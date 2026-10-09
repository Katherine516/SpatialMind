#!/usr/bin/env python3
"""Publishable artifacts are created only after both packaged runtime probes pass."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def validate_reports(manifest, reports):
    for report in reports:
        if report.get("status") != "passed" or report.get("architecture") != manifest["architecture"]:
            raise ValueError("Runtime verification failed or ran on the wrong architecture")
    if manifest["bundle"].get("problems"):
        raise ValueError("Bundle verification failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    args = parser.parse_args()
    root = args.dist.resolve()
    manifest_path = root / "build_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    reports = [json.loads((root / name).read_text()) for name in ("headless_smoke.json", "native_smoke.json")]
    validate_reports(manifest, reports)
    archive = root / ("SpatialMind-Studio-%s-macos-%s.zip" % (manifest["version"], manifest["architecture"]))
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                    str(root / "SpatialMind Studio.app"), str(archive)], check=True)
    manifest.update(status="runtime_verified", runtime_tests=reports)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    paths = sorted(list(root.glob("*.zip")) + list(root.glob("*.dmg")) +
                   [manifest_path, root / "headless_smoke.json", root / "native_smoke.json", root / "dependencies.txt"])
    lines = []
    for path in paths:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        lines.append("%s  %s\n" % (digest.hexdigest(), path.name))
    (root / "SHA256SUMS.txt").write_text("".join(lines), encoding="utf-8")
    print("Verified artifacts: " + ", ".join(path.name for path in paths))


if __name__ == "__main__":
    main()
