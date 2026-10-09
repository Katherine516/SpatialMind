"""Release guards must not certify incomplete or wrong-architecture bundles."""

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
