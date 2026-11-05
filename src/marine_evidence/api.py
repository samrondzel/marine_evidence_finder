"""Local FastAPI app for uploading and querying marine science PDFs.

Launch from project root: python -m uvicorn marine_evidence.api:app --host 127.0.0.1 --port 8000
No authentication: NEVER bind to 0.0.0.0 or deploy publicly without adding auth/security.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .answer import AnswerError, answer_question
from .corpus_store import CorpusStore, DocumentError, MAX_UPLOAD_BYTES


class Query(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)
    distinct_pages: bool = False


class AskQuery(Query):
    model: str = Field(default='gpt-5-mini', min_length=1, max_length=120)


def create_app(*, store: CorpusStore | None = None, root: Path | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(api: FastAPI):
        api.state.store = store if store is not None else CorpusStore.from_project(root or Path.cwd())
        yield

    api = FastAPI(title='Marine Evidence Finder', version='0.2.0', lifespan=lifespan,
                  description='Local PDF upload, BM25 evidence retrieval and cited research answers.')

    def collection(request: Request) -> CorpusStore:
        return request.app.state.store

    @api.get('/health')
    def health(request: Request):
        s = collection(request)
        return {'status': 'ok', 'documents': len(s.list_documents()), 'chunks': s.chunk_count,
                'retriever': 'bm25'}

    @api.get('/documents')
    def documents(request: Request):
        return {'documents': collection(request).list_documents()}

    @api.post('/documents', status_code=201)
    async def upload(request: Request, file: Annotated[UploadFile, File(description='Text-based PDF, max 25 MiB')]):
        if not file.filename or not file.filename.lower().endswith('.pdf'):
            raise HTTPException(422, 'Only .pdf documents are supported')
        try:
            data = await file.read(MAX_UPLOAD_BYTES + 1)
        finally:
            await file.close()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, 'PDF exceeds the 25 MiB limit')
        try:
            record, duplicate = await run_in_threadpool(collection(request).upload_pdf, data, file.filename)
        except DocumentError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {'document': record, 'duplicate': duplicate, 'indexed_chunks': collection(request).chunk_count}

    @api.delete('/documents/{source_id}')
    def remove_document(request: Request, source_id: str):
        try:
            if not collection(request).delete_upload(source_id):
                raise HTTPException(404, 'Document not found')
        except DocumentError as exc:
            raise HTTPException(403, str(exc)) from exc
        return {'deleted': source_id, 'indexed_chunks': collection(request).chunk_count}

    @api.get('/documents/{source_id}/pdf')
    def open_pdf(request: Request, source_id: str):
        result = collection(request).pdf_path(source_id)
        if result is None or not result[0].is_file():
            raise HTTPException(404, 'PDF unavailable')
        path, filename = result
        return FileResponse(path, media_type='application/pdf', filename=filename,
                            content_disposition_type='inline', headers={'X-Content-Type-Options': 'nosniff'})

    @api.post('/search')
    def search(request: Request, q: Query):
        hits = collection(request).search(q.question, top_k=q.top_k, distinct_pages=q.distinct_pages)
        return {'question': q.question, 'hits': hits, 'total': len(hits), 'retriever': 'bm25'}

    @api.post('/ask')
    def ask(request: Request, q: AskQuery):
        # The user/UI calls this endpoint explicitly. It makes a paid API call
        # only when the BM25 retriever found evidence and OPENAI_API_KEY exists.
        try:
            return answer_question(q.question, collection(request).snapshot_index(),
                                   model=q.model, top_k=q.top_k, distinct_pages=q.distinct_pages)
        except AnswerError as exc:
            message = str(exc)
            code = 503 if ('OPENAI_API_KEY' in message or 'Install requirements' in message) else 502
            raise HTTPException(code, message) from exc

    return api


app = create_app()
