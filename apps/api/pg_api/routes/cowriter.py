from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..cowriter import create_document, decide_revision, document_bundle, list_documents, propose_revision, update_document
from ..features import feature_enabled
from ..plugins import require_plugin_access
from ..serializers import model_dict
from ..native_execution import resolve_native_context

router = APIRouter(tags=['co-writer'])

class DocumentCreate(BaseModel):
    title: str = Field(min_length=1)
    content_markdown: str = ''
    topic_id: str | None = None

class DocumentUpdate(BaseModel):
    title: str | None = None
    content_markdown: str | None = None
    status: str | None = None

class RevisionCreate(BaseModel):
    selected_text: str = Field(min_length=1)
    instruction: str = ''
    mode: str = 'rewrite'
    tools: list[str] = []
    knowledge_base_id: str | None = None

class RevisionDecision(BaseModel):
    accept: bool


def _require(*, read=(), write=(), risks=()):
    require_plugin_access('capability.co-writer', read=read, write=write, risks=risks)
    if not feature_enabled('FEATURE_CO_WRITER'):
        raise HTTPException(503, 'Co-Writer disabled')

@router.get('/writing/documents')
def documents():
    _require(read=('writing_document',)); return {'documents': [model_dict(x) for x in list_documents()]}

@router.post('/writing/documents')
def add_document(body: DocumentCreate):
    _require(read=('topic',), write=('writing_document',))
    try: return model_dict(create_document(**body.model_dump()))
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc

@router.get('/writing/documents/{document_id}')
def get_document(document_id: str):
    _require(read=('writing_document','writing_revision'))
    try:
        doc, revisions = document_bundle(document_id)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc
    return {'document': model_dict(doc), 'revisions': [model_dict(x) for x in revisions]}

@router.put('/writing/documents/{document_id}')
def edit_document(document_id: str, body: DocumentUpdate):
    _require(read=('writing_document',), write=('writing_document',))
    try: return model_dict(update_document(document_id, **body.model_dump(exclude_none=True)))
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc

@router.post('/writing/documents/{document_id}/revisions')
async def add_revision(document_id: str, body: RevisionCreate, request: Request):
    _require(read=('writing_document','writing_revision'), write=('writing_revision',), risks=('llm',))
    try:
        context = resolve_native_context(request, 'cowriter.run')
        return model_dict(await propose_revision(document_id, native_context=context, **body.model_dump()))
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc: raise HTTPException(503, str(exc)) from exc

@router.post('/writing/revisions/{revision_id}/decide')
def decide(revision_id: str, body: RevisionDecision):
    _require(read=('writing_revision','writing_document'), write=('writing_revision','writing_document'))
    try: revision, document = decide_revision(revision_id, accept=body.accept)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc
    return {'revision': model_dict(revision), 'document': model_dict(document)}
