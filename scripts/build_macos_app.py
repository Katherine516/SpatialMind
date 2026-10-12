#!/usr/bin/env python3
"""Build `SpatialMind Studio.app` for macOS.

One important limitation, stated up front because it decides how you ship:
PyInstaller freezes the *installed* wheels, and a wheel is built for one
architecture. This script therefore builds for the architecture of the machine
it runs on, and refuses to claim otherwise. Producing both an Intel and an
Apple Silicon app means running it twice, once on each -- or letting the CI
matrix in .github/workflows/build-macos.yml do it.

    python scripts/build_macos_app.py            # build + verify
    python scripts/build_macos_app.py --dmg      # also produce a .dmg
    python scripts/build_macos_app.py --check    # report feasibility, build nothing
"""

from pathlib import Path
import argparse
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP_NAME = "SpatialMind Studio"
ICNS = PACKAGING / "SpatialMindStudio.icns"
# Every module the Studio actually imports. If one of these is thin for the
# wrong architecture, the built app dies at launch with no window and no output.
REQUIRED_MODULES = [
    "fastapi", "uvicorn", "pydantic", "numpy", "scipy", "pandas", "pyarrow",
    "h5py", "anndata", "scanpy", "squidpy", "sklearn", "matplotlib", "igraph",
    "tifffile", "PIL", "reportlab", "numba", "llvmlite", "leidenalg", "umap",
    # Export formats and upload parsing. Verified here because each one is a
    # feature that fails only when a user clicks it, not at launch.
    "docx", "openpyxl", "multipart",
    # The native window. Without these the app falls back to a browser tab.
    "webview", "objc", "AppKit", "WebKit",
]


def run(command, **kwargs):
    print("$ %s" % " ".join(str(c) for c in command))
    return subprocess.run(command, check=True, **kwargs)


def host_arch() -> str:
    return platform.machine()


def arch_label(arch: str) -> str:
    return {"x86_64": "Intel (x86_64)", "arm64": "Apple Silicon (arm64)"}.get(arch, arch)


def file_archs(path: Path):
    """Architectures present in a Mach-O file, via `lipo -archs`."""
    try:
        out = subprocess.run(["lipo", "-archs", str(path)], capture_output=True, text=True, timeout=30)
        return set(out.stdout.split()) if out.returncode == 0 else set()
    except Exception:
        return set()


MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}


def native_files(roots):
    """Find every Mach-O file, including extensionless Python/framework binaries."""
    seen = set()
    for root in roots:
        paths = root.rglob("*") if root.is_dir() else [root]
        for path in paths:
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            with path.open("rb") as stream:
                if stream.read(4) in MACHO_MAGICS:
                    yield path


def audit_native_files(roots, arch):
    checked, wrong, unreadable = 0, [], []
    for path in native_files(roots):
        archs = file_archs(path)
        checked += 1
        if not archs:
            unreadable.append(str(path))
        elif arch not in archs:
            wrong.append("%s (%s)" % (path, ",".join(sorted(archs))))
    return {"checked": checked, "thin_other_arch": wrong, "unreadable_arch": unreadable}


def audit_environment():
    """Which installed native extensions can run on which architecture."""
    import importlib.util

    report = {"host": host_arch(), "missing": []}
    roots = [Path(sys.executable).resolve()]
    for name in REQUIRED_MODULES:
        try:
            spec = importlib.util.find_spec(name)
        except Exception:
            spec = None
        if spec is None:
            report["missing"].append(name)
            continue
        locations = list(getattr(spec, "submodule_search_locations", None) or [])
        roots.extend(Path(path) for path in locations)
        if not locations and spec.origin:
            roots.append(Path(spec.origin))
    report.update(audit_native_files(roots, host_arch()))
    return report


def build_icns() -> bool:
    """Render the icon to Apple's template. See scripts/build_app_icon.py."""
    script = ROOT / "scripts" / "build_app_icon.py"
    if not script.exists():
        print("No icon builder at %s; building without an icon." % script)
        return False
    try:
        run([sys.executable, str(script)])
    except subprocess.CalledProcessError:
        print("Icon build failed; continuing without one.")
        return False
    return ICNS.exists()


