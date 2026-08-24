"""Regenerate the JSON Schema files shipped in the missions repository.

Usage:
    python -m tools.export_mission_schema [output_dir]

The schemas are generated from the pydantic models in app/missions/models.py
(the single source of truth) and give mission makers editor IntelliSense via
the missions repo's .vscode/settings.json. Re-run this whenever the models
change, and commit the result to the missions repository.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.missions.models import MissionMetadata, MissionObjectives, MissionSlots

DEFAULT_OUTPUT = Path("missions-repo-template/schema")


def export(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    schemas = {
        "mission.schema.json": MissionMetadata,
        "objectives.schema.json": MissionObjectives,
        "slots.schema.json": MissionSlots,
    }
    written = []
    for filename, model in schemas.items():
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        path = output_dir / filename
        path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main() -> None:
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    for path in export(output_dir):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
