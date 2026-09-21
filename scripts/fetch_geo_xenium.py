"""Fetch the analysis files of a GEO-deposited Xenium series, sample by sample.

Modern Xenium data is published to GEO as per-sample supplementary files, and
the whole-series tar is usually far too big to be useful -- GSE311609's is
179 GB. The files an analysis actually needs are a few megabytes each:

    cells.parquet.gz            ~0.3-2.7 MB   coordinates and per-cell QC
    cell_feature_matrix.h5      ~0.9-8 MB     expression
    cell_boundaries.parquet.gz  ~1-8 MB       segmentation, for the viewer

The morphology stack is 240 MB (focus) to 2.8 GB (full) per sample and is only
needed to *look* at tissue, so it is opt-in.

    python scripts/fetch_geo_xenium.py --series GSE311609 --list
    python scripts/fetch_geo_xenium.py --series GSE311609 --match breast_B2 \
        --dest data/GSE311609_breast

## What this does not get you

Nothing here supplies cell type labels. GSE311609 deposits no annotation of any
kind: its cell types were assigned by RCTD from matched snRNA-seq, which is
label transfer, and the gate treats transferred labels as candidates needing
review. A fetched section arrives blocked on a reviewer, exactly like every
other unlabelled section in this workspace.

These bundles also carry no `experiment.xenium`, so pixel size and run metadata
are absent. The loader reads them anyway -- coordinates are already in microns
-- but the morphology viewer cannot align an image without a pixel size.
"""

import argparse
import json
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FTP = "https://ftp.ncbi.nlm.nih.gov/geo"
# Enough to load and gate a section. Morphology is opt-in; transcripts are never
# parsed by this project.
ANALYSIS_FILES = ("cells.parquet.gz", "cell_feature_matrix.h5",
                  "cell_boundaries.parquet.gz", "nucleus_boundaries.parquet.gz")
MORPHOLOGY_FILES = ("morphology_focus.ome.tif.gz",)


def series_prefix(series: str) -> str:
    """GEO nests a series under a truncated-accession folder: GSE311nnn."""
    digits = "".join(ch for ch in series if ch.isdigit())
    return "GSE%snnn" % digits[:-3] if len(digits) > 3 else series


def sample_prefix(gsm: str) -> str:
    digits = "".join(ch for ch in gsm if ch.isdigit())
    return "GSM%snnn" % digits[:-3] if len(digits) > 3 else gsm


