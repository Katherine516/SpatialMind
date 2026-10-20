# SpatialMind Local Dataset Library, Knowledge Base, and Chat Plan

Date: 2026-10-15
Status: Proposed implementation plan; the features described as proposed are not implemented by this document.
Scope: Local, single-user SpatialMind Studio, including the Intel and Apple Silicon macOS packages and the local browser interface.

Implementation update (2026-10-15): the first source increment now provides a
persistent library, safe unregister/restore, bounded imports, local knowledge
retrieval, conversation history, and optional consent-gated synthesis. See the
[implementation record](local_library_knowledge_chat.md) for the narrower shipped
scope, actual storage layout, verification, and remaining milestones. This design
is not a claim that every release target below has already been met.

## 1. Executive Recommendation

Build three connected capabilities, in this order:

1. A persistent local dataset library with native selection, bounded-memory imports, and safe removal.
2. A curated, versioned knowledge base with local search and traceable sources.
3. A conversational Ask interface that distinguishes general knowledge, dataset facts, existing results, and requests for new analysis.

Keep the current FastAPI, pywebview, scientific tools, typed plans, review gates, and report pipeline. Do not replace the application framework or build a separate analysis engine for chat. Start with SQLite full-text retrieval; add semantic retrieval only after measuring a meaningful retrieval gap. No model fine-tuning is required to deliver the first useful version.

"Upload" in this desktop application should mean importing into local storage, not uploading to a cloud. Linking an existing folder should be the recommended option for large Xenium bundles. A cloud language model, when explicitly enabled, is a separate opt-in data flow.

The knowledge base helps the agent find and explain information. It cannot certify expert labels, approve protocols, establish malignant status, or turn descriptive results into validated biological findings.

## 2. Current Code and Specific Gaps

These observations come from source inspection on the date above, not from a new runtime or packaged-app evaluation.

| Area | Existing implementation | Gap to address |
|---|---|---|
| Desktop shell | `spatialmind/app/desktop.py` runs pywebview against a loopback server | Add a narrow native file/folder selection bridge and verify it in both architecture-specific builds |
| Upload | `app/server.py` exposes `POST /api/uploads`; `app/uploads.py` preserves folder paths | The handler reads every file completely into a payload list before writing; redesign for bounded memory and transactional publication |
| Folder selection | `POST /api/uploads/link` validates a local path | It does not persist an independent library registration; folders outside `data_root` remain absent unless the root changes |
| Discovery | `app/catalog.py` scans a root and derives IDs from paths | Need durable library IDs, source revisions, multiple locations, hidden-entry persistence, and relocation |
| Removal | There are report deletion and dataset-context clearing endpoints | No complete dataset-library removal workflow with ownership and dependency checks |
| Ask | `POST /api/ask` requires a dataset and calls `agent/planning.py:propose` | This is deterministic intent-to-plan routing, not knowledge retrieval or a conversational answering service |
| LLM boundary | `spatialmind/llm.py` provides structured planning adapters | No general answer-generation/streaming contract for Studio; the current `local` provider means rules, not a local language model |
| Memory | `memory/backends.py` stores JSON sessions, analysis records, and user priors | These are not a curated document corpus, citation index, or evidence approval system |
| Provenance | `storage/run_store.py`, `storage/replay.py`, and `ingestion/identity.py` preserve run evidence and identities | Extend these interfaces to dataset revisions and chat evidence without rewriting historical records |
| Jobs | `app/jobs.py` runs worker threads with in-memory history | Imports/indexing need persisted operation state and restart recovery; a UI cancellation flag alone cannot stop work |
| Packaging | Separate app requirements omit unused heavy services | Preserve a lightweight CPU baseline; do not make vector services or large model weights mandatory |

Existing uncommitted changes must be preserved. This plan does not authorize deleting datasets, rewriting review decisions, or migrating user storage immediately.

## 3. Product Experience

### 3.1 Datasets

The Datasets view should support:

- Add files, add folder, and drag-and-drop where supported by the actual platform.
- A choice between **Link existing data** and **Copy into SpatialMind**; show the destination and estimated disk cost before copying.
- A persistent list across restarts with display name, assay/type, location mode, import status, size when known, readiness, and last verification.
- Rename the display name without renaming the underlying source.
- Inspect missing bundle components, unsupported capabilities, and permission errors.
- Reveal in Finder, relocate a missing source, refresh metadata, and remove from library.
- Separate deliberate deletion of an app-owned copy from removing a library entry.

