from dataclasses import asdict
from typing import Any, Callable

from .bundle import NativeEngineBundle
from .context import NativeRunContext
from .errors import (
    CapabilityUnavailable,PermissionDenied,ProviderUnavailable,
    AreaIsolationError,InvalidStateTransition,ValidationError,
    LegacyEngineReviewRequired,StaleProposalError,
)
from .research import ResearchSubtopic
from .contracts import PracticeOrigin

def create_native_router(
    bundle:NativeEngineBundle,*,
    context_resolver:Callable[[Any,str],NativeRunContext],
):
    try:
        from fastapi import APIRouter,Request,HTTPException
        from pydantic import BaseModel,Field
    except ImportError as exc:
        raise RuntimeError("FastAPI/Pydantic optional dependencies required") from exc

    router=APIRouter(prefix="/api/native-execution",tags=["native-execution"])

    def ctx(request,operation):
        try:
            c=context_resolver(request,operation);c.validate();return c
        except (CapabilityUnavailable,PermissionDenied,AreaIsolationError) as exc:
            raise HTTPException(403,str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(422,str(exc)) from exc

    def guard(fn):
        try:return fn()
        except (CapabilityUnavailable,PermissionDenied,AreaIsolationError) as exc:
            raise HTTPException(403,str(exc)) from exc
        except ProviderUnavailable as exc:raise HTTPException(503,str(exc)) from exc
        except (InvalidStateTransition,LegacyEngineReviewRequired,StaleProposalError) as exc:
            raise HTTPException(409,str(exc)) from exc
        except ValidationError as exc:raise HTTPException(422,str(exc)) from exc

    class Retrieve(BaseModel):
        kb_ids:list[str];query:str;top_k:int=Field(default=6,ge=1,le=20)
    class ResearchBody(BaseModel):
        question:str;kb_ids:list[str]=Field(default_factory=list);depth:str="normal"
    class ResearchPreview(BaseModel):
        question:str;clarification_answers:list[str]=Field(default_factory=list);max_subtopics:int=Field(default=5,ge=2,le=8)
    class ResearchSubtopicBody(BaseModel):
        title:str;overview:str=""
    class ResearchConfirmed(BaseModel):
        question:str;subtopics:list[ResearchSubtopicBody];kb_ids:list[str]=Field(default_factory=list);max_queue:int=Field(default=8,ge=1,le=16)
    class TutorStart(BaseModel):
        user_message:str;selected_capability:str|None=None;kb_ids:list[str]=Field(default_factory=list)
    class TutorAnswer(BaseModel):
        questionId:str;text:str=""
    class TutorResume(BaseModel):
        user_input:str="";answers:list[TutorAnswer]=Field(default_factory=list)
    class MasteryBody(BaseModel):
        goal:str;current_stage:str
    class DeepQuestionBody(BaseModel):
        concept:str;stage:str
    class PracticeBody(BaseModel):
        topic:str;material:str;count:int=Field(default=3,ge=1,le=10);concept_ids:list[str]=Field(default_factory=list)
    class NoteBody(BaseModel):
        title:str;body:str
    class CoWriteBody(BaseModel):
        base_revision_id:str
        current_document_text:str
        selection_start:int
        selection_end:int
        instruction:str
        surrounding_context:str=""
    class BookBody(BaseModel):
        title:str;purpose:str;chapter_hints:list[str]=Field(default_factory=list)
    class VisualBody(BaseModel):
        title:str;content:str;kind:str="concept_map"
    class SolveBody(BaseModel):
        problem:str;max_replans:int=Field(default=1,ge=0,le=3)

    @router.get("/health")
    def health():return bundle.health()

    @router.get("/rag/engines")
    def rag_engines(request:Request):
        _=ctx(request,"knowledge.read");return [asdict(x) for x in bundle.retrieval.registry.list()]

    @router.get("/rag/legacy/{engine_id}")
    def rag_legacy(engine_id:str,request:Request):
        _=ctx(request,"knowledge.read");m=bundle.retrieval.registry.legacy_migration(engine_id)
        return asdict(m) if m else None

    @router.post("/retrieve")
    def retrieve(body:Retrieve,request:Request):
        c=ctx(request,"knowledge.read")
        return guard(lambda:[asdict(x) for x in bundle.retrieval.retrieve(c,kb_ids=body.kb_ids,query=body.query,top_k=body.top_k)])

    @router.post("/research")
    def research(body:ResearchBody,request:Request):
        c=ctx(request,"research.run")
        return guard(lambda:asdict(bundle.research.research(c,question=body.question,kb_ids=body.kb_ids,depth=body.depth)))

    @router.post("/research/deep/preview")
    def research_preview(body:ResearchPreview,request:Request):
        c=ctx(request,"research.run")
        return guard(lambda:asdict(bundle.research.preview_outline(c,question=body.question,clarification_answers=body.clarification_answers,max_subtopics=body.max_subtopics)))

    @router.post("/research/deep/run")
    def research_run(body:ResearchConfirmed,request:Request):
        c=ctx(request,"research.run")
        return guard(lambda:asdict(bundle.research.run_confirmed(
            c,question=body.question,
            subtopics=tuple(ResearchSubtopic(x.title,x.overview) for x in body.subtopics),
            kb_ids=tuple(body.kb_ids),max_queue=body.max_queue,outline_status="host_confirmed",
        )))

    @router.post("/tutor")
    def tutor_start(body:TutorStart,request:Request):
        c=ctx(request,"tutor.write").child(
            user_message=body.user_message,selected_capability=body.selected_capability,
            knowledge_base_ids=tuple(body.kb_ids),
        )
        def go():
            r=bundle.tutor.start(c);return {"run":asdict(r.run),"events":[x.as_dict() for x in r.events]}
        return guard(go)

    @router.get("/tutor/{run_id}/events")
    def tutor_events(run_id:str,request:Request,after_seq:int=0,limit:int=1000):
        c=ctx(request,"tutor.read")
        return guard(lambda:[x.as_dict() for x in bundle.tutor.replay(c,run_id,after_seq=after_seq,limit=limit)])

    @router.post("/tutor/{run_id}/resume")
    def tutor_resume(run_id:str,body:TutorResume,request:Request):
        c=ctx(request,"tutor.write")
        def go():
            r=bundle.tutor.resume(c,run_id=run_id,user_input=body.user_input,answers=[x.model_dump() for x in body.answers])
            return {"run":asdict(r.run),"events":[x.as_dict() for x in r.events]}
        return guard(go)

    @router.post("/tutor/{run_id}/cancel")
    def tutor_cancel(run_id:str,request:Request):
        c=ctx(request,"tutor.write");return guard(lambda:asdict(bundle.tutor.cancel(c,run_id)))

    @router.post("/tutor/{run_id}/regenerate")
    def tutor_regenerate(run_id:str,request:Request):
        c=ctx(request,"tutor.write")
        def go():
            r=bundle.tutor.regenerate(c,run_id);return {"run":asdict(r.run),"events":[x.as_dict() for x in r.events]}
        return guard(go)

    @router.post("/learning/mastery-path")
    def mastery(body:MasteryBody,request:Request):
        c=ctx(request,"learning.run");return guard(lambda:asdict(bundle.learning.mastery_path(c,goal=body.goal,current_stage=body.current_stage)))

    @router.post("/learning/deep-question")
    def deepq(body:DeepQuestionBody,request:Request):
        c=ctx(request,"learning.run");return guard(lambda:asdict(bundle.learning.deep_question(c,concept=body.concept,stage=body.stage)))

    @router.post("/notebook/propose")
    def note(body:NoteBody,request:Request):
        c=ctx(request,"notebook.run");return guard(lambda:asdict(bundle.notebook.propose_note(c,title=body.title,body=body.body)))

    @router.post("/practice/propose")
    def practice(body:PracticeBody,request:Request):
        c=ctx(request,"practice.run");return guard(lambda:[asdict(x) for x in bundle.question_notebook.propose(c,topic=body.topic,material=body.material,count=body.count,concept_ids=body.concept_ids,origin=PracticeOrigin("manual"))])

    @router.post("/cowriter/propose")
    def cowrite(body:CoWriteBody,request:Request):
        c=ctx(request,"cowriter.run")
        return guard(lambda:asdict(bundle.cowriter.propose_selection_edit(
            c,base_revision_id=body.base_revision_id,current_document_text=body.current_document_text,
            selection_start=body.selection_start,selection_end=body.selection_end,
            instruction=body.instruction,surrounding_context=body.surrounding_context,
        )))

    @router.post("/book/scaffold")
    def book(body:BookBody,request:Request):
        c=ctx(request,"book.run");return guard(lambda:asdict(bundle.book.scaffold(c,title=body.title,purpose=body.purpose,chapter_hints=body.chapter_hints or None)))

    @router.post("/visualize/plan")
    def visual(body:VisualBody,request:Request):
        c=ctx(request,"visualize.run");return guard(lambda:asdict(bundle.visualize.plan(c,title=body.title,content=body.content,kind=body.kind)))

    @router.post("/solve")
    def solve(body:SolveBody,request:Request):
        c=ctx(request,"solve.run");return guard(lambda:asdict(bundle.solve.solve(c,problem=body.problem,max_replans=body.max_replans)))

    @router.get("/memory/audit-graph")
    def memory_graph(request:Request):
        c=ctx(request,"memory.read");return guard(lambda:bundle.memory.audit_graph(c))

    return router
