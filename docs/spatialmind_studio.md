# SpatialMind Studio

The agent packaged as an application: a local web app that wraps the existing
pipeline so a wet-lab scientist can take a Xenium bundle from blocked to a
validated report without a terminal.

Nothing here reimplements analysis. Ingestion, `pilot_gate()`, the tool
registry, `validate_tool_plan()` and report generation are the same code the CLI
runs. The app adds a session, a job queue, and a browser.

## Running it

Double-click `SpatialMind Studio.app`. It opens as an ordinary desktop window.

From a checkout:

```bash
.venv/bin/python -m spatialmind.app --data-root data
```

`--browser` opens the default browser instead of a window, `--headless` serves
without opening anything (what the tests drive), and `--port` / `--output-root`
override the rest. `--data-root` defaults to the saved config, then `./data`.

### It is a window, not a browser tab

The UI is a `WKWebView` in a native window, served by a local process bound to
`127.0.0.1` and nothing else. A browser tab was the cheaper option and the wrong
one: it buries a research tool behind whatever else is open, wraps it in a URL
bar, subjects it to extensions and cache, and leaves the server running with no
window once the tab is closed. The window owns the process — close it and the
server shuts down.

The window chrome is dark end to end. A stock macOS title bar paints in the
*system* appearance, so on a light-mode Mac the app showed a white band above a
near-black UI. The title bar is made transparent and the content view runs full
height, so the page's own background reaches the top of the window; the strip
stays draggable, because a transparent title bar is still a title bar. That
restyle has to run on the main thread — Cocoa raises on any window geometry
change off it, and pywebview's `shown` event fires on its own thread.

Three consequences worth knowing:

- The window remembers its size between launches (in the same config file as the
  data root). It opens at 1440x920 and will not go below 1080x700, which is the
  width at which Review Studio's map and side panel stop fighting each other.
- The page leaves room for the traffic lights only when it is in a window. It
  asks the server (`window_mode` on `/api/health`) rather than sniffing the user
  agent, which is guesswork that breaks whenever WebKit changes its string.
- A `WKWebView` silently ignores `target="_blank"`, so report links would do
  nothing at all inside the window. They are routed through a small bridge that
  hands the URL to the real browser, and the bridge refuses anything that is not
  a `127.0.0.1` or `localhost` address. Reports are standalone HTML meant to be
  kept, mailed and printed; the browser is where they belong.

### Names

Bundle folder names run to 54 characters of vendor boilerplate
(`Xenium_V1_FFPE_Human_Brain_Glioblastoma_With_Addon_outs`), and truncating one
mid-word hides the only part that identifies it. The API returns a `display_name`
with the boilerplate dropped — `FFPE Human Brain Glioblastoma` — and the UI shows
that, with the raw folder name underneath in small type and the full relative
path in the tooltip. Nothing is hidden; the readable part is just first.

## Create: the guided path

**+ Create** in the title bar is the way in. Five steps, and only the last one
starts work.

1. **Data** — drop files or a folder, or paste the path of a folder already on
   this Mac. Uploading copies bytes; **linking** does not, which matters because
   a Xenium bundle is routinely 10 GB and pushing it through a browser form to
   land it on the same disk costs minutes and twice the space. Whatever arrives
   is described back: what the app made of it, and for a half-copied bundle,
   which file is missing.
2. **Question** — five suggestions *this dataset can answer*, plus free text.
   The suggestions are grounded in the dataset: an unlabelled section is offered
   only descriptive questions, a gated-open one is offered questions naming its
   own cell types and regions. Free text is restated as the app will act on it,
   with anything it could not parse shown rather than silently dropped.
3. **Details** — only questions whose answer changes the plan. There are no
   questions here for the sake of looking thorough; each one sets a parameter or
   picks a lane.
4. **Tools** — the proposed plan with every step's lane, plus the rest of the
   implemented registry. Gate-blocked steps are visible and disabled, with the
   reason, rather than failing after the run starts.
