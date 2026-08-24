"""Validate a mission directory locally, before pushing to GitHub.

Usage:
    python -m tools.validate_mission path/to/active/OP-001-blackout [more dirs...]

Runs the exact same validation as the Discord `/mission validate` command
(app.missions.validation) — there is one validation implementation, not two.
Exit code 0 = all missions valid, 1 = at least one error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.missions.validation import MissionFiles, ValidationReport, validate_mission_files


def load_mission_files(directory: Path) -> MissionFiles:
    def read_optional(filename: str) -> str | None:
        path = directory / filename
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    # Report paths the same way the bot sees them (e.g. "active/op-001-x")
    # so directory/status cross-checks behave identically.
    parent = directory.resolve().parent.name
    display = f"{parent}/{directory.resolve().name}" if parent in ("active", "archived") else directory.resolve().name

    return MissionFiles(
        directory=display,
        mission_json=read_optional("mission.json"),
        brief_md=read_optional("brief.md"),
        objectives_json=read_optional("objectives.json"),
        slots_json=read_optional("slots.json"),
    )


def print_report(report: ValidationReport) -> None:
    if report.metadata is not None:
        print(f"\n{report.metadata.id} — {report.metadata.name} (v{report.metadata.version})")
    else:
        print(f"\n{report.directory}")
    print("VALID" if report.is_valid else "INVALID")
    for name in report.passed:
        print(f"  ✓ {name}")
    for error in report.errors:
        print(f"  ✗ {error}")
    for warning in report.warnings:
        print(f"  ⚠ {warning}")


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.validate_mission",
        description="Validate mission directories (same checks as /mission validate).",
    )
    parser.add_argument("directories", nargs="+", type=Path, help="mission directory path(s)")
    args = parser.parse_args(argv)

    exit_code = 0
    for directory in args.directories:
        if not directory.is_dir():
            print(f"\n{directory}\n  ✗ not a directory")
            exit_code = 1
            continue
        report = validate_mission_files(load_mission_files(directory))
        print_report(report)
        if not report.is_valid:
            exit_code = 1
    return exit_code


def main() -> None:
    # Windows consoles may default to a legacy codepage; keep ✓/✗ printable.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
