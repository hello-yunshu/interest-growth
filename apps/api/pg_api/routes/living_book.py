from __future__ import annotations
from typing import Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from ..db import LivingBookChapterModel, LivingBookModel, get_session_factory
from ..domains import filter_rows_to_current_area
from ..features import feature_enabled
from ..living_book import book_bundle, compile_local_book, confirm_projected_proposal, confirm_projected_spine, create_book, project_book
from ..plugins import require_plugin_access
from ..serializers import model_dict
from ..native_execution import resolve_native_context
router = APIRouter(tags=['living-book'])
class BookCreate(BaseModel):
    topic_id: str
    title: str = Field(min_length=1)
    intent: str = ''
    knowledge_base_ids: list[str] = []
class ProposalConfirm(BaseModel): proposal: dict[str, Any] | None = None
class SpineConfirm(BaseModel):
    spine: dict[str, Any] | None = None
    auto_compile: bool = False
def _require(*, read=(), write=(), risks=()):
    require_plugin_access('capability.living-book', read=read, write=write, risks=risks)
    if not feature_enabled('FEATURE_LIVING_BOOK'): raise HTTPException(503, 'Living Book disabled')
@router.get('/living-books')
def books(include_archived: bool = False):
    _require(read=('living_book',))
    with get_session_factory()() as db:
        stmt = select(LivingBookModel).order_by(LivingBookModel.updated_at.desc())
        if not include_archived: stmt = stmt.where(LivingBookModel.status != 'archived')
        return {'books': [model_dict(x) for x in filter_rows_to_current_area(db, db.scalars(stmt).all(), 'living_book')]}
@router.post('/living-books')
def add_book(body: BookCreate):
    _require(read=('topic','knowledge_base'), write=('living_book',))
    try: return model_dict(create_book(**body.model_dump()))
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
@router.get('/living-books/{book_id}')
def get_book(book_id: str):
    _require(read=('living_book','living_book_chapter'))
    try: book, chapters = book_bundle(book_id)
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc
    return {'book': model_dict(book), 'chapters': [model_dict(x) for x in chapters]}
@router.post('/living-books/{book_id}/compile')
def compile_book(book_id: str):
    _require(read=('living_book','topic','concept','claim','claim_version','evidence','source','learning_note','practice_item','learning_activity'), write=('living_book','living_book_chapter'))
    try: book, chapters = compile_local_book(book_id)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc
    return {'book': model_dict(book), 'chapters': [model_dict(x) for x in chapters]}
@router.post('/living-books/{book_id}/project')
async def project(book_id: str, request: Request):
    _require(read=('living_book','living_book_chapter','topic','concept','claim','claim_version','evidence','source'), write=('living_book',), risks=('network','llm'))
    try: return model_dict(await project_book(book_id, resolve_native_context(request, 'book.run')))
    except (ValueError, RuntimeError) as exc: raise HTTPException(409, str(exc)) from exc
@router.post('/living-books/{book_id}/confirm-proposal')
async def confirm_proposal(book_id: str, body: ProposalConfirm):
    _require(read=('living_book',), write=('living_book',), risks=('network','llm'))
    try: return model_dict(await confirm_projected_proposal(book_id, body.proposal))
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc
@router.post('/living-books/{book_id}/confirm-spine')
async def confirm_spine(book_id: str, body: SpineConfirm):
    _require(read=('living_book',), write=('living_book',), risks=('network','llm'))
    try:
        book, upstream = await confirm_projected_spine(book_id, body.spine, auto_compile=body.auto_compile)
        return {'book': model_dict(book), 'upstream': upstream}
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc

@router.post('/living-books/{book_id}/archive')
def archive_book(book_id: str):
    _require(read=('living_book',), write=('living_book',))
    with get_session_factory()() as db:
        book = db.get(LivingBookModel, book_id)
        if not book: raise HTTPException(404, 'living book not found')
        try: from ..domains import require_entity_in_current_area; require_entity_in_current_area(db, 'living_book', book_id)
        except ValueError as exc: raise HTTPException(404, str(exc)) from exc
        book.status = 'archived'; db.commit(); db.refresh(book); return model_dict(book)

@router.post('/living-books/{book_id}/restore')
def restore_book(book_id: str):
    _require(read=('living_book',), write=('living_book',))
    with get_session_factory()() as db:
        book = db.get(LivingBookModel, book_id)
        if not book: raise HTTPException(404, 'living book not found')
        try: from ..domains import require_entity_in_current_area; require_entity_in_current_area(db, 'living_book', book_id)
        except ValueError as exc: raise HTTPException(404, str(exc)) from exc
        book.status = 'compiled' if book.source_fingerprint else 'draft'; db.commit(); db.refresh(book); return model_dict(book)

@router.delete('/living-books/{book_id}')
def delete_book(book_id: str):
    _require(read=('living_book', 'living_book_chapter'), write=('living_book', 'living_book_chapter'))
    with get_session_factory()() as db:
        book = db.get(LivingBookModel, book_id)
        if not book: raise HTTPException(404, 'living book not found')
        try: from ..domains import require_entity_in_current_area; require_entity_in_current_area(db, 'living_book', book_id)
        except ValueError as exc: raise HTTPException(404, str(exc)) from exc
        chapters = db.scalars(select(LivingBookChapterModel).where(LivingBookChapterModel.book_id == book_id)).all()
        for chapter in chapters: db.delete(chapter)
        db.delete(book); db.commit()
    return {'id': book_id, 'deleted': True, 'chapters_deleted': len(chapters)}