Use compact rows, progress indicators, familiar icons with tooltips, and a confirmation dialog describing exactly what will be affected. Keep imported, linked, missing, incomplete, and analysis-ready states visibly distinct. A recognized extension is not proof that a dataset is usable for every tool.

Native desktop selection should use the existing pywebview window. Browser mode should use normal file/folder controls and a validated local-path flow where supported; it must not pretend it can discover arbitrary absolute paths from browser file objects. See the [pywebview API](https://pywebview.flowrl.com/api/).

### 3.2 Knowledge

Add a Knowledge view with source search, title, scope, provenance, version, review status, and indexing status. Users can add permitted Markdown, text, HTML, and text-based PDF documents, inspect extracted content, and disable or remove sources. The first release should prioritize Markdown/text and curated HTML; PDF extraction follows with explicit extraction-quality checks. Scanned PDFs requiring OCR remain unsupported until tested.

Separate bundled product knowledge from private user documents. Adding a document makes it available for a selected search scope; it does not make it curated or expert-approved. Source promotion requires an explicit review action with a recorded reviewer and evidence.

### 3.3 Ask

Replace the single-question plan response with a conversation surface:

- Persistent threads, new conversation, history, rename, delete, and export.
- Dataset selection is optional for general questions and explicit for dataset-specific questions.
- Short answers by default, with expandable evidence, limitations, and follow-up detail.
- Source links that open the precise passage or local result artifact.
- A visible dataset/revision/run context, provider mode, and network-sharing indicator.
- Stop generation, retry, and clear provider errors without silently changing privacy mode.
- Proposed analysis appears as an inspectable plan with a separate approval/run action.

Example routing expectations:

| Question | Correct behavior |
|---|---|
| "What is Moran's I?" | Answer from methods sources without requiring a dataset or running analysis |
| "How many cells passed QC?" | Read the selected run's structured QC values and cite that run; ask which run if ambiguous |
| "Why is annotation blocked?" | Read the current readiness result and explain the actual missing requirements |
| "Are astrocytes next to tumor cells here?" | Use a compatible existing result, or propose gated analysis; do not answer from general literature alone |
| "What about oligodendrocytes?" | Resolve the follow-up within the explicit dataset/run scope; ask when ambiguous |
| "Run neighborhood enrichment" | Draft and validate a typed plan; execute only after user approval |
| "Remove this dataset" | Navigate to the removal confirmation; chat never receives a raw filesystem deletion tool |

## 4. Architecture and Boundaries

```text
Native window / local browser
  |-- Dataset library UI --> import/registration/removal service
  |                           |-- local SQLite registry
  |                           |-- linked sources or managed copies
  |                           `-- existing ingestion/readiness adapters
  |
  |-- Knowledge UI ---------> source curation and indexing service
  |                           `-- versioned documents + local FTS index
  |
  `-- Ask UI ---------------> conversation orchestrator
                              |-- general question: retrieve curated sources
                              |-- dataset question: read scoped live facts
                              |-- result question: read verified run artifacts
                              `-- action request: existing typed planner
                                         |
                                  explicit user approval
                                         |
                              current gates / tools / run store
                                         |
                              existing HTML/PDF reports

Answer synthesis receives bounded evidence, not raw matrices.
Policy checks, source resolution, and scientific gates remain server-side.
```

Keep the boundaries explicit:

- The dataset library owns locations and lifecycle, not annotation truth.
- The knowledge base owns source records and retrieval, not numerical computation.
- The conversation orchestrator selects evidence and proposes actions, not arbitrary code execution.
- The scientific runtime remains authoritative for tool availability, preconditions, numerical results, and biological reliability.
- Stored conversation text is context, not a new scientific evidence source.

## 5. Persistent Dataset Library

### 5.1 Identity and storage

Use a local SQLite registry under `config.support_dir()`, separate from the app bundle and raw data. Keep managed data under the configured data root and existing output locations intact. A proposed layout is:

```text
<support_dir>/
  library.sqlite
  knowledge.sqlite
  conversations.sqlite
  knowledge/sources/<source_id>/<version>/
  imports/<operation_id>/journal.json
<configured_data_root>/
  managed/<dataset_uuid>/revisions/<revision_id>/
  .staging/<operation_id>/
  .trash/<operation_id>/
<configured_output_root>/
  ...existing run directories...
```

Registry fields should include `dataset_uuid`, display name, source type, location mode, locator, ownership root, status, timestamps, current revision, metadata, and capability/readiness summary. Store donor identity separately from file identity; a file hash cannot prove donor independence.

Revision manifests should record relative file inventory, size, verified content hashes, hash scope, schema version, and extraction/loader versions. Reuse `ingestion/identity.py` and existing provenance helpers where their semantics apply. Do not silently relabel MD5 records as SHA256 or claim a partial inventory hash covers a whole bundle.

A stable UUID survives relocation. Content changes create a new revision and invalidate dependent caches, readiness, and proposed plans. Keep old run evidence tied to its historical revision. Quick size/mtime checks can flag possible changes but are not a substitute for required content verification.

### 5.2 Import transaction

1. Select the source and choose link or managed copy.
2. Preflight permissions, file count, free space, expected format, supported capabilities, and name collisions.
3. Create a persisted operation record and staging location; do not expose partial contents as a ready dataset.
4. Copy in bounded chunks or register a linked path. Hash incrementally during copying; schedule verification for large linked sources without freezing the UI.
5. Run bounded metadata inspection and readiness checks; do not load the full expression matrix merely to list a dataset.
6. Publish the managed revision using an atomic same-filesystem rename, then commit registry state through a recoverable journal.
7. On cancellation or failure, close file handles and clean only the operation-owned staging files. Reconcile interrupted publication at next launch.

SQLite commits and filesystem renames are not a single atomic transaction. The journal must handle a crash between them, including a published directory with a pending registry record. Use idempotency keys so retries do not create duplicate imports.

For HTTP intake, use bounded reads from `UploadFile` rather than accumulating whole-file byte strings. Enforce total request, individual file, file-count, duration, and spool-disk limits at the receive/parser boundary as well as during copying. Framework spooling alone does not prevent disk exhaustion. See [FastAPI file uploads](https://fastapi.tiangolo.com/tutorial/request-files/).

Treat multi-file bundles as one dataset where appropriate. Reject path traversal and colliding normalized filenames; preserve valid scientific filenames rather than silently changing their meaning. Define a strict symlink policy and reject symlink escapes. Defer general ZIP extraction initially; when added, enforce expanded-size/count/ratio limits and reject traversal and links. Apply these as layered controls, following the [OWASP upload guidance](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html).

### 5.3 Removal and recovery

| User action | Linked source | App-owned copy | Derived artifacts |
|---|---|---|---|
| Remove from library | Unregister/hide; never delete original files | Unregister/hide; preserve files | Preserve reports and provenance by default |
| Restore entry | Restore registration and revalidate location | Restore registration | Preserve historical IDs |
| Delete managed copy | Not offered | Explicit confirmation, then move owned revision to app trash | Show affected runs and caches; retain reports unless separately selected |
| Purge selected derived content | Explicit separate action | Explicit separate action | Preview exact reports, caches, chat context, and indexes affected |

Make deletion a two-step server operation: preview dependencies, then confirm a short-lived token bound to the dataset revision and selected scope. Revalidate ownership, resolved containment, symlinks, and active readers at execution time. Reject a stale preview. Never accept an arbitrary client path as deletion authority.

Block removal/deletion while a relevant analysis, export, import, or indexing operation holds a dataset lease; offer cancellation only for workers that actually support it. A linked source is never recursively deleted. Do not assume every file under `data_root` is app-owned, especially existing research data. Detect overlapping/nested registrations and shared files before deleting a managed revision.

Removal must create a persistent discovery exclusion so rescanning does not silently re-add the entry. Re-adding requires explicit user action. A retained report should say its source is unavailable rather than disappearing or claiming it remains replayable.

App trash is recoverable storage, not secure erasure. Purging cannot promise removal from backups, SSD history, exported files, or remote provider logs. Conversation/source deletion needs a separate policy for cached excerpts and database backups.

### 5.4 Migration

Perform a previewed, idempotent migration from current root discovery. Register existing datasets as linked/non-owned, retain legacy ID aliases, and preserve review sidecars and output associations. Do not move raw files or overwrite run manifests. Resolve legacy path-based sidecars through a compatibility mapping; propose migration only when the source revision is verified.

Back up registry/config metadata before schema migration. Keep readers for the old layouts until migration tests cover review assignments, moved folders, duplicate imports, and historical report lookup. Test rollback before releasing the new package.

## 6. Knowledge Base Design

### 6.1 Separate knowledge categories

| Category | Contents | Authority and limits |
|---|---|---|
| Product knowledge | Current capabilities, troubleshooting, formats, gate rules | Version-matched documentation plus live tool registry; old roadmaps cannot establish implemented capabilities |
| Methods knowledge | QC, clustering, spatial tests, multiple testing, targeted-panel caveats | Curated methods sources; does not establish a result in a user's dataset |
| Biological knowledge | Tissue-specific concepts, ontology terms, published marker evidence | Scope by species, tissue, disease, assay, and evidence quality; conflicting sources stay visible |
| Lab knowledge | SOPs, approved protocols, panel notes, private documents | User-scoped and review-status aware; upload alone is not approval |
| Dataset/run evidence | Structured metadata, gate results, completed tool outputs | Read through scoped adapters; do not indiscriminately embed `data/` or `outputs/` |

Begin with a small, reviewed corpus rather than indexing the entire repository. Exclude obsolete plans, historical performance claims presented as current, machine-generated drafts, credentials, and held-out benchmark truth. Treat user priors as preferences or hypotheses, not facts.

### 6.2 Source lifecycle and schema

Use separate fields for curation state (`pending`, `approved`, `rejected`, `superseded`, `revoked`) and index state (`queued`, `extracting`, `ready`, `failed`). Review approval and successful parsing must never be the same state.

Each source version needs: stable ID, title, URL/DOI/local locator, author/publisher, source kind, publication/retrieval dates, version, content hash, license/reuse status, visibility scope, language, species/tissue/assay tags, reviewer/date/evidence, extraction method/version, and replacement/retraction notes. Each chunk needs a version-bound ID, section/page locator, exact text span, content hash, and parent source ID.

Source ingestion should extract text without executing HTML, scripts, macros, or embedded instructions. Preview PDF extraction, preserve page references, and flag failed or empty extraction. Use a constrained parser process with file/time/memory limits for untrusted documents. Do not bypass paywalls or redistribute copyrighted full text without permission. A link can be recorded without indexing unavailable full text.

Do not automatically crawl arbitrary URLs in the first release. Add a curated-source fetcher later with explicit confirmation, allowed schemes/hosts, redirect checks, size/time limits, and blocking of loopback/private-network targets to prevent server-side request forgery.

### 6.3 Initial corpus

| Source | What to curate |
|---|---|
| Current `docs/agent_architecture.md`, `docs/gate_enforcement.md`, and runtime tool registry | Implemented capabilities and restrictions; publish at a specific app revision |
| Current review and reference-curation guides | Review provenance, donor separation, reference suitability, and approval requirements |
| [10x Xenium outputs](https://www.10xgenomics.com/support/software/xenium-onboard-analysis/latest/analysis/xoa-output-understanding-outputs) | Bundle semantics and coordinate/output context |
| [Scanpy](https://scanpy.readthedocs.io/en/stable/) | Methods used by the actual installed wrappers |
| [Squidpy](https://squidpy.readthedocs.io/en/stable/) | Spatial graph/statistics concepts and assumptions |
| [AnnData](https://anndata.readthedocs.io/en/stable/) | Matrix, layer, metadata, and coordinate semantics |
| [Cell Ontology](https://obophenotype.github.io/cell-ontology/) | Cell-type vocabulary, identifiers, and definitions |

These links were checked on 2026-10-15. They are source candidates, not an already imported corpus. Pin applicable documentation versions to installed dependencies instead of assuming a moving `stable` page matches the packaged app. Record redistribution terms before bundling excerpts. Add brain/glioblastoma primary papers only after domain curation.

### 6.4 Retrieval strategy

Use SQLite FTS5 with BM25 ranking, metadata filters, and curated exact synonyms as the first baseline. FTS5 supplies local full-text search without requiring a separate search server; verify that both packaged SQLite builds include it. See the [SQLite FTS5 documentation](https://sqlite.org/fts5.html).

Start with heading-aware chunks of roughly 300-600 tokens and limited overlap; these are tuning candidates, not validated optimal settings. Keep tables and procedural steps intact when splitting would change their meaning. Preserve gene symbols, ontology IDs, units, negation, and species qualifiers. Escape/normalize user queries through a structured query builder rather than forwarding raw FTS syntax.

Retrieval flow: identify question scope, apply access and source-status filters, retrieve candidates, remove duplicates, select bounded passages, and preserve source-version locators. Filter before ranking and again before returning results. Do not let revoked or unrelated private material leak through cached answers.

Only introduce hybrid lexical/semantic retrieval when a frozen evaluation shows missed paraphrases or synonyms. An optional local embedding model would need a licensed, pinned artifact, opt-in download, hardware/resource checks, and a versioned rebuildable index. Do not assume the existing `chromadb` dependency means a working knowledge base exists. No vector service or GPU is required for the baseline.

English is the initial curated corpus language. If Chinese questions are supported, evaluate English/Chinese pairs explicitly; provide a clear lexical-search limitation without a suitable translation or multilingual retrieval component. Translation must preserve gene symbols, numeric values, and ontology IDs, and use the same privacy policy as generation.

## 7. Grounded Conversation Service

### 7.1 Request lifecycle

1. Validate the session, question length, dataset/run selection, and permitted evidence scope.
2. Route to general explanation, dataset fact, result explanation, planning, or clarification. Use deterministic handling for authoritative status/numeric queries where practical.
3. Retrieve approved knowledge and/or read bounded structured evidence through explicit adapters.
4. Construct an evidence bundle with source IDs, passages, artifact hashes, revision/run IDs, tool parameters, label/region status, and limitations.
5. Generate a short structured answer or deterministic source-backed fallback.
6. Validate the schema, citation IDs, numeric references, evidence scope, and prohibited unsupported claims. Unknown citations fail validation rather than becoming links.
7. Return final content, source passages, limitations, and an optional typed proposed plan; persist the evidence trace.

Never automatically choose an old run merely because it is the newest file on disk. Check dataset revision, successful execution, analysis parameters, review state, and required tool outputs. Ask the user to choose when runs disagree or answer different questions.

Suggested answer contract:

```json
{
  "mode": "knowledge_answer",
  "answer": "A concise answer supported by the cited passages.",
  "claims": [
    {"text": "A supported statement.", "evidence_ids": ["kb:source:version:chunk"]}
  ],
  "citations": [
    {"evidence_id": "kb:source:version:chunk", "source_id": "source", "version": "version", "locator": "section"}
  ],
  "dataset_uuid": null,
  "dataset_revision": null,
  "run_id": null,
  "support_status": "supported",
  "limitations": [],
  "proposed_plan": null
}
```

Citation metadata and destinations must be resolved by the server, not trusted from model-generated URLs. Schema validation and citation existence do not prove entailment; use human-reviewed evaluations and conservative fallbacks for unsupported statements.

### 7.2 Provider modes and memory

- **Offline baseline:** deterministic facts plus retrieved passages and limited explanatory templates. Clearly label this as source search, not a full generative model.
- **Hosted generation, opt-in:** reuse the provider boundary, extending it with separate answer methods and structured contracts. Send only permitted passages and minimal structured context; use explicit user consent and workspace sharing controls.
- **Local generation, later:** optional separately downloaded model/runtime; benchmark RAM, latency, accuracy, and licensing on Intel and Apple Silicon. Do not bundle large weights or silently enable a cloud fallback.

Keep thread histories local with bounded context. Store summaries as conversation context, never as source truth; retain source IDs when compressing history. Changing dataset scope must explicitly reset/reconfirm dataset-specific context. Removing a dataset or revoking a source must prevent its old messages from being reused as factual evidence in future answers.

Store credentials in an OS-backed secret store when desktop credential entry is added, or use existing environment variables for development. Do not put credentials in browser storage, exported conversations, database traces, or plain-text app config.

For short answers, deliver a validated final response first. Streaming can later show a progress state or clearly provisional draft, but citations and final claims must pass validation before the answer is marked complete. Cancellation must propagate to the provider request where supported; partial text remains marked incomplete.

### 7.3 Scientific reliability

Keep chat answer support separate from the existing claim-level biological reliability score. Retrieval similarity, document count, or the model's confidence is not a probability that a biological statement is true.

For dataset-derived claims, display the stored claim score and its components only when the cited run actually produced them. Preserve sample size, grouping, effect size, adjusted p-values, robustness measurements, uncertainty, and applicable caveats. Never manufacture missing values or let literature citations increase a run's experimental reliability score.

General answers use qualitative support states such as supported, partially supported, conflicting, and insufficient evidence. Distinguish literature knowledge, observed dataset evidence, and suggested hypotheses. A targeted panel's unmeasured gene is not evidence of absent expression; proximity is not causality; a cell ontology label does not establish benignity or malignancy.

## 8. Privacy and Security

Local-only is the default: no cloud dataset transfer, automatic document upload, or background telemetry. Before any hosted request, apply field-level allowlists and show the permitted sharing scope. Aggregate summaries can still be sensitive; do not equate aggregation with de-identification. Reject obvious secrets and identifiers, but do not describe automated detection as a PHI guarantee.

Protect the loopback service with an unpredictable session capability, strict Host/Origin validation, CSRF protection for state changes, and a restricted CORS policy. Bind to loopback only; localhost is not itself authorization. Apply checks to read/export endpoints as well as mutations. Keep secrets out of URLs and logs. A browser launch should exchange a short-lived bootstrap capability for a protected session without exposing long-lived credentials.

Restrict the native bridge to deliberate user-selected paths and narrow commands. Do not expose arbitrary Python execution, shell commands, filesystem traversal, or general file reads to JavaScript. Prevent navigation of the privileged webview to untrusted pages; open external sources through a safe external-browser action.

Treat retrieved documents, filenames, local notes, and model output as untrusted content. They must never override system policy or tool permissions. Sanitize rendered Markdown/HTML, block active content and dangerous link schemes, and do not automatically load remote images that could leak private context. Follow the [OWASP prompt-injection guidance](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html), but do not rely on prompt wording alone: enforce access and execution boundaries in code.

Exclude sealed test truth, reviewer-only files, unrelated datasets, credentials, and arbitrary paths from retrieval. Answer traces should store references and minimal permitted excerpts with explicit retention settings. Evidence reproducibility does not justify retaining content after a user's explicit purge request; mark purged historical citations unavailable.

## 9. Proposed Code Changes

Names below are proposed modules, not files already implemented. Keep additions focused and do not rewrite unrelated layers.

| Location | Responsibility |
|---|---|
| `contracts/library.py`, `contracts/knowledge.py`, `contracts/chat.py` | Versioned request/response and evidence contracts |
| `storage/library_store.py` | Registry, revisions, aliases, operation journals, schema migrations |
| `storage/conversation_store.py` | Local threads, messages, evidence references, retention |
| `app/dataset_library.py` | Import/removal orchestration, leases, dependency previews, migration adapters |
| Existing `app/uploads.py`, `app/catalog.py` | Bounded transfer, discovery integration, explicit persistent registration |
| Existing `app/desktop.py` | Native chooser bridge and permission error handling |
| `knowledge/sources.py`, `knowledge/index.py`, `knowledge/retrieval.py` | Source lifecycle, extraction interfaces, FTS indexing, scoped retrieval |
| `agent/conversation.py`, `agent/answer_validation.py` | Routing, evidence assembly, provider calls, answer validation |
| Existing `llm.py` | Separate chat-generation interface without weakening planning validation |
| Existing `app/server.py` and focused router modules | Authenticated routes delegating to services; avoid adding another large block of business logic |
| Existing `app/static/index.html` plus focused local JS modules | Library, knowledge, and chat views using current UI conventions |
| Existing tests and new focused suites | Lifecycle, security, citation, routing, migration, and packaged-app regressions |

Update `.importlinter`: contracts remain foundational; knowledge/storage must not import the app or agent; the agent consumes knowledge; the app remains the top-level adapter. Existing analysis tools should not depend on chat.

## 10. Proposed API Surface

| Endpoint family | Behavior |
|---|---|
| `POST /api/dataset-imports` | Start a managed-copy or linked-source operation; return operation ID |
| `GET /api/dataset-imports/{id}` | Progress, byte counters, warnings, final dataset ID |
| `POST /api/dataset-imports/{id}/cancel` | Cooperative cancellation with persisted outcome |
| `GET /api/datasets` | Persistent registry listing; refresh discovery is explicit |
| `PATCH /api/datasets/{id}` | Rename or verified relocation; never arbitrary ownership changes |
| `POST /api/datasets/{id}/removal-preview` | Scope, affected objects, safety checks, confirmation token |
| `POST /api/datasets/{id}/remove` | Execute the exact confirmed scope after revalidation |
| `POST /api/datasets/{id}/restore` | Restore a library entry or recoverable managed copy |
| `GET/POST /api/knowledge/sources` | List/register permitted source material |
| `POST /api/knowledge/sources/{id}/review` | Explicit source curation with provenance |
| `POST /api/knowledge/search` | Scoped passages with versioned citations |
| `GET/POST /api/chat/sessions` | List/create conversations with optional dataset scope |
| `POST /api/chat/sessions/{id}/messages` | Submit question and return answer job/response |
| `DELETE /api/chat/sessions/{id}` | Delete history according to the stated retention policy |
| Existing plan and run endpoints | Validate/approve/execute analysis independently of answer generation |

Add source disable/removal and conversation export endpoints with the same preview/privacy principles. Preserve `/api/ask` as a compatibility adapter during migration; do not silently break its existing planner response contract. Final route naming can follow the repository conventions when implemented.

## 11. Implementation Priorities

| Order | Priority | Deliverable | Exit condition |
|---|---|---|---|
| 1 | P0 | Library contracts, persistent registry, legacy migration, loopback access controls | Existing data/sidecars/runs remain usable; external paths persist across restart; unauthorized access tests pass |
| 2 | P0 | Native import/link, bounded copying, operation recovery | Large-data import remains responsive; interrupted transfers never become ready datasets |
| 3 | P0 | Safe remove/restore and managed-copy deletion | Original linked data cannot be deleted; stale confirmations and active-use races are rejected |
| 4 | P1 | Curated source registry and local lexical retrieval | Approved seed corpus is searchable offline with exact source passages and versions |
| 5 | P1 | Conversational Ask with scoped facts and cited answers | General questions work without a dataset; follow-ups persist; missing evidence produces abstention |
| 6 | P1 | Opt-in generative provider and typed plan handoff | Privacy policy enforced; plans require explicit approval; existing gates remain authoritative |
| 7 | P1 | Integrated evaluation, documentation, Intel/ARM release smoke tests | Release criteria below pass on source and actual packaged binaries |
| 8 | P2 | Optional semantic retrieval, PDF/OCR expansion, local model | Demonstrated improvement over the baseline without unacceptable hardware/privacy costs |

Steps 1-3 are the first independently useful release. Steps 4-7 deliver the knowledge-grounded chatbot. Maintain a parallel biological-review track: none of these product features resolves the missing human labels, anatomical evidence, reference approvals, or independent validation data.

## 12. Evaluation and Acceptance Criteria

All numbers below are proposed engineering release targets, not observed results or biological validation thresholds. Freeze the evaluation set and scoring rubric before tuning retrieval/prompts; report denominators, failures, and uncertainty. Use human review for biological answer quality, not only an LLM judge.

| Area | Proposed evaluation and target |
|---|---|
| Data preservation | 100% of linked-source tests retain original bytes after removal, cancellation, restart, and restore |
| Boundary security | Zero successful traversal, unauthorized loopback access, cross-dataset retrieval, or unapproved execution in the adversarial suite |
| Migration | All fixture datasets retain review/run associations; migration retry is idempotent; rollback preserves the old registry |
| Import memory | Bounded copy buffers; proposed import-worker peak additional RSS below 256 MiB on a 10 GiB fixture, excluding later scientific analysis; measure multipart spool usage separately |
| Crash recovery | Crash injection at each journal boundary leaves either a recoverable pending operation or a complete verified revision |
| Large local data | Exercise existing Xenium folders by linking, with no writes to source files; use disposable fixtures for destructive tests |
| Retrieval | At least 100 independently reviewed questions with relevance judgments; proposed Recall@5 >= 0.90 for answerable questions; also report MRR and scope-specific failures |
| Citations | 100% of returned citation IDs resolve to the permitted source version; proposed human-rated citation support precision >= 0.95 |
| Unsupported questions | Proposed abstention/clarification rate >= 0.95 on intentionally unanswerable questions; separately measure false abstentions |
| Numerical answers | 100% exact agreement with cited structured artifacts in deterministic numeric fixtures, including units and denominators |
| Scientific boundaries | Zero expert-review bypasses, fabricated measurements, or literature-only claims presented as findings from the selected sample in the release suite |
| Latency | Proposed p95 local retrieval < 1 second for a fixed 10,000-chunk corpus; report cold/warm timings, hardware, memory, and corpus size |
| Conversation | Context survives restart; switching datasets, source revocation, retry, cancellation, and deletion do not leak stale evidence |
| Architecture packaging | Native Intel and native Apple Silicon smoke runs verify chooser, imports, FTS, offline answers, citations, permissions, and launch without network |

Build evaluation categories for product usage, methods, brain biology, readiness, run interpretation, unsupported clinical requests, conflicting/revoked sources, prompt injection, and follow-up ambiguity. Keep biomedical answer review separate from the engineering test result. Generic knowledge questions should not need a 40,000-cell index or load Scanpy just to answer.

## 13. Dependencies and Deployment

Reuse FastAPI, Pydantic, pywebview, existing scientific libraries, and Python's SQLite integration. Check FTS5 at startup and in both packaged builds; provide a clear failure diagnostic instead of silently dropping retrieval. Use local DB transactions, bounded writer concurrency, backups, and explicit schema versions.

Add document parsers or OS secret-store dependencies only when their feature is implemented, pinned/tested against supported Python/macOS versions, and included in packaging tests. A developer environment passing imports does not establish frozen-app compatibility.

Keep all user state outside the signed `.app`. Ship only a small, redistributable seed corpus with a manifest/version/license record; copy/update it without overwriting private sources. Package updates should use a new index build and atomic activation, retaining the prior version for rollback. User documents and model weights must not be committed to GitHub or bundled in DMGs by default.

No managed cloud vector database, Redis, Celery deployment, or dedicated GPU is needed for the initial single-user scope. Multi-user remote hosting would require a separate design for authentication, authorization, tenancy, encryption, durable workers, and institutional data governance.

## 14. Decisions and Inputs Needed

Recommended defaults allow implementation to begin without blocking on all preferences:

| Decision/input | Recommended default |
|---|---|
| Data location | Link large existing bundles; offer managed copy explicitly |
| Meaning of remove | Hide/unregister only; managed deletion is a separate confirmation |
| Existing data migration | Register as non-owned; preserve raw locations and sidecars |
| Knowledge scope | Current product/method docs first, then specialist-curated brain knowledge |
| Private documents | Local-only, unreviewed until explicitly curated |
| Language | English corpus initially; bilingual behavior requires explicit evaluation |
| Generation | Offline source-backed baseline; provider/model selection and credentials needed for generative chat |
| External sharing | Disabled until explicit provider/workspace consent |
| Chat retention | Persist locally with delete/export controls; agree on backup and purge policy |
| Review ownership | Maintainer for software docs; qualified scientist for biological knowledge; user-designated approver for lab protocols |
| Release validation | Access to both Intel and Apple Silicon machines/runners for actual packaged-app tests |

The remaining human inputs are a curated source list with reuse permissions, reviewers for biological content and evaluation questions, a decision on hosted versus fully local generation, and approval of retention/sharing defaults. These are independent of the missing specimen-level labels and ROIs.

## 15. Definition of Done

A user can install SpatialMind, add a local Xenium bundle without a terminal, restart the app and retain its registration, remove it without losing the original data, and restore or relocate it safely. They can ask a short general question without selecting a dataset and receive a concise source-backed answer. They can ask about a selected run and receive exact, traceable results with their limitations. A new analysis request produces a typed, reviewable plan, and nothing executes or gains biological validation merely because a chatbot suggested it.

The first implementation task should therefore be the persistent dataset registry and migration/access-control foundation, followed immediately by safe import/link and removal. This establishes the stable identities and evidence scope that the knowledge base and chatbot depend on.
