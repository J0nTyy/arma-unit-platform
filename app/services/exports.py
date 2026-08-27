"""Tabular file exports (CSV / XLSX).

ExportService knows how to write tables to files; it knows nothing about
what the tables contain (datasets live in DataExportService). Two modes,
matching the canonical-vs-generated rule in data/README.md:

- **Dated exports** — staff-triggered, written once, never silently
  overwritten: ``members_2026-08-28.csv`` (collisions get ``_2``, ``_3``…).
- **Snapshots** — regularly regenerated "latest state" files that are
  overwritten in place: ``exports/latest/members.csv``.

CSV files are written as UTF-8 with BOM so Excel opens them correctly
without an import wizard; XLSX via openpyxl.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

Rows = Sequence[Sequence[Any]]


class ExportService:
    def dated_export(
        self,
        directory: Path,
        name: str,
        headers: Sequence[str],
        rows: Rows,
        *,
        formats: Sequence[str] = ("csv",),
    ) -> list[Path]:
        """Write a dated, never-overwritten export. Returns created paths."""
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        written: list[Path] = []
        for fmt in formats:
            path = self._free_path(directory, f"{name}_{stamp}", fmt)
            self._write(path, fmt, headers, rows)
            written.append(path)
        return written

    def snapshot(
        self, directory: Path, name: str, headers: Sequence[str], rows: Rows
    ) -> Path:
        """Write/overwrite a 'latest state' CSV snapshot (generated file)."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.csv"
        self._write(path, "csv", headers, rows)
        return path

    @staticmethod
    def _free_path(directory: Path, stem: str, fmt: str) -> Path:
        """First non-existing path: stem.fmt, stem_2.fmt, stem_3.fmt, ..."""
        path = directory / f"{stem}.{fmt}"
        counter = 2
        while path.exists():
            path = directory / f"{stem}_{counter}.{fmt}"
            counter += 1
        return path

    @staticmethod
    def _write(path: Path, fmt: str, headers: Sequence[str], rows: Rows) -> None:
        if fmt == "csv":
            # utf-8-sig: Excel needs the BOM to detect UTF-8 on double-click.
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(headers)
                writer.writerows(rows)
        elif fmt == "xlsx":
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(list(headers))
            for cell in sheet[1]:
                cell.font = Font(bold=True)
            sheet.freeze_panes = "A2"
            for row in rows:
                sheet.append(list(row))
            for index, header in enumerate(headers, start=1):
                width = max(
                    len(str(header)),
                    *(len(str(row[index - 1])) for row in rows) if rows else (0,),
                )
                sheet.column_dimensions[get_column_letter(index)].width = min(width + 2, 40)
            workbook.save(path)
        else:
            raise ValueError(f"unsupported export format: {fmt}")
