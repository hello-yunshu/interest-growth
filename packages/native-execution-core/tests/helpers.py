from interest_growth_native.capabilities import *
from interest_growth_native.contracts import DomainPolicy,KnowledgeBaseSnapshot,SourceTextSnapshot,SourceLocator
from interest_growth_native.context import NativeRunContext,PermissionScope
from interest_growth_native.execution_store import SQLiteExecutionStore

ALL_CAPS=frozenset({
    CAP_TUTOR,CAP_RESEARCH,CAP_KNOWLEDGE,CAP_MASTERY,CAP_PRACTICE,
    CAP_NOTEBOOK,CAP_COWRITER,CAP_BOOK,CAP_VISUALIZE,CAP_DEEP_SOLVE,
})
ALL_PERMS=PermissionScope(
    resources_read=frozenset({"knowledge","tutor","agent_memory"}),
    resources_write=frozenset({"tutor","agent_memory"}),
    risks=frozenset({"llm","network"}),
)
def policy(id="general",profile=None):
    return DomainPolicy(id,mastery_profile=tuple(profile or (
        "unfamiliar","familiar","understand","practice","apply","reflect","transfer","self_directed"
    )),version="p1")
def ctx(area="a",session="s",caps=ALL_CAPS,global_caps=ALL_CAPS,perms=ALL_PERMS,domain=None,**kw):
    return NativeRunContext(
        area_id=area,session_id=session,domain_policy=domain or policy(),
        area_capabilities=frozenset(caps),global_capabilities=frozenset(global_caps),
        permission_scope=perms,**kw
    )
class StaticResolver:
    def __init__(self,kbs):self.kbs={x.kb_id:x for x in kbs}
    def resolve(self,*,area_id,kb_ids):
        return tuple(self.kbs[k] for k in kb_ids if k in self.kbs and self.kbs[k].area_id==area_id)
def kb(area="a",kid="k",engine="native-lexical",text="watercolor wet paper makes soft edges",source="src",fingerprint="",source_fp="",page=1):
    return KnowledgeBaseSnapshot(
        kid,area,"KB",engine,
        (SourceTextSnapshot(source,area,"x.md",text,source_fp,SourceLocator(filename="x.md",page=page,section="sec")),),
        fingerprint=fingerprint,
    )
def store():return SQLiteExecutionStore(":memory:")