def _ssl_context():
    """Verify against certifi when the interpreter's default store cannot.

    On a Mac behind TLS interception the stock context fails with "self signed
    certificate in certificate chain" while curl succeeds, because they read
    different trust stores. Falling back to certifi keeps verification on;
    turning verification off to make a download work would be trading a real
    guarantee for a convenience.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _urlopen(url: str, timeout: int):
    request = urllib.request.Request(url, headers={"User-Agent": "spatialmind/1.0"})
    try:
        return urllib.request.urlopen(request, timeout=timeout, context=_ssl_context())
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            raise SystemExit(
                "TLS verification failed for %s.\n"
                "This machine's trust store does not verify NCBI's chain. Install certifi "
                "(`pip install certifi`) or fetch with curl, which reads a different store.\n"
                "Verification is not disabled here: a download that silently skips it is a "
                "worse outcome than a failed download." % url)
        raise


def read_filelist(series: str):
    url = "%s/series/%s/%s/suppl/filelist.txt" % (FTP, series_prefix(series), series)
    with _urlopen(url, timeout=120) as handle:
        text = handle.read().decode("utf-8", "replace")
    rows = []
    for line in text.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 4 or parts[0] != "File":
            continue
        rows.append({"name": parts[1], "bytes": int(parts[3] or 0)})
    return rows


def group_samples(rows):
    """name -> {gsm, stem, files}. A GEO name is `GSM<id>_<stem>_<file>`."""
    samples = {}
    for row in rows:
        name = row["name"]
        if not name.startswith("GSM") or "_" not in name:
            continue
        gsm, _, rest = name.partition("_")
        for suffix in ANALYSIS_FILES + MORPHOLOGY_FILES + ("transcripts.parquet.gz",
                                                           "morphology.ome.tif.gz"):
            if rest.endswith("_" + suffix):
                stem = rest[: -len(suffix) - 1]
                entry = samples.setdefault(stem, {"gsm": gsm, "stem": stem, "files": {}})
                entry["files"][suffix] = row
                break
    return samples


def decompress_image(path: Path) -> Path:
    """Unwrap a gzipped OME-TIFF, because nothing downstream reads one.

    GEO gzips the morphology stack. `tifffile` needs a real TIFF, and so does
    every asset check that looks for `morphology_focus.ome.tif`. Teaching five
    readers about gzip would be five places to get it wrong; unwrapping once at
    intake is the same bytes and none of the ambiguity.
    """
    import gzip
    import shutil

    target = path.with_suffix("")          # drops the trailing .gz
    if target.exists() and target.stat().st_size > 0:
        return target
    with gzip.open(path, "rb") as source, open(target, "wb") as handle:
        shutil.copyfileobj(source, handle, length=1 << 22)
    path.unlink()                          # the archive is no longer useful
    return target


def download(url: str, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _urlopen(url, timeout=900) as response, open(destination, "wb") as handle:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)
    return destination.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a GEO Xenium series' analysis files.")
    parser.add_argument("--series", required=True, help="GEO series accession, e.g. GSE311609.")
    parser.add_argument("--match", default="",
                        help="Only samples whose name contains this, e.g. breast_B2.")
    parser.add_argument("--dest", default="", help="Destination directory.")
    parser.add_argument("--with-morphology", action="store_true",
                        help="Also fetch morphology_focus (hundreds of MB per sample).")
    parser.add_argument("--list", action="store_true", help="List matching samples and exit.")
    args = parser.parse_args()

    samples = group_samples(read_filelist(args.series))
    selected = {name: entry for name, entry in sorted(samples.items())
                if not args.match or args.match in name}
    if not selected:
        raise SystemExit("No sample in %s matches %r. Use --list to see them."
                         % (args.series, args.match))

    wanted = ANALYSIS_FILES + (MORPHOLOGY_FILES if args.with_morphology else ())
    if args.list:
        for name, entry in selected.items():
            total = sum(entry["files"][f]["bytes"] for f in wanted if f in entry["files"])
            print("%-42s %-12s %8.1f MB" % (name, entry["gsm"], total / 1048576))
        print("\n%d sample(s), %.1f MB with the current flags."
              % (len(selected),
                 sum(entry["files"][f]["bytes"] for entry in selected.values()
                     for f in wanted if f in entry["files"]) / 1048576))
        return

    if not args.dest:
        raise SystemExit("--dest is required unless --list is given.")

    manifest = []
    for name, entry in selected.items():
        bundle = Path(args.dest) / name
        print("\n%s -> %s" % (name, bundle))
        got = {}
        for suffix in wanted:
            row = entry["files"].get(suffix)
            if not row:
                print("  (no %s in this series)" % suffix)
                continue
            target = bundle / suffix
            if target.exists() and target.stat().st_size == row["bytes"]:
                print("  have %s" % suffix)
                got[suffix] = target.stat().st_size
                continue
            unwrapped = bundle / suffix[:-3] if suffix.endswith(".gz") else None
            if unwrapped is not None and unwrapped.exists() and unwrapped.stat().st_size > 0:
                print("  have %s (already unwrapped)" % unwrapped.name)
                got[suffix] = unwrapped.stat().st_size
                continue
            url = "%s/samples/%s/%s/suppl/%s" % (FTP, sample_prefix(entry["gsm"]),
                                                 entry["gsm"], row["name"])
            print("  fetching %s (%.1f MB)" % (suffix, row["bytes"] / 1048576))
            got[suffix] = download(url, target)
            if suffix.endswith(".ome.tif.gz"):
                unwrapped = decompress_image(target)
                print("    unwrapped -> %s (%.0f MB)"
                      % (unwrapped.name, unwrapped.stat().st_size / 1048576))
                got[suffix] = unwrapped.stat().st_size
        manifest.append({"sample": name, "gsm": entry["gsm"], "path": str(bundle), "files": got})

    out = Path(args.dest) / "geo_fetch_manifest.json"
    out.write_text(json.dumps({"series": args.series, "samples": manifest}, indent=2),
                   encoding="utf-8")
    print("\nWrote %s" % out)
    print("\nThese sections have no cell type labels -- GEO deposits none for this series -- so "
          "each one arrives blocked on a reviewer.")


if __name__ == "__main__":
    main()
