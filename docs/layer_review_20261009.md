# Layer-by-layer review — 9 Oct 2026

An independent check of the work since 28 Sep: Codex's layer evaluation
(`layer_evaluation_20261003.md`), its correctness upgrade, the reference-readiness
foundation, and the dual-architecture macOS release. Every claim below was
re-measured rather than read out of the documents it appears in.

## How the work is laid out

The working tree on `spatialmind-studio` carries 60 uncommitted or untracked
files. That looks like orphaned work and is not: compared by content hash, **59
of the 60 are byte-identical** to the tip of `codex/macos-dual-architecture`
(`d9b6d17`), which is committed and pushed. The one difference is `README.md`,
which adds a download section for the published release.

So this tree is the codex branch plus one README addition. **It should not be
committed again on `spatialmind-studio`** — that would duplicate a branch's worth
of history. The right move is to merge the codex branch and add the README change
on top.

## Verification

| Gate | Local (this tree) | CI (codex branch) |
| --- | --- | --- |
| Unit and integration | **648 / 648** | pass, py3.9 and py3.11 |
| Legacy eval | 16 / 16 | pass |
| MVP eval | 13 / 13 | pass |
| Import contracts | 6 / 6 | pass |
| Doc counts | **fail** | **fail, on all four commits** |
| Compile check | — | skipped (after the failure) |
| macOS build, both arch | — | pass, incl. native window |

The code is green. **The Checks workflow has been red on every commit of the
codex branch** — not for a test failure but because three documents disagree
about one number: the architecture doc says 637 tests, the release doc says 645,
and 648 are discovered. `check_doc_numbers.py --write` fixes it in one command.

The release was published while that workflow was red. The cause is trivial; the
practice is not. A CI that is red for a known harmless reason stops being read,
and the next real failure arrives looking exactly the same.

---

## The eight findings: all real, all fixed

I reproduced each independently, with probes written against APIs present in
`HEAD` and run unchanged against both the `HEAD` export and the working tree.

| | Finding | HEAD (`2d0a00a`) | Working tree |
| --- | --- | --- | --- |
| F2 | index coordinates pass the spatial precondition | **passes** | rejected |
| F3 | generic H5AD truncates rows to top-200 features | **200 of 301 kept** | 301 of 301 |
| F4 | protein intensities normalised like RNA | **100/200 → 8.112/8.805** | 100/200 preserved |
| F6 | tiny panels readmit technical features | **`NegControlProbe_1`, `TOTAL_COUNTS` leak** | excluded |
| F8 | fusion invents metrics for disjoint inputs | **shared=40, quality=0.5** | null / null |
| F1 | spatial FDR computed on a Moran-selected subset | screen present (3 refs) | removed (0 refs) |
| F5 | export keeps only the top-N tested genes | no `all_tested_genes` | retained |
| F7 | a missing artifact still reads `verified` | no `partial` state | `partial` |

F2, F3, F4, F6 and F8 were reproduced behaviourally on `HEAD` and confirmed fixed.
F1, F5 and F7 were confirmed in the diff. F4 reproduced Codex's exact numbers.
F8 gave quality 0.5 where Codex reported 1.0 — a different modality pair, the
same defect: numbers produced for inputs that share no cells.

**Two of these were in code I had already reviewed.** F3 is in the loader I
optimised on 20 Sep; I checked the `max_features_per_record` default only on the
Xenium path, which overrides it to 0, and called it consistent without checking
the generic H5AD entry point. F1 I recorded in my evaluation as *"disclosed in a
caveat"* and moved on. Codex is right that a caveat is not selective inference.

---

## Per-layer evaluation

### Contracts and schemas — strengthened

Coordinates now carry a kind and units; measurement semantics and the declared
measured-feature universe are recorded; unknown modalities fail contract
construction instead of defaulting to Xenium RNA. A zero is no longer evidence
that an unmeasured feature was measured. This is the layer F2, F4 and F6 all
trace back to, and it is now the right shape.

### Ingestion — the most improved layer

F3 was a quiet distortion: per-row top-200 truncation changed library sizes
before normalisation, so a 301-gene row's source sum fell from 45,451 to 40,300
and every normalised value moved. Positive per-cell caps are now rejected
outright. H5AD loads require a declared `expression_semantics` — my probe was
refused until I supplied one, which is the guard working. `identity.py` ties
provenance to bytes rather than paths, so a moved file keeps its identity.

### Tools — correct now, and slower, and that should be said

**F1 is fixed properly.** The family is chosen by detection count, which does not
change when cell positions are permuted, so it is independent of the Moran
statistic under the spatial null. That is valid independent filtering in the
sense of Bourgon et al., and the right repair.

Its consequences were not measured in the upgrade document. On the healthy brain
section, 24,362 cells, 250 permutations, warm:

| | genes tested | significant | runtime |
| --- | --- | --- | --- |
| HEAD | 100 | 100 | 67.2 s |
| working tree | 296 | **289** | **221.0 s** |

**Runtime tripled.** This is the most expensive tool in the descriptive lane, and
the first-analysis time in the packaged app will rise with it. The production
default is still 250 permutations — the 100 in the upgrade document's reruns was
exploratory and stated as such, so nothing was quietly lowered. The suite took
677 s here against 302 s in the release document.

