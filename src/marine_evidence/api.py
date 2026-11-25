"""Local FastAPI app for uploading and querying marine science PDFs.

Launch from project root: python -m uvicorn marine_evidence.api:app --host 127.0.0.1 --port 8000
No authentication: NEVER bind to 0.0.0.0 or deploy publicly without adding auth/security.
"""
from __future__ import annotations

import logging
import os
import re
import time
from uuid import uuid4
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from .answer import AnswerError, answer_question
from .llm_usage import load_prices, usage_scope
from .corpus_store import (CorpusStore, DocumentError, MetadataStoreError, MAX_UPLOAD_BYTES,
                           _atomic_bytes, _safe_filename)
from .config import AppPaths
from .observability import (ApiMetrics, configure_logging, new_request_id,
                            request_id_context, state_snapshot)
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

logger = logging.getLogger(__name__)


class Query(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)
    distinct_pages: bool = False


class AskQuery(Query):
    model: str = Field(default='gpt-5-mini', min_length=1, max_length=120)


class AgentQuery(AskQuery):
    top_k: int = Field(default=4, ge=1, le=6)
    max_steps: int = Field(default=5, ge=2, le=6)


class HealthResponse(BaseModel):
    status: Literal['ok']
    documents: int = Field(ge=0)
    chunks: int = Field(ge=0)
    retriever: Literal['bm25']


class SearchHit(BaseModel):
    rank: int = Field(ge=1)
    score: float
    chunk_id: str
    source_id: str
    pdf_page: int = Field(ge=1)
    title: str
    filename: str
    doi: str
    text: str


class SearchResponse(BaseModel):
    question: str
    hits: list[SearchHit]
    total: int = Field(ge=0)
    retriever: Literal['bm25']


