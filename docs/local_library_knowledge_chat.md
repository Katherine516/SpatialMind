# Local Dataset Library and Knowledge Chat

Date: 2026-10-15
Status: Source implementation; not yet included in the published 1.0.1 DMGs.

October 17 update: versioned wiki drafts, claim review, explicit publication,
source revision/invalidation, multi-source BioBot, answer filing, and historical
run imports are described in [Research Knowledge Workspace](research_knowledge_workspace.md).
The earlier first-increment behavior below is retained as historical context;
in particular, BioBot no longer returns only one source passage.

## What Is Implemented

The first usable increment of the [design plan](local_library_knowledge_chat_plan.md)
extends the current Studio rather than introducing another analysis engine.

### Dataset lifecycle

New packaged installations use the current user's empty `~/SpatialMind/data`
directory unless a data root was explicitly configured. No research datasets,
developer paths, API credentials, or local SQLite databases are bundled. The
developer checkout can still discover its existing `data/`; cloning source code
also includes tiny demo fixtures, unlike the packaged app. Changing this behavior
does not delete existing research files.

The Datasets view offers Add data, Link local folder, Rename, Remove, and Removed
datasets/Restore. A native folder chooser is exposed through the desktop bridge;
browser mode accepts a user-provided local path. The existing upload wizard also
accepts files/folder selections. Linked sources outside the data root now persist
in the library across restarts.

Removal is deliberately non-destructive: it hides a registration and preserves
source files, review tables, and reports. Rescanning does not resurrect removed
entries. A dataset with a running analysis/export task cannot be removed through
the normal dataset-associated task check. Source-file deletion is not offered.
Display-name changes do not rename source folders. Missing explicit registrations
stay visible as missing rather than silently disappearing.

Imports stream from spooled multipart files in 1 MiB chunks, with an 8 GiB total
payload limit and at most 512 files. The receive layer additionally caps request
size before parsing. Each import uses a unique hidden staging directory, records
per-file SHA256 hashes, then publishes its completed directory by rename. Failed
copies clean their staging directory. Crash-interrupted staging remains hidden
and is not automatically resumed or deleted; restart recovery is still a later
milestone. Native linking avoids copying large bundles altogether.

### Knowledge

The app ships 11 original concise notes about product usage, Xenium bundles,
Moran's I, neighborhood analysis, expert review, clustering, Cell Ontology,
AnnData, reliability, targeted panels, and privacy. They have stable IDs, source
links where appropriate, a version, and content hashes. They are labeled
`bundled`, not specialist-reviewed biological evidence or quotations from the
linked websites.

Users can upload Word (`.docx`), Excel (`.xlsx`), PowerPoint (`.pptx`), text-based
PDF, CSV, TSV, TXT and Markdown, or paste text with a title and optional HTTPS
source URL. Pasted text is limited to 200,000 characters and a 2 MiB request.
Imported sources start `pending` and
are excluded from answer retrieval until a person records a review identity.
That record is local attribution, not authenticated identity or proof of expertise.
Source review does not approve specimen labels, ROIs, or scientific protocols.

The file picker accepts multiple documents; the client submits them sequentially
to `POST /api/knowledge/uploads` (one multipart `file` field per request). Each
file receives its own success/error result, so a bad file does not discard good
imports. Limits: 25 MiB per file, 2 MiB extracted text, 200 PDF pages or slides,
50,000 spreadsheet/CSV fields or empty rows, and 50 MiB expanded Office archives
with at most 5,000 entries. Oversize documents are rejected, not truncated.
Extraction runs in a spawned process with a 30-second wall timeout and a POSIX
20-second CPU limit. Concurrent extraction is refused while one import is active.
This is not an OS security sandbox and does not impose a portable RAM quota.

Source previews show extraction warnings and provenance: original filename,
format, SHA256, input size, parser/version and extracted size. Page, paragraph,
slide, sheet/row or text-line locators are repeated in retrieval chunks. Original
files are not retained by the knowledge store or modified on the user's disk;
multipart input may temporarily spool to local storage. Only extracted text and
metadata are persisted. Existing databases migrate without losing sources.

