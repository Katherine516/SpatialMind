#!/usr/bin/env python3
"""Assemble verified native installers and evidence without rebuilding the apps."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.finalize_macos_release import validate_reports


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def verify_artifact(root, arch, version, commit):
    manifest = json.loads((root / "build_manifest.json").read_text())
    if (manifest.get("architecture") != arch or manifest.get("version") != version
            or manifest.get("source_commit") != commit or manifest.get("source_dirty")
            or manifest.get("status") != "runtime_verified"):
        raise ValueError("Build identity is not the requested clean, runtime-verified source")
    headless = json.loads((root / "headless_smoke.json").read_text())
    native = json.loads((root / "native_smoke.json").read_text())
    validate_reports(manifest, [headless, native])
    if headless.get("passed") != headless.get("total") or headless.get("total", 0) < 13:
        raise ValueError("Incomplete packaged API acceptance")
    engines = {entry["tool"]: entry.get("metrics", {}).get("engine")
               for entry in headless.get("analysis", {}).get("result", {}).get("results", [])}
    if engines.get("qc_and_cluster") != "scanpy" or engines.get("spatial_variable_genes") != "squidpy":
        raise ValueError("Strict scientific backend evidence is missing")
    if not native.get("native_window") or not native.get("folder_panel") or not native.get("page", {}).get("bridge"):
        raise ValueError("Native window evidence is missing")
    checksums = {}
    for line in (root / "SHA256SUMS.txt").read_text().splitlines():
        checksum, name = line.split(maxsplit=1)
        if Path(name).name != name or name in checksums or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("Invalid checksum inventory")
        checksums[name] = checksum
    files = ["build_manifest.json", "headless_smoke.json", "native_smoke.json", "dependencies.txt"]
    files += ["SpatialMind-Studio-%s-macos-%s.%s" % (version, arch, extension) for extension in ("dmg", "zip")]
    for name in files:
        if name not in checksums or digest(root / name) != checksums[name]:
            raise ValueError("Artifact integrity check failed: " + name)
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version) or not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        parser.error("A semantic version and full source commit are required")
    verified = []
    for arch in ("arm64", "x86_64"):
        root = args.artifacts / ("SpatialMind-Studio-macos-" + arch)
        verified.append((arch, root, verify_artifact(root, arch, args.version, args.commit)))
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = args.output / ("SpatialMind-Studio-%s-verification.zip" % args.version)
    with zipfile.ZipFile(evidence, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for arch, root, names in verified:
            for name in names:
                if name.endswith((".dmg", ".zip")):
                    shutil.copy2(root / name, args.output / name)
                else:
                    archive.write(root / name, "%s/%s" % (arch, name))
            archive.write(root / "SHA256SUMS.txt", "%s/SHA256SUMS.txt" % arch)
            example = root / "smoke_example"
            if example.exists():
                for path in sorted(example.rglob("*")):
                    if path.is_file() and not path.is_symlink():
                        archive.write(path, "%s/smoke_example/%s" % (arch, path.relative_to(example)))
    downloads = sorted(path for path in args.output.iterdir() if path.suffix in {".zip", ".dmg"})
    (args.output / "SHA256SUMS.txt").write_text(
        "".join("%s  %s\n" % (digest(path), path.name) for path in downloads), encoding="utf-8")
    print("Both native packages and their evidence passed source, runtime and integrity checks.")


if __name__ == "__main__":
    # Support both script and module invocation.
    main()