def create_app(*, store: CorpusStore | None = None, root: Path | None = None,
               jobs_repository=None, job_queue=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(api: FastAPI):
        configure_logging('api')
        db_engine = None
        try:
            if store is not None:
                api.state.store = store
            else:
                paths = AppPaths.from_environment(root)
                backend = os.environ.get('MARINE_METADATA_BACKEND', 'json').lower()
                if backend not in ('json', 'postgres'):
                    raise RuntimeError('MARINE_METADATA_BACKEND must be json or postgres')
                repo = None
                if backend == 'postgres':
                    # Imported lazily: the legacy JSON mode needs no DB extras.
                    from .db_connection import make_engine
                    from .metadata_repository import UploadedDocumentRepository
                    db_engine = make_engine()
                    repo = UploadedDocumentRepository(db_engine)
                    repo.ping()
                api.state.store = CorpusStore(
                    base_chunks_path=paths.base_chunks_path,
                    base_papers_dir=paths.base_papers_dir,
                    uploads_dir=paths.uploads_dir,
                    base_manifest_path=paths.base_manifest_path,
                    metadata_repo=repo,
                )
            api.state.redis_client = None
            api.state.jobs_repository = jobs_repository
            api.state.job_queue = job_queue
            api.state.async_ingestion_enabled = False
            if jobs_repository is not None and job_queue is not None:
                api.state.async_ingestion_enabled = True
            elif os.environ.get('MARINE_ASYNC_INGESTION') == '1':
                if db_engine is None:
                    raise RuntimeError('Asynchronous ingestion requires MARINE_METADATA_BACKEND=postgres')
                from redis import Redis
                from rq import Queue
                from .ingestion_job_repository import IngestionJobRepository
                redis_client = Redis.from_url(os.environ.get('REDIS_URL', 'redis://redis:6379/0'))
                redis_client.ping()
                api.state.redis_client = redis_client
                api.state.jobs_repository = IngestionJobRepository(db_engine)
                api.state.job_queue = Queue('marine-ingest', connection=redis_client)
                api.state.async_ingestion_enabled = True
            yield
        finally:
            if db_engine is not None:
                db_engine.dispose()

    api = FastAPI(title='Marine Evidence Finder', version='0.2.0', lifespan=lifespan,
                  description='Local PDF upload, BM25 evidence retrieval and cited research answers.')
    api.state.api_metrics = ApiMetrics()
    api.state.llm_prices = load_prices()

    @api.middleware('http')
    async def instrument_http(request: Request, call_next):
        # Server-generated request ID avoids trusting an arbitrary client header.
        request_id = new_request_id()
        token = request_id_context.set(request_id)
        started = time.perf_counter()
        metrics = request.app.state.api_metrics
        observe = request.url.path not in ('/metrics', '/health/live', '/health/ready')
        if observe:
            metrics.in_flight.inc()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers['X-Request-ID'] = request_id
            return response
        finally:
            seconds = time.perf_counter() - started
            if observe:
                # FastAPI attaches the *template*, e.g. /ingestion-jobs/{job_id}.
                # Never use raw request.url.path: it contains unbounded job IDs.
                route = request.scope.get('route')
                template = getattr(route, 'path', '_unmatched')
                safe_method = request.method if request.method in (
                    'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'
                ) else '_other'
                metrics.observe(safe_method, template, status, seconds)
                metrics.in_flight.dec()
                logger.info('http_request_complete', extra={
                    'event': 'http_request_complete', 'http_method': safe_method,
                    'http_route': template, 'status_code': status,
                    'duration_ms': round(seconds * 1000, 2),
                })
            request_id_context.reset(token)

    def observation_state(request: Request) -> dict:
        return state_snapshot(
            request.app.state.jobs_repository if request.app.state.async_ingestion_enabled else None,
            request.app.state.job_queue if request.app.state.async_ingestion_enabled else None,
            request.app.state.redis_client,
        )

    @api.get('/ops/status', include_in_schema=True)
    def ops_status(request: Request):
        try:
            return observation_state(request)
        except Exception as exc:
            logger.exception('Could not collect operational status')
            raise HTTPException(503, 'Operational dependencies unavailable') from exc

    @api.get('/metrics', include_in_schema=False)
    def prometheus_metrics(request: Request):
        try:
            request.app.state.api_metrics.set_snapshot(observation_state(request))
        except Exception as exc:
            logger.exception('Prometheus scrape failed')
            raise HTTPException(503, 'Could not collect operational metrics') from exc
        return Response(generate_latest(request.app.state.api_metrics.registry),
                        media_type=CONTENT_TYPE_LATEST)


    def collection(request: Request) -> CorpusStore:
        s = request.app.state.store
        if request.app.state.async_ingestion_enabled:
            try:
                s.refresh_from_metadata_repo()
            except MetadataStoreError as exc:
                raise HTTPException(503, str(exc)) from exc
        return s

    @api.get('/health', response_model=HealthResponse)
    def health(request: Request):
        s = collection(request)
        return {'status': 'ok', 'documents': len(s.list_documents()), 'chunks': s.chunk_count,
                'retriever': 'bm25'}

    @api.get('/health/live')
    def live():
        # Liveness must not perform disk access, DB queries or LLM calls.
        return {'status': 'alive'}

    @api.get('/health/ready')
    def ready(request: Request):
        # For now, successful store initialization is the readiness condition.
        # When PostgreSQL is introduced, extend this to verify DB availability.
        s = collection(request)
        if s.metadata_repo is not None:
            try:
                s.metadata_repo.ping()
            except Exception as exc:
                raise HTTPException(503, 'Metadata database is not ready') from exc
        if request.app.state.redis_client is not None:
            try:
                request.app.state.redis_client.ping()
            except Exception as exc:
                raise HTTPException(503, 'Redis queue is not ready') from exc
        return {'status': 'ready', 'chunks': s.chunk_count}

    @api.post('/ingestion-jobs', status_code=202)
    async def submit_ingestion_job(
        request: Request,
        file: Annotated[UploadFile, File(description='Text-based PDF, max 25 MiB')],
    ):
        if not request.app.state.async_ingestion_enabled:
            raise HTTPException(503, 'Background ingestion is not enabled')
        try:
            filename = _safe_filename(file.filename or '')
        except DocumentError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            data = await file.read(MAX_UPLOAD_BYTES + 1)
        finally:
            await file.close()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, 'PDF exceeds the 25 MiB limit')
        if not data.startswith(b'%PDF-'):
            raise HTTPException(422, 'File does not have a valid PDF header')

        job_id = uuid4().hex
        staged = request.app.state.store.uploads_dir / 'staging' / (job_id + '.pdf')
        try:
            await run_in_threadpool(_atomic_bytes, staged, data)
            request.app.state.jobs_repository.create(job_id, filename)
        except Exception as exc:
            staged.unlink(missing_ok=True)
            raise HTTPException(503, 'Could not persist queued PDF ingestion') from exc

        try:
            # Redis receives an ID, never the PDF bytes. Worker reads from the shared mount.
            from .job_delivery import enqueue_delivery
            enqueue_delivery(request.app.state.job_queue, job_id, job_id)
        except Exception as exc:
            try:
                request.app.state.jobs_repository.fail(job_id, 'Redis enqueue failed')
                staged.unlink(missing_ok=True)
            except Exception:
                # If the DB is down, leave staging for manual recovery.
                pass
            raise HTTPException(503, 'Could not enqueue PDF ingestion') from exc
        logger.info('ingestion_job_accepted', extra={'event': 'ingestion_job_accepted',
                    'job_id': job_id, 'rq_job_id': job_id})
        return {'job_id': job_id, 'status': 'queued', 'status_url': f'/ingestion-jobs/{job_id}'}

    @api.get('/ingestion-jobs/{job_id}')
    def get_ingestion_job(request: Request, job_id: str):
        if not request.app.state.async_ingestion_enabled:
            raise HTTPException(503, 'Background ingestion is not enabled')
        if re.fullmatch(r'[a-f0-9]{32}', job_id) is None:
            raise HTTPException(404, 'Job not found')
        try:
            job = request.app.state.jobs_repository.get(job_id)
        except Exception as exc:
            raise HTTPException(503, 'Job database is unavailable') from exc
        if job is None:
            raise HTTPException(404, 'Job not found')
        return job

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
        except MetadataStoreError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {'document': record, 'duplicate': duplicate, 'indexed_chunks': collection(request).chunk_count}

    @api.delete('/documents/{source_id}')
    def remove_document(request: Request, source_id: str):
        try:
            if not collection(request).delete_upload(source_id):
                raise HTTPException(404, 'Document not found')
        except DocumentError as exc:
            raise HTTPException(403, str(exc)) from exc
        except MetadataStoreError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {'deleted': source_id, 'indexed_chunks': collection(request).chunk_count}

    @api.get('/documents/{source_id}/pdf')
    def open_pdf(request: Request, source_id: str):
        result = collection(request).pdf_path(source_id)
        if result is None or not result[0].is_file():
            raise HTTPException(404, 'PDF unavailable')
        path, filename = result
        return FileResponse(path, media_type='application/pdf', filename=filename,
                            content_disposition_type='inline', headers={'X-Content-Type-Options': 'nosniff'})

    @api.post('/search', response_model=SearchResponse)
    def search(request: Request, q: Query):
        hits = collection(request).search(q.question, top_k=q.top_k, distinct_pages=q.distinct_pages)
        return {'question': q.question, 'hits': hits, 'total': len(hits), 'retriever': 'bm25'}

    @api.post('/ask')
    def ask(request: Request, q: AskQuery):
        # The user/UI calls this endpoint explicitly. It makes a paid API call
        # only when the BM25 retriever found evidence and OPENAI_API_KEY exists.
        try:
            with usage_scope(request.app.state.llm_prices) as ledger:
                try:
                    result = answer_question(q.question, collection(request).snapshot_index(),
                                             model=q.model, top_k=q.top_k, distinct_pages=q.distinct_pages)
                finally:
                    request.app.state.api_metrics.observe_llm('baseline', ledger.summary())
            return {**result, 'llm_usage': ledger.summary()}
        except AnswerError as exc:
            message = str(exc)
            code = 503 if ('OPENAI_API_KEY' in message or 'Install requirements' in message) else 502
            return JSONResponse(status_code=code, content={"detail": message, "llm_usage": ledger.summary()})

    @api.post('/agent/ask')
    def agent_ask(request: Request, q: AgentQuery):
        """Explicit, paid (if configured) bounded agent run; no PDF mutations."""
        from .agent import run_research_agent
        try:
            with usage_scope(request.app.state.llm_prices) as ledger:
                try:
                    result = run_research_agent(
                        q.question, collection(request).snapshot_index(),
                        model=q.model, top_k=q.top_k, max_steps=q.max_steps,
                        distinct_pages=q.distinct_pages,
                    )
                finally:
                    request.app.state.api_metrics.observe_llm('agent', ledger.summary())
            result['llm_usage'] = ledger.summary()
        except AnswerError as exc:
            message = str(exc)
            code = 503 if ('OPENAI_API_KEY' in message or 'Install requirements' in message) else 502
            return JSONResponse(status_code=code, content={"detail": message, "llm_usage": ledger.summary()})
        request.app.state.api_metrics.observe_agent(result)
        return result

    return api


app = create_app()
