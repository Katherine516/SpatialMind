#!/usr/bin/env python3
"""Launch the packaged Cocoa/WKWebView window, not a headless substitute."""

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import time

from smoke_test_macos_app import make_dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = args.report.resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)
    binary = args.app.resolve() / "Contents/MacOS/SpatialMindStudio"
    result = {"status": "failed", "architecture": platform.machine()}
    with tempfile.TemporaryDirectory(prefix="spatialmind-window-") as directory:
        workspace = Path(directory)
        make_dataset(workspace / "data")
        env = dict(os.environ)
        for name in ("SPATIALMIND_HEADLESS", "SPATIALMIND_NO_BROWSER"):
            env.pop(name, None)
        env.update(SPATIALMIND_DATA_ROOT=str(workspace / "data"),
                   SPATIALMIND_OUTPUT_ROOT=str(workspace / "outputs"),
                   SPATIALMIND_SUPPORT_DIR=str(workspace / "support"),
                   SPATIALMIND_NO_WARMUP="1", SPATIALMIND_PORT="8792",
                   SPATIALMIND_NATIVE_SMOKE_REPORT=str(report))
        with report.with_suffix(".log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([str(binary)], env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline and not report.exists() and process.poll() is None:
                    time.sleep(.5)
                if report.exists():
                    result.update(json.loads(report.read_text(encoding="utf-8")))
                    process.wait(timeout=20)
                    if process.returncode != 0:
                        result.update(status="failed", error="Window process exited with code %s" % process.returncode)
                else:
                    result["error"] = "Native window probe timed out or app exited early"
            except Exception as exc:
                result.update(status="failed", error=str(exc))
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=15)
    result["scope"] = "Visible native window, WKWebView DOM/bridge and folder-panel construction; not interactive folder consent"
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
