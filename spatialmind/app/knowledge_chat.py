"""Studio routes for local knowledge and read-only conversation."""

import os
from threading import Lock
from typing import Dict, List

from ..agent.conversation import answer_question, synthesize_answer
from ..knowledge.store import KnowledgeStore
from ..knowledge.documents import MAX_FILE_BYTES, extract_isolated
from ..llm import build_llm_provider
from ..knowledge.compiler import compile_page, file_answer
from .knowledge_runs import import_run


def install_routes(app, studio):
    from fastapi import File, Form, HTTPException, Query, UploadFile
    from pydantic import BaseModel, Field

    store = KnowledgeStore(studio.state_root / "knowledge.sqlite")
    studio.knowledge = store
    # Serialize answer persistence/source revocation so an in-flight answer cannot
    # resurrect a deleted source. These local requests are small and read-mostly.
    lock = Lock()
    import_lock = Lock()

    class SourceRequest(BaseModel):
        title: str = Field(min_length=1, max_length=200)
        body: str = Field(min_length=1, max_length=200000)
        url: str = Field(default="", max_length=2000)

    class SourceReview(BaseModel):
        enabled: bool = True
        approve: bool = False
        reviewer: str = Field(default="", max_length=200)

    class SessionRequest(BaseModel):
        dataset_id: str = ""

    class MessageRequest(BaseModel):
        question: str = Field(min_length=1, max_length=4000)
        hosted: bool = False
        consent_to_send_question_and_public_notes: bool = False
        run_source_id: str = ""

    class CompileRequest(BaseModel):
        title: str = Field(min_length=1, max_length=200)
        source_ids: List[str] = Field(min_length=1, max_length=12)
        kind: str = "concept"
        scope: str = "general"
        page_id: str = ""
        hosted: bool = False
        consent: bool = False
        allowed_private_ids: List[str] = Field(default_factory=list)

    class PublishRequest(BaseModel):
        revision: int = Field(ge=1)
        reviewer: str = Field(min_length=1, max_length=200)
        assessments: Dict[str, Dict[str, str]]

    class FileAnswerRequest(BaseModel):
        message_index: int = Field(ge=0)
        title: str = Field(min_length=1, max_length=200)

    class RunImportRequest(BaseModel):
        report_id: str
        dataset_id: str

    def provider_settings():
        name = os.environ.get("SPATIALMIND_CHAT_PROVIDER", "").lower()
        model = os.environ.get("SPATIALMIND_CHAT_MODEL", "")
        key_name = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(name, "")
        return {"provider": name, "model": model, "configured": bool(key_name and os.environ.get(key_name) and model)}

    @app.get("/api/knowledge/sources")
    def sources():
        return {"sources": store.list_sources(), "generation": provider_settings(), "mode": "local_fts5"}

    @app.post("/api/knowledge/sources")
    def add_source(request: SourceRequest):
        try:
            with lock:
                identity = store.add(request.title, request.body, request.url)
            return {"source_id": identity, "status": "pending"}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/knowledge/source")
    def source(source_id: str = Query(...)):
        try:
            return store.source(source_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown source.")

    @app.post("/api/knowledge/uploads")
    def upload_source(file: UploadFile = File(...), retain_original: bool = Form(False)):
        try:
            if not import_lock.acquire(blocking=False):
                raise HTTPException(status_code=409, detail="Another document is being imported. Try again shortly.")
            try:
                payload = file.file.read(MAX_FILE_BYTES + 1)
                if len(payload) > MAX_FILE_BYTES:
                    raise ValueError("Each document is limited to 25 MiB.")
                extracted = extract_isolated(file.filename or "", payload)
                metadata = extracted["metadata"]
                with lock:
                    identity = store.add(metadata["filename"][:200], extracted["body"], metadata=metadata)
                    if retain_original:
                        store.workspace.retain_original(identity, payload)
                return {"source_id": identity, "status": "pending", "metadata": store.source(identity)["metadata"]}
            finally:
                import_lock.release()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            file.file.close()

    @app.patch("/api/knowledge/source")
    def review_source(request: SourceReview, source_id: str = Query(...)):
        try:
            with lock:
                store.set_status(source_id, request.enabled, request.approve, request.reviewer)
            return store.source(source_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown source.")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.delete("/api/knowledge/source")
    def delete_source(source_id: str = Query(...)):
        try:
            with lock:
                title = store.delete(source_id)
            return {"deleted": title}
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown source.")

    @app.get("/api/knowledge/search")
    def search(q: str = Query(..., max_length=4000)):
        with lock:
            return {"passages": store.search(q), "pages": store.workspace.search(q)}

    @app.post("/api/knowledge/sources/{source_id}/revisions")
    def revise_source(source_id: str, request: SourceRequest):
        try:
            with lock:
                identity = store.revise(source_id, request.title, request.body, request.url)
            return {"source_id": identity, "status": "pending"}
        except KeyError:
            raise HTTPException(404, "Unknown source.")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/knowledge/wiki")
    def wiki():
        with lock:
            pages = store.workspace.pages()
            return {"pages": [{k: p[k] for k in ("id", "revision", "title", "kind", "scope", "status", "reviewer")} for p in pages],
                    "workspace": str(store.workspace.root)}

    @app.get("/api/knowledge/wiki/{page_id}")
    def wiki_page(page_id: str):
        try:
            with lock:
                store.workspace.health()
                page = store.workspace.get(page_id)
                return dict(page, diff=store.workspace.diff(page_id), related=store.workspace.related(page_id))
        except KeyError:
            raise HTTPException(404, "Unknown wiki page.")

    @app.post("/api/knowledge/compile")
    def compile_knowledge(request: CompileRequest):
        try:
            with lock:
                provider = None
                if request.hosted:
                    settings = provider_settings()
                    if not settings["configured"]:
                        raise ValueError("Configure the provider and model before requesting model compilation.")
                    provider = build_llm_provider(settings["provider"], model=settings["model"])
                return compile_page(store, request.title, request.source_ids, request.kind, request.scope,
                                    request.page_id or None, provider, request.consent, request.allowed_private_ids)
        except KeyError:
            raise HTTPException(404, "Unknown source or wiki page.")
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/knowledge/wiki/{page_id}/publish")
    def publish_page(page_id: str, request: PublishRequest):
        try:
            with lock:
                return store.workspace.publish(page_id, request.revision, request.reviewer, request.assessments)
        except KeyError:
            raise HTTPException(404, "Unknown wiki page.")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/knowledge/health")
    def knowledge_health():
        with lock:
            return store.workspace.health()

    @app.post("/api/knowledge/import-run")
    def import_run_evidence(request: RunImportRequest):
        try:
            with lock:
                return import_run(studio, store, request.report_id, request.dataset_id)
        except KeyError:
            raise HTTPException(404, "Unknown dataset.")
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/chat/sessions/{session_id}/file-answer")
    def save_answer(session_id: str, request: FileAnswerRequest):
        try:
            with lock:
                return file_answer(store, session_id, request.message_index, request.title)
        except KeyError:
            raise HTTPException(404, "Unknown session or source.")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/chat/sessions")
    def sessions():
        return {"sessions": store.sessions()}

    @app.post("/api/chat/sessions")
    def create_session(request: SessionRequest):
        if request.dataset_id:
            try:
                studio.entry(request.dataset_id)
            except KeyError:
                raise HTTPException(status_code=404, detail="Dataset is not in the active library.")
        return store.create_session(request.dataset_id)

    @app.get("/api/chat/sessions/{session_id}")
    def session(session_id: str):
        try:
            return store.session(session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown conversation.")

    @app.delete("/api/chat/sessions/{session_id}")
    def delete_session(session_id: str):
        with lock:
            store.delete_session(session_id)
        return {"deleted": True}

    @app.post("/api/chat/sessions/{session_id}/messages")
    def message(session_id: str, request: MessageRequest):
        with lock:
            current = session(session_id)
            dataset = None
            if current["dataset_id"]:
                try:
                    dataset = studio.entry(current["dataset_id"])
                except KeyError:
                    raise HTTPException(status_code=409, detail="This conversation's dataset was removed. Restore it or start a general conversation.")
                if dataset.missing:
                    raise HTTPException(status_code=409, detail="The source dataset is missing from disk.")
            try:
                if request.run_source_id:
                    source = store.source(request.run_source_id)
                    if not dataset or source["scope"] != "dataset:" + current["dataset_id"] or source["metadata"].get("kind") != "run_artifact":
                        raise ValueError("Run evidence must belong to this conversation's selected dataset.")
                    evidence = store.workspace.evidence([request.run_source_id], per_source=64)
                    store.workspace.check_evidence(evidence)
                    reply = {"mode": "run_evidence", "support_status": "historical_run_snapshot", "provider": "offline",
                             "answer": source["body"], "citations": evidence, "dataset_id": current["dataset_id"],
                             "limitations": ["Exact selected-run fields, not an LLM interpretation. Current dataset/review files were checked at import time only.",
                                             "Artifact integrity and source review do not establish biological validation."]}
                else:
                    reply = answer_question(store, request.question, current, dataset,
                                        lambda: studio.gate(current["dataset_id"]) if dataset and dataset.reviewable else {
                                            "status": "not_reviewable", "blocking_reasons": ["This workflow requires a Xenium bundle."]})
                if request.hosted:
                    if not request.consent_to_send_question_and_public_notes:
                        raise ValueError("Explicit consent is required to send your question and public notes.")
                    settings = provider_settings()
                    if not settings["configured"]:
                        raise ValueError("Hosted chat is not configured. Offline source search remains available.")
                    provider = build_llm_provider(settings["provider"], model=settings["model"])
                    reply = synthesize_answer(provider, request.question, reply)
                store.append(session_id, request.question, reply)
                return reply
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            except KeyError:
                raise HTTPException(status_code=404, detail="Unknown knowledge source.")
