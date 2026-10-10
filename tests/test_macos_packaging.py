"""Release guards must not certify incomplete or wrong-architecture bundles."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def load_script(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load_script("build_macos_app")
release = load_script("finalize_macos_release")
signing = load_script("configure_macos_signing")
publish = load_script("prepare_macos_release")


class PackagingTests(unittest.TestCase):
    def test_every_native_file_including_extensionless_is_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(301):
                (root / ("lib%03d.so" % index)).write_bytes(b"\xcf\xfa\xed\xfe" + b"fixture")
            (root / "Python").write_bytes(b"\xcf\xfa\xed\xfe" + b"fixture")
            (root / "not-native.txt").write_text("ordinary text")
            with patch.object(build, "file_archs", side_effect=lambda path: {"arm64"} if path.name == "Python" else {"x86_64"}):
                report = build.audit_native_files([root, root], "x86_64")
            self.assertEqual(report["checked"], 302)
            self.assertEqual(len(report["thin_other_arch"]), 1)

    def test_unreadable_native_architecture_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "Python"
            binary.write_bytes(b"\xcf\xfa\xed\xfe")
            with patch.object(build, "file_archs", return_value=set()):
                report = build.audit_native_files([binary], "arm64")
            self.assertEqual(report["unreadable_arch"], [str(binary)])

    def test_release_requires_matching_runtime_architecture_and_success(self):
        manifest = {"architecture": "arm64", "bundle": {"problems": []}}
        release.validate_reports(manifest, [{"status": "passed", "architecture": "arm64"}] * 2)
        for bad in ({"status": "failed", "architecture": "arm64"},
                    {"status": "passed", "architecture": "x86_64"}):
            with self.assertRaises(ValueError):
                release.validate_reports(manifest, [bad])

    def test_bundle_problems_block_release(self):
        with self.assertRaises(ValueError):
            release.validate_reports({"architecture": "arm64", "bundle": {"problems": ["missing UI"]}}, [])

    def test_absent_credentials_use_explicit_test_mode(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(signing, "quiet") as quiet:
            signing.prepare()
            quiet.assert_not_called()

    def test_partial_signing_identity_is_not_silently_downgraded(self):
        with patch.dict(os.environ, {"SPATIALMIND_CODESIGN_IDENTITY": "Developer ID Application: Example"}, clear=True):
            with self.assertRaises(ValueError):
                signing.prepare()


class PublicationTests(unittest.TestCase):
    def test_publishing_requires_a_green_checks_run_before_any_upload(self):
        """1.0.1 was published while checks.yml was red on every commit of its
        branch. The build workflow verified its own run and nothing else; the
        full suite, evals and doc counts live in Checks. Publishing has to ask
        Checks, and has to ask before anything is downloaded or uploaded."""
        import yaml

        workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "build-macos.yml"
        steps = [step.get("name") or step.get("uses")
                 for step in yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]["publish"]["steps"]]
        guard = "Require a green Checks run on the same commit"
        self.assertIn(guard, steps)
        self.assertLess(steps.index(guard), steps.index("Download both verified artifacts"))
        self.assertIn("checks.yml/runs?head_sha=$SOURCE_COMMIT", workflow.read_text(encoding="utf-8"))

    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.commit = "a" * 40
        manifest = {"architecture": "arm64", "version": "1.0.1", "source_commit": self.commit,
                    "source_dirty": False, "status": "runtime_verified", "bundle": {"problems": []}}
        headless = {"status": "passed", "architecture": "arm64", "passed": 13, "total": 13,
                    "analysis": {"result": {"results": [
                        {"tool": "qc_and_cluster", "metrics": {"engine": "scanpy"}},
                        {"tool": "spatial_variable_genes", "metrics": {"engine": "squidpy"}}]}}}
        native = {"status": "passed", "architecture": "arm64", "native_window": True,
                  "folder_panel": True, "page": {"bridge": True}}
        for name, value in (("build_manifest.json", manifest), ("headless_smoke.json", headless),
                            ("native_smoke.json", native)):
            (self.root / name).write_text(json.dumps(value))
        (self.root / "dependencies.txt").write_text("fixture-dependency==1.0\n")
        for extension in ("dmg", "zip"):
            (self.root / ("SpatialMind-Studio-1.0.1-macos-arm64." + extension)).write_bytes(b"synthetic installer fixture")
        files = sorted(self.root.iterdir())
        (self.root / "SHA256SUMS.txt").write_text(
            "".join("%s  %s\n" % (publish.digest(path), path.name) for path in files))

    def test_matching_evidence_and_checksums_are_accepted(self):
        self.assertEqual(len(publish.verify_artifact(self.root, "arm64", "1.0.1", self.commit)), 6)

    def test_modified_installer_is_refused(self):
        (self.root / "SpatialMind-Studio-1.0.1-macos-arm64.dmg").write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            publish.verify_artifact(self.root, "arm64", "1.0.1", self.commit)

    def test_different_source_commit_is_refused(self):
        with self.assertRaises(ValueError):
            publish.verify_artifact(self.root, "arm64", "1.0.1", "b" * 40)


if __name__ == "__main__":
    unittest.main()