5. **Run** — the exact parameters, then go.

Two rules the wizard never bends. It offers nothing it cannot run: every
suggestion resolves to a registered, implemented tool, and a suggestion carries
the tools it resolves to rather than being re-parsed from its own words. And it
routes around nothing: a blocked step is labelled blocked while it is still a
choice.

The text analysis is deterministic and local. An LLM would phrase the
restatement more fluently and could also quietly widen the question past what
the tools do, and this is the step that decides what gets run.

## The surfaces

Five home tabs, and three that belong to whichever dataset is selected.

| Surface | Job to be done | Backed by |
| --- | --- | --- |
| Datasets | What do I have, and how far is each from an answer? | folder scan + `infer_data_type` |
| Tools | I know the method I want | `ToolRegistry` |
| Visualization | Show me the figures | run artifacts |
| Tasks | What is running, what finished, what failed | `JobRunner` |
| Reports | Pin, rename, preview, edit, export | `ReportLibrary` |
| Readiness | Why can't this run, and what clears it? | `pilot_gate()` |
| Review Studio | Label cells and draw regions without writing a CSV | cell index + label/region writers |
| Ask | Answer my question, or tell me you can't | `planner.propose` |

## Reports, edits and exports

Every run leaves a report, result tables and at least one figure. A plan run
writes its own report rather than only JSON: a run that ends with a file nobody
can read is not a finished piece of work.

**Editing.** The user's version is written to `report_edited.md` *beside* the
run's own report and never over it, so the run record still replays byte for
byte. Every export of an edited report says "edited by hand after the run" —
a document carrying a run id has to be traceable back to what actually ran.

**Exports.** The report goes out as `.docx`, PDF, plain text or Markdown; the
result tables as one `.xlsx` workbook or a zip of CSVs, for all cells, all
genes, or everything. Every sheet and every CSV repeats the run id, the dataset
and the gate status, because a table is usually read apart from the report that
qualifies it.

A big export is a background task. Writing 163,920 cells x 35 columns to `.xlsx`
takes about 75 seconds, nearly all of it openpyxl serialising XML — too long to
hold a browser request open, and no reason to block an analysis run, since it is
one core writing a file. Exports are therefore non-exclusive jobs and appear
under Tasks beside the analyses.

**Deleting** a report removes the run directory and its record, so that run can
no longer be replayed. The UI confirms, and that is the only guard: a Reports
tab that cannot delete accumulates until it is useless.

## Choosing which tool runs

Three routes, one object. Ask, the recipes, and the Tool Bench all produce a
`ToolCallSpec` list that the real `validate_tool_plan()` checks before anything
executes.

- **Ask** routes a question to a plan and shows the reasoning. When the only
  tool that could answer is a registered scaffold, it refuses and names it
  rather than substituting a near-miss.
- **Recipes** are four saved plans: descriptive QC lane, validated Xenium pilot,
  spatial structure only, region contrast.
- **Tool Bench** lists all registered tools with capability, backend, runtime
  and preconditions. Scaffolds are visible and disabled.

Plan validation checks *structure*; whether the inputs exist is the gate's job.
That separation is why a gate-blocked plan still validates as sound instead of
duplicating the gate's blockers as fake plan errors.

### Lanes

Every step carries a lane, computed per call from the tool's preconditions:

- `descriptive` — runs now, describes data-derived groups, never names a cell type.
- `validated` — the gate is open; reviewed labels and regions are in play.
- `blocked` — needs reviewed labels or regions that do not exist yet.

Grouping a tool by cluster instead of cell type keeps it descriptive, so
`marker_detection` with `group_key=leiden` runs before any labels exist.

## Review Studio

The only screen where a human creates truth.

- **Label cells** — click a cell to select its whole 10x cluster, then apply a
  Cell Ontology term. The assignment covers every cell in that cluster, not just
  the drawn sample.
- **Draw regions** — drag a rectangle; every cell inside is written.

