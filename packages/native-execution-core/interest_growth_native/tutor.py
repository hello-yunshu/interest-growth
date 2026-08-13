from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .capabilities import CAP_TUTOR, CapabilityRegistry
from .context import NativeRunContext
from .errors import InvalidStateTransition, NativeExecutionError
from .events import RuntimeEvent
from .execution_store import (
    SQLiteExecutionStore, RunRecord,
    RUNNING, WAITING, COMPLETED, CANCELLED, ERROR, TERMINAL,
)
from .llm import LLMClient, LLMResponse, LLMStreamEvent
from .signals import LearningActivityCandidate
from .tools import ToolRegistry

@dataclass(frozen=True, slots=True)
class TutorTurnResult:
    run: RunRecord
    events: tuple[RuntimeEvent, ...]

class NativeTutorExecutor:
    """v0.3-compatible execution semantics on the v0.6 execution-only architecture.

    Key invariants:
    - only answer-visible content enters assistant_text;
    - tool-round narration never pollutes the final answer;
    - wait/resume continues from a persisted same-turn execution snapshot;
    - events have a replay sequence cursor;
    - raw tool bodies are not published as ActivityTrace;
    - RAG tool output emits sanitized `sources` provenance;
    - model Tool names are re-authorized at execution time;
    - terminal cancellation wins over late LLM completion.
    """

    BASELINE_TOOLS = (
        "read_memory", "read_skill", "read_source",
        "web_search", "reason", "brainstorm",
    )

    def __init__(
        self,
        *,
        store: SQLiteExecutionStore,
        llm: LLMClient,
        capabilities: CapabilityRegistry,
        tools: ToolRegistry,
        max_tool_rounds: int = 8,
    ) -> None:
        self.store=store;self.llm=llm;self.capabilities=capabilities;self.tools=tools
        self.max_tool_rounds=max(1,min(int(max_tool_rounds),32))

    def _emit(self,event:RuntimeEvent,event_sink=None)->RuntimeEvent:
        persisted=self.store.append_event(event)
        if event_sink is not None:
            try:event_sink(persisted)
            except Exception:
                # UI/event subscriber failure must never corrupt run state.
                pass
        return persisted

    def _event(self,typ,run,context,payload,event_sink=None):
        return self._emit(RuntimeEvent(typ,run.id,context.area_id,context.session_id,payload),event_sink)

    def _system_prompt(self,c:NativeRunContext)->str:
        blocks=[
            "You are the Interest Growth learning execution assistant.",
            f"Interest Area={c.area_id}; Domain Pack={c.domain_pack_id}.",
            "Use only current-Area authorized context. Retrieval is candidate_not_evidence.",
            "Do not expose private chain-of-thought. Public activity may describe tools/status only.",
        ]
        if c.domain_policy.learning_instructions:blocks.append("Domain learning policy:\n"+c.domain_policy.learning_instructions)
        if c.domain_policy.safety_instructions:blocks.append("Safety:\n"+c.domain_policy.safety_instructions)
        if c.persona_context:blocks.append("Persona:\n"+c.persona_context)
        if c.skills_manifest:blocks.append("Skills manifest:\n"+c.skills_manifest)
        if c.memory_context:blocks.append("Auxiliary memory:\n"+c.memory_context)
        if c.source_manifest:blocks.append("Source manifest:\n"+c.source_manifest)
        selected=self.capabilities.selected(c)
        if selected and selected.prompt_factory:
            b=selected.prompt_factory(c)
            if b and b.content:blocks.append(f"{b.name}:\n{b.content}")
        return "\n\n".join(blocks)

    def _granted_tools(self,c):
        names=self.capabilities.compose_tools(c,self.BASELINE_TOOLS)
        names=self.tools.granted_names(c,names)
        if "ask_user" not in names and any(x.name=="ask_user" for x in self.tools.list()):
            names=tuple(sorted({*names,"ask_user"}))
        return names

    def _snapshot(self,c,messages,granted_tools,*,pending_call=None):
        return {
            "messages": messages,
            "granted_tools": list(granted_tools),
            "area_id": c.area_id,
            "session_id": c.session_id,
            "selected_capability": c.selected_capability,
            "knowledge_base_ids": list(c.knowledge_base_ids),
            "domain_pack_id": c.domain_pack_id,
            "domain_policy_version": c.domain_policy.version,
            "persona_fingerprint": c.persona_fingerprint,
            "skills_fingerprint": c.skills_fingerprint,
            "config_overrides": dict(c.config_overrides),
            "pending_call": pending_call,
        }

    def _initial_messages(self,c):
        return [
            {"role":"system","content":self._system_prompt(c)},
            *list(c.conversation_history),
            {"role":"user","content":c.user_message},
        ]

    def _terminal_after_race(self,run_id,c):
        current=self.store.load(run_id,area_id=c.area_id)
        return current if current.state in TERMINAL else None

    def _transition_or_race(self,run,c,to_state,**kwargs):
        try:
            return self.store.transition(
                run.id,area_id=c.area_id,from_states={RUNNING},
                to_state=to_state,expected_version=run.version,**kwargs
            )
        except InvalidStateTransition:
            terminal=self._terminal_after_race(run.id,c)
            if terminal:return terminal
            raise

    def _fail(self,run,c,events,exc,event_sink):
        current=self.store.load(run.id,area_id=c.area_id)
        if current.state==CANCELLED:return TutorTurnResult(current,tuple(events))
        if current.state==RUNNING:
            try:
                current=self.store.transition(
                    current.id,area_id=c.area_id,from_states={RUNNING},
                    to_state=ERROR,expected_version=current.version,
                    assistant_text=current.assistant_text,
                )
            except InvalidStateTransition:
                current=self.store.load(run.id,area_id=c.area_id)
        if current.state==ERROR:
            events.append(self._event("error",current,c,{"error_type":type(exc).__name__,"code":"runtime_failure"},event_sink))
            events.append(self._event("done",current,c,{"state":"error"},event_sink))
        return TutorTurnResult(current,tuple(events))

    def _call_round(self,*,messages,schemas,temperature,event_sink,run,c):
        """Return (answer_chunks, narration_text, tool_calls, finish_reason).

        A provider may emit explicit answer_delta stream events. Ambiguous text
        from a round that also contains tool calls is treated as narration.
        """
        answer_chunks=[];ambiguous=[];calls=[];finish=None
        if hasattr(self.llm,"stream"):
            try:
                for item in self.llm.stream(messages=messages,tools=schemas or None,temperature=temperature):
                    if self.store.load(run.id,area_id=c.area_id).state==CANCELLED:
                        return [],"",[],"cancelled"
                    if item.type=="answer_delta" and item.text:
                        # Explicitly answer-visible upstream segment: safe to stream now.
                        answer_chunks.append(item.text)
                        self._event("answer_delta",run,c,{"text":item.text},event_sink)
                    elif item.type=="narration_delta" and item.text:
                        ambiguous.append(item.text)
                    elif item.type=="tool_call" and item.tool_call:
                        calls.append(item.tool_call)
                    elif item.type=="done":
                        finish=item.finish_reason
                # If no tool call occurred, ambiguous OpenAI-compatible text becomes
                # answer-visible after the round is known to be a final answer.
                if not calls and ambiguous:
                    text="".join(ambiguous)
                    answer_chunks.append(text)
                    self._event("answer_delta",run,c,{"text":text},event_sink)
                elif calls and ambiguous:
                    self._event("activity",run,c,{"kind":"model_narration","status":"suppressed_from_answer","chars":len("".join(ambiguous))},event_sink)
                return answer_chunks,"".join(ambiguous),calls,finish
            except TypeError:
                # Adapter's stream signature is incompatible; use complete path.
                pass

        response=self.llm.complete(messages=messages,tools=schemas or None,temperature=temperature)
        if self.store.load(run.id,area_id=c.area_id).state==CANCELLED:
            return [],"",[],"cancelled"
        finish=response.finish_reason
        calls=list(response.tool_calls)
        text=response.text or ""
        visible=(response.text_visibility=="answer" or (response.text_visibility=="auto" and not calls))
        if text and visible:
            answer_chunks.append(text)
            self._event("answer_delta",run,c,{"text":text},event_sink)
        elif text:
            self._event("activity",run,c,{"kind":"model_narration","status":"suppressed_from_answer","chars":len(text)},event_sink)
        return answer_chunks,(text if not visible else ""),calls,finish

    def _run_loop(self,c,run,*,messages=None,granted_tools=None,event_sink=None):
        events=[]
        granted=tuple(granted_tools or self._granted_tools(c));granted_set=set(granted)
        schemas=self.tools.schemas(granted)
        messages=list(messages or self._initial_messages(c))
        accumulated=run.assistant_text
        continuation_count=0
        max_continuations=max(0,min(int(c.config_overrides.get("max_stream_continuations",2)),4))
        try:
            for round_no in range(self.max_tool_rounds+1):
                current=self.store.load(run.id,area_id=c.area_id)
                if current.state==CANCELLED:return TutorTurnResult(current,tuple(events))
                if current.state!=RUNNING:raise InvalidStateTransition(f"run not running: {current.state}")
                run=current
                chunks,narration,calls,finish=self._call_round(
                    messages=messages,schemas=schemas,
                    temperature=float(c.config_overrides.get("temperature",.25)),
                    event_sink=event_sink,run=run,c=c,
                )
                if chunks:accumulated+="".join(chunks)

                current=self.store.load(run.id,area_id=c.area_id)
                if current.state==CANCELLED:return TutorTurnResult(current,tuple(events))
                run=current

                if not calls and finish=="length" and continuation_count<max_continuations:
                    continuation_count+=1
                    visible_round="".join(chunks)
                    messages.extend([
                        {"role":"assistant","content":visible_round},
                        {"role":"user","content":"Continue exactly from where the previous response was truncated. Do not restart or repeat prior answer text."},
                    ])
                    snap=self._snapshot(c,messages,granted)
                    run=self.store.update_snapshot(
                        run.id,area_id=c.area_id,expected_version=run.version,
                        execution_snapshot=snap,assistant_text=accumulated,
                    )
                    continue

                if not calls:
                    snap=self._snapshot(c,messages,granted)
                    final=self._transition_or_race(
                        run,c,COMPLETED,assistant_text=accumulated,
                        execution_snapshot=snap,
                    )
                    if final.state==CANCELLED:return TutorTurnResult(final,tuple(events))
                    activity=LearningActivityCandidate(
                        c.area_id,c.session_id,CAP_TUTOR,"tutor_turn",
                        "Completed a tutor turn",
                        metadata={"selected_capability":c.selected_capability},
                    )
                    events.append(self._event("result",final,c,{"state":"completed","activity_candidate":activity.as_dict()},event_sink))
                    events.append(self._event("done",final,c,{"state":"completed"},event_sink))
                    return TutorTurnResult(final,tuple(events))

                # The assistant tool-call envelope is execution history. Any
                # accompanying text is narration and not answer-visible.
                assistant_call_msg={
                    "role":"assistant",
                    "content":narration or None,
                    "tool_calls":calls,
                }
                messages.append(assistant_call_msg)

                for call in calls:
                    current=self.store.load(run.id,area_id=c.area_id)
                    if current.state==CANCELLED:return TutorTurnResult(current,tuple(events))
                    run=current
                    name=str(call.get("name") or "")
                    args=c.bind_tool_args(name,dict(call.get("arguments") or {}))
                    if name not in granted_set:
                        raise NativeExecutionError(f"model requested ungranted tool: {name}")

                    if name=="ask_user":
                        payload={
                            "question":str(args.get("question") or args.get("prompt") or ""),
                            "choices":args.get("choices") or [],
                            "tool_call_id":call.get("id",""),
                        }
                        if isinstance(args.get("questions"),list):payload["questions"]=args["questions"]
                        snap=self._snapshot(c,messages,granted,pending_call={
                            "id":call.get("id",""),"name":"ask_user"
                        })
                        waiting=self._transition_or_race(
                            run,c,WAITING,assistant_text=accumulated,
                            wait_payload=payload,execution_snapshot=snap,
                        )
                        if waiting.state==CANCELLED:return TutorTurnResult(waiting,tuple(events))
                        events.append(self._event("wait_for_input",waiting,c,payload,event_sink))
                        return TutorTurnResult(waiting,tuple(events))

                    result=self.tools.execute_granted(
                        c,granted_names=granted_set,name=name,args=args
                    )
                    spec=self.tools.get(name)
                    if spec.source_projector is not None:
                        safe_sources=spec.source_projector(result)
                        if safe_sources:
                            events.append(self._event("sources",run,c,{"tool":name,"sources":safe_sources},event_sink))
                    events.append(self._event("activity",run,c,{"kind":"tool_result","tool":name,"status":"ok","result_type":type(result).__name__},event_sink))
                    messages.append({
                        "role":"tool","tool_call_id":call.get("id",""),
                        "name":name,
                        "content":json.dumps(result,ensure_ascii=False,default=str),
                    })
                    # Persist every completed tool result so wait/resume or
                    # process recovery never loses earlier same-turn context.
                    snap=self._snapshot(c,messages,granted)
                    run=self.store.update_snapshot(
                        run.id,area_id=c.area_id,expected_version=run.version,
                        execution_snapshot=snap,assistant_text=accumulated,
                    )

            raise NativeExecutionError("max_tool_rounds_exceeded")
        except Exception as exc:
            return self._fail(run,c,events,exc,event_sink)

    def start(self,c:NativeRunContext,*,event_sink=None):
        c.validate();c.require_capability(CAP_TUTOR);c.permission_scope.require_write("tutor")
        granted=self._granted_tools(c);messages=self._initial_messages(c)
        binding=c.host_tutor
        run=self.store.create_run(
            area_id=c.area_id,session_id=c.session_id,user_message=c.user_message,
            selected_capability=c.selected_capability,
            host_session_id=binding.tutor_session_id if binding else None,
            host_turn_id=binding.tutor_turn_id if binding else None,
            execution_snapshot=self._snapshot(c,messages,granted),
        )
        self._event("activity",run,c,{"kind":"run_started","selected_capability":c.selected_capability},event_sink)
        result=self._run_loop(c,run,messages=messages,granted_tools=granted,event_sink=event_sink)
        return TutorTurnResult(result.run,self._events_internal(result.run.id,c.area_id))

    def load(self,c,run_id):
        c.permission_scope.require_read("tutor")
        r=self.store.load(run_id,area_id=c.area_id)
        if r.session_id!=c.session_id:raise InvalidStateTransition("run belongs to another session")
        return r

    def _events_internal(self,run_id,area_id,*,after_seq=0):
        rows=self.store.events(run_id,area_id=area_id,after_seq=after_seq,limit=5000)
        return tuple(RuntimeEvent(
            r["event_type"],run_id,r["area_id"],r["session_id"],
            self.store.loads(r["payload_json"],{}),int(r["seq"]),r["created_at"]
        ) for r in rows)

    def replay(self,c,run_id,*,after_seq=0,limit=1000):
        self.load(c,run_id)
        rows=self.store.events(run_id,area_id=c.area_id,after_seq=after_seq,limit=limit)
        return tuple(RuntimeEvent(
            r["event_type"],run_id,r["area_id"],r["session_id"],
            self.store.loads(r["payload_json"],{}),int(r["seq"]),r["created_at"]
        ) for r in rows)

    def resume(self,c,*,run_id,user_input="",answers=None,event_sink=None):
        c.validate();c.require_capability(CAP_TUTOR);c.permission_scope.require_write("tutor")
        prior=self.load(c,run_id)
        if prior.state!=WAITING:raise InvalidStateTransition("only waiting runs can resume")
        if prior.selected_capability:
            c.require_capability(prior.selected_capability)
        previous_events=self.store.events(run_id,area_id=c.area_id,after_seq=0,limit=5000)
        prior_seq=int(previous_events[-1]["seq"]) if previous_events else 0
        snap=prior.execution_snapshot or {}
        if snap.get("area_id")!=c.area_id or snap.get("session_id")!=c.session_id:
            raise InvalidStateTransition("execution snapshot scope mismatch")
        messages=list(snap.get("messages") or [])
        # Historical authorization must not become future executable grants.
        # The resumed turn may only keep tools still granted under the CURRENT
        # context (capability, PermissionScope, network/LLM risk, Area,
        # tool eligibility). New permissions granted while paused do not
        # automatically expand an older turn's grant.
        snap_granted=tuple(snap.get("granted_tools") or ())
        current_granted=self._granted_tools(c)
        granted=tuple(x for x in snap_granted if x in set(current_granted))
        pending=snap.get("pending_call") or {}
        cleaned=[]
        for item in answers or ():
            if not isinstance(item,dict):continue
            qid=str(item.get("questionId") or item.get("id") or "").strip()
            if qid:cleaned.append({"questionId":qid,"text":str(item.get("text") or "")})
        payload={"text":str(user_input or ""),"answers":cleaned}
        # Continue the exact paused tool call; do not rebuild the pre-wait turn.
        messages.append({
            "role":"tool",
            "tool_call_id":pending.get("id") or (prior.wait_payload or {}).get("tool_call_id",""),
            "name":"ask_user",
            "content":json.dumps(payload,ensure_ascii=False),
        })
        running=self.store.transition(
            run_id,area_id=c.area_id,from_states={WAITING},to_state=RUNNING,
            expected_version=prior.version,assistant_text=prior.assistant_text,
            execution_snapshot=self._snapshot(c,messages,granted),
        )
        # Preserve original turn selection/snapshotted execution context.
        turn_context=c.child(
            user_message=prior.user_message,
            selected_capability=prior.selected_capability,
            knowledge_base_ids=tuple(snap.get("knowledge_base_ids") or c.knowledge_base_ids),
            config_overrides=dict(snap.get("config_overrides") or c.config_overrides),
        )
        self._event("activity",running,turn_context,{"kind":"run_resumed","structured_answers":len(cleaned)},event_sink)
        result=self._run_loop(turn_context,running,messages=messages,granted_tools=granted,event_sink=event_sink)
        return TutorTurnResult(result.run,self._events_internal(result.run.id,c.area_id,after_seq=prior_seq))

    def cancel(self,c,run_id,*,event_sink=None):
        c.validate();c.require_capability(CAP_TUTOR);c.permission_scope.require_write("tutor")
        prior=self.load(c,run_id)
        if prior.state not in {RUNNING,WAITING}:raise InvalidStateTransition(f"cannot cancel {prior.state}")
        cancelled=self.store.transition(
            run_id,area_id=c.area_id,from_states={prior.state},to_state=CANCELLED,
            expected_version=prior.version,assistant_text=prior.assistant_text,
        )
        self._event("activity",cancelled,c,{"kind":"run_cancelled"},event_sink)
        self._event("done",cancelled,c,{"state":"cancelled"},event_sink)
        return cancelled

    def regenerate(self,c,run_id,*,event_sink=None):
        c.validate();c.require_capability(CAP_TUTOR);c.permission_scope.require_write("tutor")
        prior=self.load(c,run_id)
        if prior.state not in TERMINAL:raise InvalidStateTransition("regenerate requires terminal run")
        child_context=c.child(user_message=prior.user_message,selected_capability=prior.selected_capability)
        granted=self._granted_tools(child_context);messages=self._initial_messages(child_context)
        run=self.store.create_run(
            area_id=c.area_id,session_id=c.session_id,user_message=prior.user_message,
            selected_capability=prior.selected_capability,parent_run_id=prior.id,
            host_session_id=prior.host_session_id,host_turn_id=prior.host_turn_id,
            execution_snapshot=self._snapshot(child_context,messages,granted),
        )
        self._event("activity",run,child_context,{"kind":"run_regenerated","parent_run_id":prior.id},event_sink)
        res=self._run_loop(child_context,run,messages=messages,granted_tools=granted,event_sink=event_sink)
        return TutorTurnResult(res.run,self._events_internal(res.run.id,c.area_id))
