# SpatialMind Research Knowledge Workspace

Date: 2026-10-17
Status: Source implementation and engineering evaluation; not specialist-validated.
Published macOS DMGs have not been rebuilt for this increment.

## Purpose and Priority Status

Implement a local, inspectable research wiki inspired by the source-to-wiki workflow
discussed with the user. Generated content is derived material, not new independent
evidence. The application may organize knowledge but cannot approve its own claims,
create expert specimen labels, or raise a biological reliability score.

| Priority | Delivered | Remaining boundary |
| --- | --- | --- |
| P0 | SQLite page revisions, source dependencies, event journal, review state, optional original archive, Markdown projections, revocation | Not a multi-user service or transactional filesystem/database store; interrupted projections fail closed |
| P1 compiler | Bounded offline digests and opt-in configured-provider drafts, per-claim citations, review form, diffs, publication, explicit rebuilds | Offline digests are excerpts, not LLM synthesis; no live hosted call was made |
| P1 BioBot | Multiple source excerpts, reviewed-wiki navigation to original evidence, filing answers as drafts, scoped historical run snapshots | Historical results do not attest to the current dataset revision or support arbitrary numerical Q&A |
| P2 | Integrity/staleness checks, backlink candidates, retrieval evaluation CLI, frozen benchmark/corpus hashes, specialist benchmark template | Semantic contradiction detection and specialist benchmark completion still need human judgments |
| P3 | Evaluation prerequisites and explicit adoption criteria documented below | OCR, image interpretation, semantic retrieval and local model execution are not implemented; no benchmark yet justifies a particular expansion |

This is a working first research-wiki increment, not completion of every speculative
feature in the broader roadmap. No expert review, protocol approval, model training,
cloud upload or GitHub publication was performed by this implementation.

## Architecture

```text
Local documents -> extraction -> source registry -> reviewed source passages
                                            |                  |
                                      optional raw copy        |
                                                               v
Verified historical run -> scoped pending source -> bounded compiler
                                                      |
                                          claims + exact citations
                                                      |
                                      draft revision + Markdown diff
                                                      |
                                   human per-claim review and notes
                                                      |
                                         published research wiki
                                                      |
                         BioBot navigation -> original evidence -> answer
                                                      |
                                     explicit save -> another draft
```

SQLite is authoritative for page revisions, review decisions, source dependencies
and the append-only operation event log. Markdown is a checked projection that can
be opened in Obsidian or another editor. It is not a second independently trusted
database. Editing an exported page does not preserve its previous review approval.

Relevant modules:

- `spatialmind/knowledge/store.py`: source registry, source revisions, FTS and chat.
- `spatialmind/knowledge/workspace.py`: page lifecycle, evidence integrity, projections.
- `spatialmind/knowledge/compiler.py`: bounded provider invocation and answer filing.
- `spatialmind/knowledge/evaluation.py`: deterministic retrieval scoring.
- `spatialmind/app/knowledge_chat.py`: authenticated Studio routes.
- `spatialmind/app/knowledge_runs.py`: restricted report/run bridge.
- `spatialmind/agent/conversation.py`: source-first BioBot behavior.

## Storage and Migration

```text
<output_root>/.studio/
  knowledge.sqlite
  knowledge/
    raw/                 # optional originals, hashed source IDs + safe extensions
    extracted/           # escaped Markdown projections of extracted source text
    assets/              # reserved; no image/OCR ingestion yet
    drafts/              # page-ID-rN.md
    wiki/                # latest published projection per page
    manifests/           # source manifests and shared-source backlink candidates
    index.md             # generated page index with states and short excerpts
```

Existing source IDs, enabled/review states and conversations survive additive
SQLite migration. Existing sources default to `general` scope. Large omics data
remain in the dataset library, not in the wiki. Existing uploaded originals cannot
be recovered retrospectively from extracted text: re-upload with **Retain local
originals** selected when an archival copy is needed. A raw copy is an explicit
local retention choice, not permission to send the document to a model.