Both write into the bundle: `expert_cell_labels.csv` and `cell_regions.csv`,
where the loader looks for them. Writes are **merges**, never overwrites, and
are atomic — a table you hand-authored survives contact with the app.

### Why the app stays responsive on 40,887 cells

The review surface needs a cell id, a coordinate, and a group. It needs none of
the expression matrix. Reading `cells.parquet` plus the 10x cluster table builds
that index in about 1.6 seconds; loading the full 540-gene panel to answer
"which cells are in this rectangle" would cost minutes. Expression is loaded
only when a tool actually runs.

The browser is sent a sample of the cells (every Nth, keeping real density).
Selections are resolved **server-side over every cell**, so coverage and the
gate are computed on the whole section, not on what was drawn.

## Packaging for macOS

### The constraint, stated plainly

PyInstaller freezes the *installed wheels*, and the scientific stack ships thin
(single-architecture) wheels. On the development machine here, 400 of 414
bundled native extensions are `x86_64`-only. So:

- **A universal2 app cannot be produced from one machine** with this dependency
  set. It would need universal2 wheels for numpy, scipy, numba, llvmlite, h5py,
  pyarrow and the rest.
- **Each architecture must be built on that architecture.**

`scripts/build_macos_app.py` therefore builds for the host architecture, audits
every required native library first, and fails rather than producing a bundle
that would die on launch.

### Building

```bash
python scripts/build_macos_app.py --check       # audit only
python scripts/build_macos_app.py --clean --dmg # build + verify + package
python scripts/smoke_test_macos_app.py          # launch it and drive the API
```

The build produces `dist/SpatialMind Studio.app` and, with `--dmg`, a
`.dmg` named for its architecture.

### Both architectures

`.github/workflows/build-macos.yml` runs the same script on a matrix:
`macos-13` (Intel) and `macos-14` (Apple Silicon), each testing, auditing,
building and smoke-testing on real hardware of that architecture, then uploading
the `.dmg`. That is the supported way to produce both.

### The icon

`scripts/build_app_icon.py` renders `docs/icon.png` to Apple's macOS template
before the build: an 824x824 rounded square centred on a 1024x1024 transparent
canvas, with a soft shadow, then compiled to `.icns`.

That inset is not decoration. The source art is a full-bleed square with opaque
black corners, and macOS draws it edge to edge — next to Claude Code, Codex, or
any system app it read as noticeably larger and square-shouldered. Every icon in
the Dock is the same size because they all leave the same ~20% margin. The corner
is a superellipse rather than a circular arc, because macOS uses a continuously
curving corner and an arc is visibly pinched where it meets the straight edge.

The build fails if the icon does not end up inside the bundle; a missing icon is
a silent downgrade to the generic app tile.

### What the bundle contains

Only what the Studio imports — 18 third-party modules, the pywebview/pyobjc
window stack, and their dependencies.
`requirements.txt` installs the whole workstation stack (napari, vitessce,
chromadb, celery, torch); none of it is on the Studio's import path and
including it would add gigabytes and a much larger surface for a broken hidden
import.

### Gatekeeper

The app is ad-hoc signed, not notarised. On another Mac the first launch needs
right-click → Open, or:

```bash
xattr -dr com.apple.quarantine "/Applications/SpatialMind Studio.app"
```

Notarisation needs an Apple Developer ID; wire the certificate into the CI
workflow when one exists.

### macOS folder permissions

macOS gates `~/Documents`, `~/Desktop`, `~/Downloads` and removable volumes
behind a consent prompt, and a `.app` launched from Finder must obtain that
consent itself — it does not inherit the terminal's. Two consequences shaped the
build:

- **The app never scans a folder at startup.** The first read of a protected
  folder blocks until the prompt is answered. Doing that in the constructor
  blocked the app before it bound a port: no window, no error, nothing to click,
  and only a truncated log to say where it stopped. The scan now runs on the
  first `/api/datasets` request, so the UI is already open when the prompt
  appears. `/api/health` reports `scanned: false` until it happens.