def verify_app(app_path: Path, expected_arch=None) -> dict:
    """Check the built bundle before anyone tries to open it."""
    arch = expected_arch or host_arch()
    results = {"exists": app_path.exists(), "problems": [], "binary_archs": set(), "size_mb": 0}
    if not results["exists"]:
        results["problems"].append("No .app was produced at %s" % app_path)
        return results

    binary = app_path / "Contents" / "MacOS" / "SpatialMindStudio"
    if not binary.exists():
        results["problems"].append("Missing executable at Contents/MacOS/SpatialMindStudio")
    else:
        results["binary_archs"] = file_archs(binary)
        if arch not in results["binary_archs"]:
            results["problems"].append(
                "Executable is %s but the requested architecture is %s" % (",".join(results["binary_archs"]), arch))

    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.exists():
        results["problems"].append("Missing Info.plist")
    else:
        with open(plist_path, "rb") as handle:
            plist = plistlib.load(handle)
        results["bundle_id"] = plist.get("CFBundleIdentifier", "")
        results["version"] = plist.get("CFBundleShortVersionString", "")
        results["minimum_macos"] = plist.get("LSMinimumSystemVersion", "")

        results["ats_local"] = bool(
            (plist.get("NSAppTransportSecurity") or {}).get("NSAllowsLocalNetworking"))
        if not results["ats_local"]:
            results["problems"].append(
                "Info.plist does not allow local networking; the window cannot load http://127.0.0.1")

    # The native window ships as pywebview over pyobjc. If either is missing the
    # app silently degrades to a browser tab, which is not what was built.
    bundled = {path.name for path in app_path.rglob("*") if path.is_dir()}
    for package in ("webview", "objc"):
        if package not in bundled and not list(app_path.rglob("%s*" % package))[:1]:
            results["problems"].append("%s is not in the bundle; the native window would fall back to a browser" % package)

    icon = app_path / "Contents" / "Resources" / "SpatialMindStudio.icns"
    if not icon.exists():
        results["problems"].append("No icon in the bundle; it would show the generic app tile")
    else:
        results["icon_kb"] = round(icon.stat().st_size / 1024)

    static = app_path / "Contents" / "Resources" / "spatialmind" / "app" / "static" / "index.html"
    frameworks_static = app_path / "Contents" / "Frameworks" / "spatialmind" / "app" / "static" / "index.html"
    if not static.exists() and not frameworks_static.exists():
        results["problems"].append("The web UI (spatialmind/app/static/index.html) is not inside the bundle")

    total = 0
    for path in app_path.rglob("*"):
        if path.is_file() and not path.is_symlink():
            try:
                total += path.stat().st_size
            except OSError:
                pass
    results["size_mb"] = round(total / (1024 * 1024), 1)

    # Mixed architectures inside one bundle mean it will fail on some machine.
    native = audit_native_files([app_path], arch)
    results["native_audit"] = native
    if native["thin_other_arch"]:
        results["problems"].append("%d bundled libraries cannot run on %s: %s"
                                   % (len(native["thin_other_arch"]), arch, ", ".join(native["thin_other_arch"][:5])))
    if native["unreadable_arch"]:
        results["problems"].append("Could not verify %d native binary architectures" % len(native["unreadable_arch"]))
    return results


def make_dmg(app_path: Path, arch: str, version="1.0.1") -> Path:
    dmg = DIST / ("SpatialMind-Studio-%s-macos-%s.dmg" % (version, arch))
    if dmg.exists():
        dmg.unlink()
    staging = DIST / "dmg-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    run(["cp", "-R", str(app_path), str(staging / app_path.name)])
    os.symlink("/Applications", str(staging / "Applications"))
    run(["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", str(staging),
         "-ov", "-format", "UDZO", str(dmg)])
    shutil.rmtree(staging, ignore_errors=True)
    return dmg


