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
    "tifffile", "PIL", "reportlab",
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


def audit_environment():
    """Which installed native extensions can run on which architecture."""
    import importlib.util

    report = {"host": host_arch(), "missing": [], "thin_other_arch": [], "checked": 0}
    for name in REQUIRED_MODULES:
        try:
            spec = importlib.util.find_spec(name)
        except Exception:
            spec = None
        if spec is None:
            report["missing"].append(name)
            continue
        locations = list(getattr(spec, "submodule_search_locations", None) or [])
        root = Path(locations[0]) if locations else Path(str(spec.origin)).parent
        for so in list(root.rglob("*.so"))[:40]:
            archs = file_archs(so)
            report["checked"] += 1
            if archs and host_arch() not in archs:
                report["thin_other_arch"].append("%s: %s (%s)" % (name, so.name, ",".join(sorted(archs))))
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


def verify_app(app_path: Path) -> dict:
    """Check the built bundle before anyone tries to open it."""
    results = {"exists": app_path.exists(), "problems": [], "binary_archs": set(), "size_mb": 0}
    if not results["exists"]:
        results["problems"].append("No .app was produced at %s" % app_path)
        return results

    binary = app_path / "Contents" / "MacOS" / "SpatialMindStudio"
    if not binary.exists():
        results["problems"].append("Missing executable at Contents/MacOS/SpatialMindStudio")
    else:
        results["binary_archs"] = file_archs(binary)
        if host_arch() not in results["binary_archs"]:
            results["problems"].append(
                "Executable is %s but this machine is %s" % (",".join(results["binary_archs"]), host_arch()))

    plist_path = app_path / "Contents" / "Info.plist"
    if not plist_path.exists():
        results["problems"].append("Missing Info.plist")
    else:
        with open(plist_path, "rb") as handle:
            plist = plistlib.load(handle)
        results["bundle_id"] = plist.get("CFBundleIdentifier", "")
        results["version"] = plist.get("CFBundleShortVersionString", "")

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
    wrong = []
    for path in list(app_path.rglob("*.so"))[:250] + list(app_path.rglob("*.dylib"))[:250]:
        archs = file_archs(path)
        if archs and host_arch() not in archs:
            wrong.append("%s (%s)" % (path.name, ",".join(sorted(archs))))
    if wrong:
        results["problems"].append("%d bundled libraries cannot run on %s: %s"
                                   % (len(wrong), host_arch(), ", ".join(wrong[:5])))
    return results


def make_dmg(app_path: Path, arch: str) -> Path:
    dmg = DIST / ("SpatialMind-Studio-1.0.0-macos-%s.dmg" % arch)
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
    parser = argparse.ArgumentParser(description="Build the SpatialMind Studio macOS app.")
    parser.add_argument("--dmg", action="store_true", help="Also produce a .dmg for distribution.")
    parser.add_argument("--check", action="store_true", help="Audit the environment and exit.")
    parser.add_argument("--clean", action="store_true", help="Remove build/ and dist/ first.")
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("This builds a macOS .app and must run on macOS. Host: %s" % sys.platform)
        return 2

    arch = host_arch()
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
    if audit["thin_other_arch"]:
        print("\n%d installed libraries cannot run on %s:" % (len(audit["thin_other_arch"]), arch))
        for line in audit["thin_other_arch"][:10]:
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

    print("\nFreezing. This takes several minutes.")
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(DIST),
         "--workpath", str(BUILD), str(PACKAGING / "SpatialMindStudio.spec")], cwd=str(ROOT))

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
    identity = os.environ.get("SPATIALMIND_CODESIGN_IDENTITY", "").strip()
    signed_properly = False
    if shutil.which("codesign"):
        try:
            command = ["codesign", "--force", "--deep", "--sign", identity or "-"]
            if identity:
                # Hardened runtime and a timestamp are preconditions for
                # notarisation; without them `notarytool` rejects the upload.
                command += ["--options", "runtime", "--timestamp"]
            run(command + [str(app_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            signed_properly = bool(identity)
            print("  signed     : %s" % (("Developer ID (%s)" % identity) if identity else "ad-hoc"))
        except subprocess.CalledProcessError:
            print("  signed     : signing failed; the app still runs on this machine")

    if not signed_properly:
        print()
        print("  NOT NOTARISED. On any Mac but this one, macOS will refuse to open it:")
        print("    \"SpatialMind Studio is damaged and can't be opened\" -- which is Gatekeeper,")
        print("    not a corrupt download. Until the app is signed and notarised, a recipient has to run")
        print("      xattr -dr com.apple.quarantine '/Applications/%s.app'" % APP_NAME)
        print("    To do this properly: set SPATIALMIND_CODESIGN_IDENTITY to a Developer ID Application")
        print("    identity (`security find-identity -v -p codesigning`), rebuild, then notarise:")
        print("      xcrun notarytool submit <dmg> --apple-id <id> --team-id <team> --password <app-password> --wait")
        print("      xcrun stapler staple <dmg>")

    if args.dmg:
        dmg = make_dmg(app_path, arch)
        print("  dmg        : %s (%.1f MB)" % (dmg, dmg.stat().st_size / (1024 * 1024)))

    print("\nDone. Open with:  open '%s'" % app_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