Important extraction boundaries:

- Legacy `.doc`, `.xls`, `.ppt`, macro-bearing and password-protected files must
  be exported to supported, unlocked formats first.
- PDF figures and scanned pages are not interpreted. Image-only files are
  rejected with an OCR instruction; partially scanned files carry missing-page
  warnings. PDF text/table ordering still needs human inspection.
- Word body paragraphs and top-level tables are imported. Headers, footers,
  comments, tracked deletions, nested tables and embedded images are not.
- Excel includes hidden worksheets and literal formulas, without evaluation,
  external-link fetching, chart interpretation or cached formula results.
- PowerPoint includes text, tables, grouped text and speaker notes, including
  hidden slides; diagrams and other non-text content are not interpreted.
- CSV/TSV use explicit comma/tab delimiters. Text must be UTF-8 or BOM-marked
  UTF-16. Large expression matrices belong in Datasets, not Knowledge.

Parser references: [pypdf extraction limitations](https://pypdf.readthedocs.io/en/5.4.0/user/extract-text.html),
[openpyxl workbook loading](https://openpyxl.readthedocs.io/en/3.1/tutorial.html),
and [python-pptx text/notes](https://python-pptx.readthedocs.io/en/stable/api/slides.html).

SQLite FTS5 retrieves enabled bundled/reviewed passages. Users can inspect,
disable, or delete sources. Deletion removes indexed text and redacts stored
assistant answers citing it; tombstones stop bundled sources reappearing after
restart. This is logical deletion, not secure erasure of SQLite free pages,
backups, screenshots, exported conversations, or third-party logs.

### BioBot

BioBot (formerly Ask) has persistent conversations, history selection, an optional dataset
scope, deletion, JSON export, and source passage inspection. General questions
do not require a dataset or load a cell index. Limited follow-ups reuse the last
question as retrieval context. The default mode returns a source excerpt and
explicitly identifies itself as offline source search; it does not pretend a
language model is running locally.

Readiness questions about a selected dataset use the live gate. Analysis requests
go through the existing deterministic planner and require the separate Run plan
action. Dataset numerical-result questions currently ask the user to inspect the
relevant report instead of guessing values or selecting an unrelated run. Chat
bound to a removed/missing dataset refuses further contextual answers until its
source is restored or a new general conversation is started.

Optional hosted synthesis is restricted to bundled public-note evidence. Configure
the provider and model before starting Studio:

```bash
export SPATIALMIND_CHAT_PROVIDER=openai
export SPATIALMIND_CHAT_MODEL=<your-supported-model-id>
# Set OPENAI_API_KEY securely in the environment; never commit it.
.venv/bin/python -m spatialmind.app
```

`anthropic` with `ANTHROPIC_API_KEY` is the other existing provider option. No model
ID is hardcoded. The UI requires consent to send the current question and public
notes. Private reviewed documents are refused in hosted mode. Numerical additions
and nonexistent citation IDs are rejected, but structural checks do not prove
semantic correctness. No real provider call or paid request was made during this
implementation. Users should not include PHI or other sensitive material in a
question they choose to send externally.

## Storage and Compatibility

The concrete first-increment layout is deliberately workspace-scoped:

```text
<output_root>/.studio/library.sqlite       # registrations and removal tombstones
<output_root>/.studio/knowledge.sqlite     # sources, FTS, threads, messages
<data_root>/uploads/<name>_<id>/           # completed local copies
<data_root>/uploads/.import-<id>/          # hidden in-progress copy
```

This is a narrower layout than the proposed global support-directory design. It
keeps separate workspaces isolated and allows tests to use disposable output roots.
Do not change/delete `output_root` expecting library/history state to follow
automatically. Back up the `.studio` directory with other local app state.

Existing discovered IDs are retained when registered; explicit external imports
receive UUIDs. The path-to-registration mapping preserves names/removal across
rescan. General relocation, content-revision migration, and review-sidecar alias
mapping are not implemented yet. Existing scientific input snapshot/hash checks
remain authoritative for actual analysis runs.

`/api/ask` remains compatible with old planner clients. New conversational clients
use `/api/chat/sessions` and `/api/chat/sessions/{id}/messages`. The source registry
is under `/api/knowledge`; dataset library removal/restore uses dedicated endpoints.
The low-level app factory preserves unprotected in-process test compatibility;
all supported desktop/browser launchers enable local session protection.

## Security Boundary

The launcher binds loopback and uses an unpredictable local session token plus
strict Host/Origin checks. Opening the local root page establishes an HttpOnly,
SameSite session cookie. API state changes require an authorized local session;
cross-origin/cross-site requests are refused. `/healthz` exposes only a liveness
status. Exported HTML responses use a sandbox policy to separate report scripts
from the privileged application. This is single-user local protection, not
multi-user authentication or a defense against malware already running as the OS user.

Source text and chat answers render as text, not executable HTML. The UI no longer
loads fonts from a third-party service. No automatic web crawler, embeddings
service, background telemetry, dataset upload to a provider, or automatic training
was added. Credentials remain environment-only in this increment.

## Verification

The BioBot/document-upload increment added 13 tests. Combined knowledge/chat/
document tests passed 35/35; Studio regression passed 79/79 (114 total). All six
import contracts, JavaScript syntax and Python compilation passed. The complete
699-test suite was not rerun for this increment. A browser test in a disposable
library uploaded Word, Excel, PowerPoint, PDF and CSV together and verified pending
review plus the PDF's page locators/provenance. No test sources were added to the
real workspace. Screenshot: `outputs/biobot_documents_20261015/knowledge_upload.png`.
Native Intel/ARM package execution remains unverified for these changes.

Earlier local-library increment checks (historical):

- 22 focused tests cover empty first use, external-link persistence, reversible
  removal, original-byte preservation, rename, missing paths, bounded reads,
  upload traversal/collision/size rejection, hidden staging, source approval and
  revocation, history, context boundaries, consent, fabricated citations/numbers,
  and loopback session checks.
- The existing 79 Studio tests pass after updating upload-test cleanup to remove
  its newly persistent disposable registration explicitly.
- JavaScript syntax, Python compilation, and all six import contracts pass.
- A live local source server discovered the existing 17 local dataset entries and
  the 11 bundled knowledge notes without copying or deleting research inputs.
- Full regression ran 686 tests in 481.532 seconds: 685 passed and one skipped.
  Log: `outputs/local_library_knowledge_chat_20261015/full_tests.log`.
- Browser visual inspection was attempted, but the browser tool failed to open a
  usable surface. Native chooser interaction and native Intel/ARM package launch
  have not been verified for this increment. Published DMGs were not rebuilt.

These checks establish software behavior on fixtures, not biological annotation
accuracy, specialist review quality, or generative-answer accuracy.

## Remaining Work, In Order

1. Complete visual/native-window acceptance and rebuild/test both architecture
   packages before publishing a new release. Retain empty-install tests.
2. Add explicit revision-aware relocation, recoverable operation journals,
   resumable/cancellable imports, and a safe owned-copy trash workflow only if
   source-file deletion is actually needed. Current Remove remains non-destructive.
3. Add selected-run artifact adapters for exact result questions, including hash,
   revision and parameter compatibility checks; add streaming/cancellation only
   with a truthful partial-output state.
4. Curate a larger domain corpus and a human-reviewed question benchmark. Measure
   retrieval recall, citation support, abstention and contradictions; current
   lexical smoke tests are not the design's 100-question quality evaluation.
5. Validate hosted generation with approved nonsensitive questions and implement
   desktop secret-store/provider settings. Then consider optional OCR, hybrid
   retrieval, bilingual evaluation, and optional local generation if justified.

The human label/ROI, tissue evidence, reference-curation, protocol-approval, and
independent-donor requirements remain unchanged and must proceed separately.