def main() -> int:
    global DIST, BUILD
    parser = argparse.ArgumentParser(description="Build the SpatialMind Studio macOS app.")
    parser.add_argument("--dmg", action="store_true", help="Also produce a .dmg for distribution.")
    parser.add_argument("--check", action="store_true", help="Audit the environment and exit.")
    parser.add_argument("--clean", action="store_true", help="Remove build/ and dist/ first.")
    parser.add_argument("--expected-arch", choices=["x86_64", "arm64"])
    parser.add_argument("--version", default="1.0.1")
    parser.add_argument("--dist-dir", type=Path, default=DIST)
    parser.add_argument("--build-dir", type=Path, default=BUILD)
    parser.add_argument("--notarize-profile", help="Existing notarytool keychain profile; requires Developer ID signing.")
    args = parser.parse_args()

    DIST, BUILD = args.dist_dir.resolve(), args.build_dir.resolve()

    if sys.platform != "darwin":
        print("This builds a macOS .app and must run on macOS. Host: %s" % sys.platform)
        return 2

    arch = host_arch()
    if args.expected_arch and arch != args.expected_arch:
        print("Native %s Python required; current interpreter is %s." % (args.expected_arch, arch))
        return 2
    if arch not in {"x86_64", "arm64"}:
        print("Unsupported architecture: " + arch)
        return 2
    identity = os.environ.get("SPATIALMIND_CODESIGN_IDENTITY", "").strip()
    if args.notarize_profile and (not identity or not args.dmg):
        parser.error("Notarization requires a Developer ID identity and --dmg.")
    print("=" * 68)
    print("SpatialMind Studio -- macOS build")
    print("  host architecture : %s" % arch_label(arch))
    print("  python            : %s (%s)" % (platform.python_version(), sys.executable))
    print("=" * 68)

    audit = audit_environment()
    if audit["missing"]:
        print("\nMissing modules the Studio needs: %s" % ", ".join(audit["missing"]))
        print("Install them into this interpreter before building.")
        return 1
    if audit["thin_other_arch"] or audit["unreadable_arch"]:
        print("\n%d installed libraries cannot run on %s:" % (len(audit["thin_other_arch"]), arch))
        for line in (audit["thin_other_arch"] + audit["unreadable_arch"])[:10]:
            print("   %s" % line)
        return 1
    print("\nEnvironment audit passed: %d native libraries checked, all %s." % (audit["checked"], arch))
    print("This build targets %s only. Build on the other architecture for its app." % arch_label(arch))

    if args.check:
        return 0

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("\nPyInstaller is not installed: pip install pyinstaller")
        return 1

    if args.clean:
        shutil.rmtree(BUILD, ignore_errors=True)
        shutil.rmtree(DIST, ignore_errors=True)

    build_icns()
    build_env = dict(os.environ, SPATIALMIND_BUILD_ARCH=arch, SPATIALMIND_BUILD_VERSION=args.version,
                     SPATIALMIND_MIN_MACOS="15.0")

    print("\nFreezing. This takes several minutes.")
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(DIST),
         "--workpath", str(BUILD), str(PACKAGING / "SpatialMindStudio.spec")], cwd=str(ROOT), env=build_env)

    app_path = DIST / ("%s.app" % APP_NAME)
    print("\nVerifying the bundle.")
    results = verify_app(app_path)
    print("  path       : %s" % app_path)
    print("  size       : %s MB" % results["size_mb"])
    print("  arch       : %s" % (", ".join(sorted(results["binary_archs"])) or "unknown"))
    print("  bundle id  : %s" % results.get("bundle_id", "?"))
    print("  icon       : %s KB" % results.get("icon_kb", "missing"))
    print("  window     : native (pywebview/WKWebView), local networking %s"
          % ("allowed" if results.get("ats_local") else "BLOCKED"))
    if results["problems"]:
        print("\nFAILED verification:")
        for problem in results["problems"]:
            print("   - %s" % problem)
        return 1
    print("  verified   : ok")

    # Signing decides what a recipient sees. A Developer ID identity in
    # SPATIALMIND_CODESIGN_IDENTITY is used when present; otherwise the app is
    # ad-hoc signed, which keeps it launchable on this machine and nowhere else
    # without a manual override.
    signed_properly = False
    if shutil.which("codesign"):
        try:
            command = ["codesign", "--force", "--sign", identity or "-"]
            if identity:
                # Hardened runtime and a timestamp are preconditions for
                # notarisation; without them `notarytool` rejects the upload.
                command += ["--options", "runtime", "--timestamp", "--entitlements", str(PACKAGING / "entitlements.plist")]
            run(command + [str(app_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            run(["codesign", "--verify", "--deep", "--strict", str(app_path)])
            signed_properly = bool(identity)
            print("  signed     : %s" % (("Developer ID (%s)" % identity) if identity else "ad-hoc"))
        except subprocess.CalledProcessError:
            print("  signed     : verification failed; no distribution package will be produced")
            return 1

    if not signed_properly:
        print()
        print("  Ad-hoc signed test build. Downloaded apps may be blocked by Gatekeeper.")
        print("  Developer ID signing and notarization are required for normal distribution.")

    notarized = False
    if args.dmg:
        dmg = make_dmg(app_path, arch, args.version)
        if args.notarize_profile:
            keychain_args = (["--keychain", os.environ["SPATIALMIND_NOTARY_KEYCHAIN"]]
                             if os.environ.get("SPATIALMIND_NOTARY_KEYCHAIN") else [])
            submission = run(["xcrun", "notarytool", "submit", str(dmg), "--keychain-profile",
                              args.notarize_profile, "--wait", "--output-format", "json"] + keychain_args, capture_output=True, text=True)
            status = json.loads(submission.stdout)
            if status.get("status") != "Accepted":
                raise RuntimeError("Notarization failed: " + str(status.get("status")))
            run(["xcrun", "stapler", "staple", str(app_path)])
            dmg = make_dmg(app_path, arch, args.version)
            submission = run(["xcrun", "notarytool", "submit", str(dmg), "--keychain-profile",
                              args.notarize_profile, "--wait", "--output-format", "json"] + keychain_args, capture_output=True, text=True)
            if json.loads(submission.stdout).get("status") != "Accepted":
                raise RuntimeError("Final DMG notarization failed.")
            run(["xcrun", "stapler", "staple", str(dmg)])
            run(["xcrun", "stapler", "validate", str(dmg)])
            notarized = True
        print("  dmg        : %s (%.1f MB)" % (dmg, dmg.stat().st_size / (1024 * 1024)))

    source = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    manifest = {"version": args.version, "architecture": arch, "minimum_macos": "15.0",
                "source_commit": source.stdout.strip(), "source_dirty": bool(dirty.stdout.strip()),
                "python": platform.python_version(), "signature": "developer_id" if signed_properly else "ad_hoc",
                "notarized": notarized, "status": "built_awaiting_runtime_tests", "bundle": results}
    manifest["bundle"]["binary_archs"] = sorted(results["binary_archs"])
    (DIST / "build_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("\nDone. Open with:  open '%s'" % app_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