- **The default data root is `~/SpatialMind/data`, not `~/Documents`.** The home
  folder itself is not gated. Point the app at a Documents folder from the
  Datasets screen if that is where the data lives, and answer the prompt.

`Info.plist` carries `NSDocumentsFolderUsageDescription` and its siblings so the
prompt explains itself rather than appearing bare.

### Where a packaged app keeps things

| What | Where |
| --- | --- |
| Settings | `~/Library/Application Support/SpatialMind/config.json` |
| Log | `~/Library/Logs/SpatialMind/studio.log` |
| Data root (default) | `~/SpatialMind/data`, changeable in the UI |
| Run outputs | `~/SpatialMind/outputs` |

The data root is set from the Datasets screen and remembered, because a `.app`
has no useful working directory.

## Dataset context

A researcher knows things the files do not carry: that a block sat in a drawer
for three years, that they care about immune infiltration, that they expect
tumour cells in the upper third. Refusing that is wasteful. Accepting it
carelessly is worse, because free text is the obvious way around a gate whose
purpose is to refuse unverified assertions — write "this section contains
abundant malignant cells" and, if it reaches any evidential path, the review
requirement has been bypassed with prose.

So context is **typed, not free-form**, and every field is classified by what it
may influence:

| Class | Fields | May affect | Never affects |
| --- | --- | --- | --- |
| `intent` | question, focus genes | which tools are proposed | anything evidential |
| `specimen` | tissue, condition, fixation, handling notes | an attributed report caveat | the gate, labels, claims |
| `expectation` | expected cell types, suspected artifacts | the order cells are reviewed in | anything at all, otherwise |

**The rule: context can change what the agent looks at first and what caveats it
prints. It can never change what the agent believes.** `gatekeeper`,
`pilot_gate` and `score_claim_reliability` do not read it, and tests assert that
directly — including one that writes the most tendentious context available
("glioblastoma with abundant malignant cells throughout", four expected cell
types, "fully characterised") and asserts the gate does not move a millimetre.

Why typed rather than a free-text box: a blob cannot be scoped. There is no way
to let "FFPE, degraded" affect a caveat while stopping "contains malignant
cells" from affecting a claim if both arrive in the same string. Separating them
at the input is the only point where the distinction is cheap.

Specimen facts become caveats that always name their author and say they are
unverified. A line reading "FFPE, degraded" beside the agent's own processing
steps is indistinguishable from something the pipeline measured; the same line
naming its submitter is not. Context with no author is recorded as coming from
"an unnamed submitter", which is the honest description of anonymous hearsay.

### Where it surfaces

**Report limitations.** Specimen facts are appended to `_limitations`, which
feeds the markdown, HTML and PDF reports alike, each line naming its author and
saying it is unverified. Expectations appear too, and say explicitly that they
ordered the review queue and nothing else — that no claim above depends on them.
Appended rather than merged: a handling note sitting among the agent's own
measured limitations would read as something the pipeline established.

**Review Studio ordering.** Expected cell types are listed first in the label
chips, outlined and tagged `expected`. That is the whole of the effect. The chip
assigns exactly what any other chip assigns, and only when a human clicks it —
a test asserts that offering a type for review leaves label coverage at zero and
the reviewed-class list empty.

Stored as `dataset_context.json` beside the bundle, like the label tables.
`GET`/`POST`/`DELETE /api/datasets/{id}/context`. The POST response returns the
recomputed gate, so a caller can see for themselves that what they wrote did not
move it.

## What labelling still needs

The Readiness screen ends with a live inventory of the inputs expert labels
require, computed from what is on disk rather than written down once and left to
rot: which reference atlases are present and which lineages they can name, the
ontology vocabulary, reviewer time, and region delineation. Each row says what it
unblocks, and each unmet one says what to do.

