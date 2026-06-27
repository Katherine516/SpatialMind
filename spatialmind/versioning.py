from importlib import metadata
from typing import Dict, List, Tuple


REQUIRED_RUNTIME_PACKAGES: Dict[str, Tuple[str, ...]] = {
    "anndata": (),
    "h5py": (),
    "numpy": ("1.",),
    "scanpy": ("1.",),
    "scipy": ("1.",),
    "squidpy": ("1.",),
}


OPTIONAL_RUNTIME_PACKAGES: Tuple[str, ...] = (
    "cell2location",
    "celltypist",
    "decoupler",
    "infercnvpy",
    "liana",
    "omnipath",
    "scvi-tools",
    "spatialdata",
    "spatialdata-io",
)


def collect_versions(packages: Dict[str, Tuple[str, ...]] = REQUIRED_RUNTIME_PACKAGES) -> Dict[str, str]:
    versions = {}
    for package in packages:
        versions[package] = metadata.version(package)
    return versions


def check_runtime_versions(include_optional: bool = False) -> Dict[str, object]:
    missing: List[str] = []
    incompatible: List[str] = []
    versions: Dict[str, str] = {}
    for package, prefixes in REQUIRED_RUNTIME_PACKAGES.items():
        try:
            version = metadata.version(package)
        except metadata.PackageNotFoundError:
            missing.append(package)
            continue
        versions[package] = version
        if prefixes and not version.startswith(prefixes):
            incompatible.append("%s==%s does not match allowed prefixes %s" % (package, version, ", ".join(prefixes)))
    optional_missing: List[str] = []
    if include_optional:
        for package in OPTIONAL_RUNTIME_PACKAGES:
            try:
                versions[package] = metadata.version(package)
            except metadata.PackageNotFoundError:
                optional_missing.append(package)
    return {
        "ok": not missing and not incompatible,
        "versions": versions,
        "missing": missing,
        "incompatible": incompatible,
        "optional_missing": optional_missing,
    }


def main() -> None:
    report = check_runtime_versions(include_optional=True)
    print("SpatialMind runtime version check")
    for package, version in sorted(report["versions"].items()):
        print("- %s %s" % (package, version))
    if report["optional_missing"]:
        print("Optional packages not installed: %s" % ", ".join(report["optional_missing"]))
    if not report["ok"]:
        problems = list(report["missing"]) + list(report["incompatible"])
        raise SystemExit("Version check failed: %s" % "; ".join(problems))
    print("Version check passed.")


if __name__ == "__main__":
    main()
