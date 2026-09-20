"""Check the counts in docs/ against the code, and refresh them with --write.

`docs/agent_architecture.md` is the file whose own section "Three
self-descriptions that disagreed" records this failure mode, and it had drifted
again: 166 unit tests (234), legacy eval 15/15 (16/16), MVP eval 11/11 (13/13),
"16 are plannable and 14 are hidden" (12 and 18). Meanwhile
`docs/spatialmind_agent_reference.html` already said 12, so the two docs
disagreed with each other as well as with the code.

Typing these numbers by hand is what produced the drift. This derives them, so
`--check` fails in CI when a doc falls behind and `--write` fixes it.

    python scripts/check_doc_numbers.py            # report
    python scripts/check_doc_numbers.py --check    # non-zero exit on drift
    python scripts/check_doc_numbers.py --write    # rewrite the doc lines
"""

import argparse
import configparser
import re
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARCHITECTURE = ROOT / "docs" / "agent_architecture.md"


def measure() -> dict:
    from spatialmind.tools import build_default_registry

    registry = build_default_registry()
    plannable = len(registry.list_plannable())
    registered = len(registry.list_all())

    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    test_count = suite.countTestCases()

    cases = {
        name: len(list((ROOT / "eval" / name).glob("*.yaml")) + list((ROOT / "eval" / name).glob("*.json")))
        for name in ("test_cases", "mvp_cases")
    }

    parser = configparser.ConfigParser()
    parser.read(ROOT / ".importlinter")
    contracts = len([s for s in parser.sections() if s.startswith("importlinter:contract:")])

    return {
        "tests": test_count,
        "legacy_cases": cases["test_cases"],
        "mvp_cases": cases["mvp_cases"],
        "contracts": contracts,
        "registered": registered,
        "plannable": plannable,
        "hidden": registered - plannable,
    }


def expected_lines(counts: dict) -> dict:
    """Doc line -> what it should say. Keyed by a regex that finds the line."""
    return {
        r"^Last verified: .*$": (
            "Last verified: %s. Unit tests %d/%d; legacy eval %d/%d; MVP eval %d/%d; "
            "real Scanpy/Squidpy backend checks passed; import-linter %d/%d. "
            "(Counts derived by `scripts/check_doc_numbers.py`.)"
            % (
                date.today().isoformat(),
                counts["tests"], counts["tests"],
                counts["legacy_cases"], counts["legacy_cases"],
                counts["mvp_cases"], counts["mvp_cases"],
                counts["contracts"], counts["contracts"],
            )
        ),
        r"^plannable and \d+ are hidden, so a model cannot select a tool that does nothing\.$": (
            "plannable and %d are hidden, so a model cannot select a tool that does nothing."
            % counts["hidden"]
        ),
        r"^stays honest even if a caller forgets to set the field\. `list_plannable\(\)` and$": (
            "stays honest even if a caller forgets to set the field. `list_plannable()` and"
        ),
        r"^`to_anthropic_tools\(\)` exclude them by default: of \d+ registered tools, \d+ are$": (
            "`to_anthropic_tools()` exclude them by default: of %d registered tools, %d are"
            % (counts["registered"], counts["plannable"])
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check or refresh the counts in docs/.")
    parser.add_argument("--check", action="store_true", help="Exit non-zero when a doc has drifted.")
    parser.add_argument("--write", action="store_true", help="Rewrite the doc lines in place.")
    args = parser.parse_args()

    counts = measure()
    print("measured: %s" % ", ".join("%s=%s" % item for item in sorted(counts.items())))

    text = ARCHITECTURE.read_text(encoding="utf-8")
    lines = text.splitlines()
    drifted = []
    for pattern, wanted in expected_lines(counts).items():
        matcher = re.compile(pattern)
        index = next((i for i, line in enumerate(lines) if matcher.match(line)), None)
        if index is None:
            drifted.append("no line matching %s" % pattern)
            continue
        if lines[index] != wanted:
            drifted.append("%s:%d\n  is:     %s\n  should: %s" % (ARCHITECTURE.name, index + 1, lines[index], wanted))
            lines[index] = wanted

    if not drifted:
        print("docs match the code.")
        return
    for item in drifted:
        print(item)
    if args.write:
        ARCHITECTURE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("rewrote %s" % ARCHITECTURE)
        return
    if args.check:
        raise SystemExit("docs have drifted; run `python scripts/check_doc_numbers.py --write`")


if __name__ == "__main__":
    main()