[`cell_label_resources.md`](cell_label_resources.md) is the same inventory in
prose, with the preflight evidence. The short version, as of 5 Sep 2026: the
seven Human Brain Cell Atlas superclusters now cover **every lineage confidently
detected** in the glioblastoma section, which closes a gap that previously left
~40% of cells unnameable. What is still missing is a **human** reference carrying
a malignant class — the only tumour reference present is mouse, and the preflight
refuses cross-species transfer — plus the reviewer time and the region drawing,
neither of which any reference can supply.

## HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Status, roots, registry capability counts |
| GET | `/api/datasets` | Discovered datasets (`?refresh=true` rescans) |
| POST | `/api/config` | Change and remember the data root |
| GET | `/api/datasets/{id}` | Detail, cluster sizes, gate, coverage |
| GET | `/api/datasets/{id}/cells` | Display sample for the map |
| POST | `/api/datasets/{id}/assign` | Write labels or regions |
| POST | `/api/datasets/{id}/clear` | Delete a label or region table |
| GET/POST/DELETE | `/api/datasets/{id}/context` | Typed user context; never evidential |
| GET | `/api/resources` | What expert labelling still needs, from what is on disk |
| GET | `/api/tools` | Full registry with lanes and recipes |
| POST | `/api/plan` | Order, validate and describe a plan |
| POST | `/api/ask` | Route a question to a plan, or refuse |
| POST | `/api/runs` | Start a `plan` or `pilot` job |
| GET | `/api/runs`, `/api/runs/{id}` | Job list and status |
| GET | `/api/runs/{id}/report` | The run's HTML report |
| POST | `/api/uploads` | Store an uploaded file or folder, then describe it |
| POST | `/api/uploads/link` | Register a folder already on this machine, without copying |
| GET | `/api/workflow/facts` | What the wizard reasons over: cells, gate, classes, panel |
| GET | `/api/workflow/questions` | Questions this dataset can answer |
| POST | `/api/workflow/analyze` | Free text, or a suggestion, into a structured prompt |
| POST | `/api/workflow/plan` | Answers into parameters, and the plan with its lanes |
| GET | `/api/reports` | Every run that produced a report |
| GET | `/api/reports/{id}` | Detail, report text and result tables |
| POST | `/api/reports/{id}/rename`, `/pin` | Library metadata |
| POST | `/api/reports/{id}/edit`, `/revert` | The user's version, beside the run's |
| DELETE | `/api/reports/{id}` | Remove the run directory and its record |
| GET | `/api/reports/{id}/export` | `docx`, `pdf`, `txt` or `md` |
| POST/GET | `/api/reports/{id}/results` | `xlsx` or `csv`, optionally one `kind` |
| GET | `/api/reports/{id}/table` | Preview one result table |
| GET | `/api/visualizations` | Every figure any run produced |

One *analysis* job runs at a time per process: two Scanpy pipelines on one
machine contend for the same cores and finish no sooner. Exports are jobs too
and are not exclusive — they are one core writing a file, and queueing them
behind an analysis would serve nobody.

## Evaluation

[`agent_evaluation.md`](agent_evaluation.md) is a full end-to-end run with
timings, gate behaviour in both directions, the honesty surface and the claim
reliability breakdown. `make eval-studio` reproduces it.

The headline: in three claims out of three the limiting component was `P_panel`
at 0.500-0.667, while statistics, annotation and robustness scored 1.000, 0.862
and 0.964-1.000. Reliability is weakest-link, so labelling buys *which claims are
possible*, not *how reliable they are*. The Readiness screen now shows that
ceiling before a reviewer commits a day to labelling.

## Tests

```bash
python -m unittest discover -s tests -p 'test_studio_app.py' -v
```

20 checks covering discovery, the gate opening and closing as a reviewer works,
merge-not-overwrite semantics, lane computation, dependency insertion, and the
scaffold refusal. They run against a synthetic bundle in a temp directory, so
they never leave label tables in a real dataset folder.