Source revisions create a new source identity with a `supersedes` link and an
incremented version. The predecessor is disabled, dependent pages become stale,
and the new source starts pending. A new wiki revision can select replacement
sources through the revision-target control. Re-enabling a source never silently
reapproves stale pages.

The event journal records compilation start/completion/failure, publication and
revocation. Health checks expose unfinished operations. Restart does not silently
resume provider requests or publish partial output. Files are replaced atomically
one at a time; a crash between SQLite and filesystem changes can leave a stale
projection. Missing or modified projections are excluded until rebuilt and reviewed.
Simultaneous independent writers to the same workspace are not supported.

## Compilation and Review

1. Import permitted documents and inspect extraction warnings and source previews.
2. Record source review attribution. This is not authentication or proof of expertise.
3. Select 1-12 enabled sources, a title, page type and scope. Pick a new page or an
   existing revision target. Supported types include concepts, source summaries,
   methods, hypotheses and project findings.
4. Use **Offline evidence digest** or explicitly select the configured model.
   The compiler reads at most eight passages per source, 48,000 characters total.
   It is a bounded, non-exhaustive synthesis, not a whole-document systematic review.
5. Inspect the draft and diff. Every claim cites exact source passage IDs, hashes
   and versions. Numeric tokens absent from cited passages are rejected. These
   checks cannot prove semantic entailment or correct numerical interpretation.
6. Assess every claim's support, applicability and contradictions, with a review
   note and a real reviewer identity. Only the current unchanged draft can publish.
7. Publication makes a page available as a navigation aid. BioBot still cites the
   underlying source evidence, not the generated page as independent corroboration.

Offline digests use source excerpts. The optional model compiler uses the existing
configured provider transport. It has no tool execution or file-write authority;
only its validated JSON claims enter a draft. Sharing consent covers the selected
passages, title and scope for that request. Each private source must be authorized
explicitly. This is a separate opt-in from ordinary hosted BioBot answers, which
remain restricted to bundled public notes. No credentials are saved in the wiki.

No universal truth probability is reported. Evidence profiles show exact-citation
checking, distinct content hashes, review attribution, semantic-review state and
unestablished biological validation/independent corroboration. Multiple excerpts
or paraphrases do not become independent observations. Scientific reliability
metrics remain owned by the scientific pipeline.

## BioBot and Run Evidence

BioBot now diversifies up to three excerpts across matching sources. Published wiki
pages can lead it to their original passages, including concept titles not present
verbatim in the original text. Related pages are visible in the conversation. This
is lexical navigation and evidence retrieval, not semantic reasoning by an offline
language model.

Published pages have their own FTS5 index. BioBot checks only the candidate pages'
evidence/projections during retrieval, rather than scanning the whole wiki on every
question. The explicit integrity check and page-management view perform broader checks.

**Save last answer to wiki** creates a new derived draft. It retains original
citations, does not approve the answer, and does not add it to the raw source corpus.
Plans, uncited refusals and unsupported responses cannot be filed as evidence.

The run-import form requires an explicit dataset and report. The bridge:

- Requires a structured plan/pilot artifact and a bounded run-record JSON.
- Restricts recorded paths to the selected dataset and configured output root.
- Requires the selected artifact to match its recorded artifact digest.
- Runs existing replay verification and rejects mismatched/missing hashes.
- Records the input hash scope honestly; partial bundle hashing is not a full
  cryptographic digest of every input byte.
- Imports selected exact JSON fields and JSON-pointer locators, up to 40 fields.
  Oversize fields and nested metrics stay in the original artifact and are listed
  as omitted. Claim ledgers are not converted into prose or silently flattened.
- Starts the source pending review, scoped to `dataset:<ID>`.

After source review, select it in BioBot's Run evidence menu. This returns the
captured fields, not a question-specific statistical interpretation. Its record
and artifact hashes are rechecked; current input files are not rehashed on every
chat request. The answer explicitly says it is historical. Missing or changed
artifacts disable retrieval. Dataset removal/missing-path checks still apply.

## Maintenance and Security

Source disable/revision invalidates dependent page revisions and redacts stored
answers citing the source. Deletion additionally clears dependent claim/evidence
payloads, overwrites managed Markdown with an unavailable notice, and removes the
retained knowledge copy. Original source files are not deleted. This is logical
deletion, not secure erasure of SQLite free pages, backups, exports or OS caches.

