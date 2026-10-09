#!/usr/bin/env python3
"""Configure optional CI signing without exposing certificate/private credentials."""

import argparse
import base64
import os
from pathlib import Path
import secrets
import subprocess
import tempfile


def quiet(command):
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def prepare():
    certificate = os.environ.get("MACOS_CERTIFICATE_P12", "")
    if not certificate:
        if os.environ.get("SPATIALMIND_CODESIGN_IDENTITY"):
            raise ValueError("A signing identity was configured without its certificate")
        print("No Developer ID certificate configured: ad-hoc test build only.")
        return
    identity = os.environ.get("SPATIALMIND_CODESIGN_IDENTITY", "")
    if not identity.startswith("Developer ID Application:"):
        raise ValueError("Use a Developer ID Application identity, not development signing")
    runner_temp = Path(os.environ["RUNNER_TEMP"])
    keychain = runner_temp / "spatialmind-signing.keychain-db"
    password = secrets.token_urlsafe(32)
    try:
        quiet(["security", "create-keychain", "-p", password, str(keychain)])
        quiet(["security", "set-keychain-settings", "-lut", "21600", str(keychain)])
        quiet(["security", "unlock-keychain", "-p", password, str(keychain)])
        with tempfile.NamedTemporaryFile(dir=runner_temp, suffix=".p12") as handle:
            handle.write(base64.b64decode(certificate, validate=True))
            handle.flush()
            quiet(["security", "import", handle.name, "-k", str(keychain), "-P",
                   os.environ.get("MACOS_CERTIFICATE_PASSWORD", ""), "-T", "/usr/bin/codesign"])
        quiet(["security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:", "-s", "-k", password, str(keychain)])
        existing = subprocess.run(["security", "list-keychains", "-d", "user"], check=True, capture_output=True, text=True)
        search = [line.strip().strip('"') for line in existing.stdout.splitlines() if line.strip()]
        quiet(["security", "list-keychains", "-d", "user", "-s", str(keychain)] + search)
        credentials = [os.environ.get(name, "") for name in ("APPLE_ID", "APPLE_TEAM_ID", "APPLE_APP_PASSWORD")]
        if any(credentials) and not all(credentials):
            raise ValueError("All three Apple notarization credentials are required")
        if all(credentials):
            quiet(["xcrun", "notarytool", "store-credentials", "spatialmind-notary", "--keychain", str(keychain),
                   "--apple-id", credentials[0], "--team-id", credentials[1], "--password", credentials[2]])
            with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as stream:
                stream.write("SPATIALMIND_NOTARY_PROFILE=spatialmind-notary\n")
                stream.write("SPATIALMIND_NOTARY_KEYCHAIN=%s\n" % keychain)
        print("Developer ID signing prepared; notarization %s." % ("enabled" if all(credentials) else "not configured"))
    except Exception:
        cleanup()
        raise


def cleanup():
    keychain = Path(os.environ["RUNNER_TEMP"]) / "spatialmind-signing.keychain-db"
    if keychain.exists():
        quiet(["security", "delete-keychain", str(keychain)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "cleanup"])
    args = parser.parse_args()
    try:
        prepare() if args.mode == "prepare" else cleanup()
    except Exception:
        # Subprocess exceptions contain argv, which may contain a password.
        print("Signing setup failed. Check certificate, identity and complete Apple credentials; secret values are suppressed.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