**289 of 296 genes are significant — 97.6%.** On a structured tissue, nearly every
gene is spatially patterned, because cell-type composition is. The corrected test
is statistically sound and close to uninformative as a discovery signal here. The
old "100 of 100" looked like a clean result; it was the screened subset, and in
hindsight it was itself a symptom of F1.

The null evaluation is reported honestly: 2 of 50 all-null trials rejected
anything, rate 0.04, Wilson 95% interval 0.011–0.135. The upper bound is nearly
three times the target, and the document says so rather than claiming control.

### The gate — unchanged, still holding

All five local bundles remain correctly blocked. The Studio review writer now
marks a decision `reviewed` only when both a `reviewer_id` and an `evidence_ref`
are supplied. I checked how that composes with the `"unidentified (SpatialMind
Studio)"` default I added on 21 Sep: the status test reads the raw input, not the
defaulted value, so an unnamed reviewer is stored as unidentified and can never
reach `reviewed`. The two changes compose correctly.

### Review and reference curation — principled, and empty

`reference_curation.py` prepares decision templates and never fills them: every
decision starts `pending` with a blank reviewer, `use_for_training: False`, blank
target labels, and it refuses to write into an existing directory. I searched the
package for any code path that sets an approval field to a truthy value; the only
hit is the Studio writer above, which requires a human-supplied reviewer and
evidence reference. The docstring's claim — *"software never supplies human
approval"* — holds.

Nine local H5AD references were inspected without loading X. None is approved.
`training_ready` is false. Brain review packets have **zero accepted labels and
zero accepted regions**, unchanged since 27 Sep.

### Packaging and delivery — the longest-standing gap is closed

`scripts/smoke_test_macos_window.py` removes the headless switches so the app
takes the windowed path, and the app writes its own report once the WKWebView DOM
bridge is live. Its stated scope is honest: it does not test the interactive
folder-consent prompt, which cannot be automated.

It has genuinely run. CI run `37874197461` at `9237f40` shows *"Test the real
native window — success"* on both Intel and Apple Silicon. That is the windowed
boot path I flagged as untested in four consecutive reports. It is now tested.

The isolated build environment brought the DMGs to **455–459 MB**, down from
about 558 MB locally. The release `studio-v1.0.1-native` exists as a published
prerelease with both DMGs, ZIPs, checksums and a verification bundle, so the
README's new links resolve.

The minimum macOS is now **15.0**, up from 11.0, deliberately: *"older systems are
not certified by these runs."* That is the honest choice and it excludes every Mac
on 11 through 14.

(A correction to my 28 Sep report: the run in which I said arm64 succeeded and
Intel was queued was ultimately cancelled. Intel never ran in it. The codex
branch's later runs supersede it.)

---

## Next steps, in order

1. **Turn CI green and keep it green.** Run `check_doc_numbers.py --write`, then
   adopt a rule that a release is not published on a red Checks run. The fix is
   one command; the rule is the part that matters.

2. **Merge `codex/macos-dual-architecture`, then add the README change.** Do not
   commit the 59 identical files a second time on `spatialmind-studio`.

3. **Decide how `spatial_variable_genes` should present itself.** At 97.6%
   significance the binary call carries almost no information on brain tissue.
   Lead with effect size and rank, and consider a composition-adjusted variant —
   genes spatially patterned *beyond* what the cell-type layout explains is the
   question a biologist actually has. This is a scientific design decision, not
   a bug fix.

4. **Price the runtime.** Record the 3× cost in the release notes and the
   first-analysis expectations. If it needs to come down, permutation count is a
   statistical choice to make deliberately, not a performance knob.

5. **Then Codex's roadmap, which I agree with.** P1 data foundation and human
   review in parallel, a prespecified development benchmark, a locked independent
   test — before any second platform. Validate before expanding.

The binding constraint has not moved since the first review. There are still no
reviewed brain labels, no specialists engaged, no matched histology and no
independent donor. The software has outrun the biology for some time, and further
software will not close that gap.

## Follow-up, same day: steps 1 and 2

- **Merged.** `spatialmind-studio` was fast-forwarded to
  `codex/macos-dual-architecture` (`d9b6d17`), so the 59 identical files arrive
  once, as Codex committed them. Before the merge the working tree was stashed
  and every one of its 61 files was afterwards checked byte-for-byte against the
  merged tree; none differed. The README download section was then added on top.
- **Doc counts.** The inventory line now reads 649 discovered tests (648 plus the
  guard test below). The release document's "645/645" is left as it is: it
  records what one past run executed, not what the suite contains.
- **No release on red.** The publish job verified that its own build run
  succeeded and asked nothing about Checks. It now requires a successful Checks
  run on the exact source commit before anything is downloaded or uploaded, and
  `tests/test_macos_packaging.py` fails if that step is removed or moved after
  the download.
- **A new failure on the first green attempt.** Checks on the merged tip passed on
  py3.9 and failed on py3.11 with `pyarrow requires NumPy 2.0 or newer, found
  1.26.4`. pyarrow 26.0.0 had been released after Codex's last passing run; Checks
  installed `requirements.txt` without constraints, so py3.11 took it while py3.9,
  with no matching wheel, fell back to 21.0.0. The shipped app was unaffected,
  because its build installs against `packaging/constraints-macos.txt`. Checks now
  installs against the same pins, so it tests the stack that ships.