An external Markdown edit is left on disk but invalidates application approval.
The generated index and API state are authoritative; an old Markdown header is
not an approval certificate. Health checks detect missing/modified projections and
unresolvable source dependencies. Shared-source backlinks are deterministic related-
page candidates, not discovered biological relationships. Human assessment remains
necessary for semantic contradictions, missing concepts and applicability.

All generated/source content is shown as text in the application. Markdown export
escapes active HTML and embed syntax. No remote images are loaded, websites crawled,
shell commands executed or arbitrary files opened by a model. Local session and
origin protections remain active. This is not multi-user authentication or protection
against malware already running with the user's filesystem permissions.

## Commands and Evaluation

```bash
.venv/bin/python -m spatialmind.knowledge --database outputs/studio/.studio/knowledge.sqlite health
.venv/bin/python -m spatialmind.knowledge --database outputs/studio/.studio/knowledge.sqlite search "neighborhood enrichment"
.venv/bin/python -m spatialmind.knowledge --database outputs/studio/.studio/knowledge.sqlite pages
.venv/bin/python -m spatialmind.knowledge --database outputs/knowledge_wiki_20261017/pilot/knowledge.sqlite evaluate eval/knowledge/development.json
.venv/bin/python scripts/run_knowledge_pilot.py --output outputs/knowledge_wiki_20261017/example --report-root outputs/studio --report-id job_3d54e9b613
```

The CLI can also create offline drafts with `compile --title TITLE --sources ID...`.
Source and page approval stays explicit; no CLI auto-review action is provided.

The 13-case development benchmark contains ten answerable and three unanswerable
questions. Initial source Recall@5 and MRR@5 were 1.0, but retrieval abstention was
2/3 because a common word matched an unrelated passage. After expanding stop-word
handling, the same development cases scored 1.0 for all three metrics. This is
development-tuned smoke evidence, not held-out accuracy. Baseline and updated
results retain benchmark/corpus hashes in `outputs/knowledge_wiki_20261017/`.

The specialist template in `eval/knowledge/specialist_review_template.json` is
deliberately incomplete and cannot be scored as a finished benchmark. A qualified
reviewer must specify answerability, exact expected sources, required claims,
forbidden inferences and conflicts. Freeze the rubric and an independent test split
before tuning prompts/retrieval. Citation support precision, biological accuracy,
and model-generated answer quality remain unmeasured.

## Pilot Result and Remaining Work

Engineering verification on 2026-10-17: the full suite ran 718 tests in 633.336
seconds, with 717 passing and one skipped. The separate focused knowledge suite
(54 tests), Studio suite (79 tests), and post-index-change workspace suite
(19 tests) passed. All six architecture import contracts, Python compilation,
JavaScript syntax and whitespace checks passed. Test logs are retained under
`outputs/knowledge_wiki_20261017/`. Sparse-efficiency and unclosed-test-file
warnings were non-fatal; these tests do not establish scientific accuracy.

The example produced three method/concept drafts without approving them. Importing
the existing healthy-brain report `job_3d54e9b613` was blocked because its older run
record contains empty artifact hash/path maps. The importer did not invent or
retroactively certify provenance. Regenerate that report through the current
Studio workflow, which records result artifact hashes, then import the new run.

P3 expansion should follow measured failures rather than adding dependencies by
default: OCR needs a reviewed scanned-document set; image interpretation needs
licensed figures and visual-grounding judgments; semantic retrieval needs a held-
out paraphrase benchmark; local generation needs model licensing, memory/latency
measurements and native Intel/ARM tests. Fine-tuning is not required for this wiki
and must not turn derived answers into self-labeled biological ground truth.

Still needed: real source/page reviewers, a specialist-reviewed QA benchmark,
provider configuration and explicit sharing choices for live model compilation,
visual acceptance in the desktop UI, and rebuilt/tested Intel and Apple Silicon
packages. These do not replace specimen-label, ROI, reference-curation or protocol
approval requirements.
