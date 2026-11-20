"""Exportación de tablas y reportes a Excel (.xlsx)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

MONEY_FMT = '"$" #,##0;[Red]-"$" #,##0'
QTY_FMT = "#,##0.##"
PCT_FMT = "0.0%"


@dataclass
class Sheet:
    title: str
    headers: list[str]
    rows: list[list]
    kinds: list[str] = field(default_factory=list)  # por columna: text|money|number|qty|pct|date|datetime
    subtitle: str = ""


def export_xlsx(path: str, sheets: list[Sheet], business: str = "") -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    header_fill = PatternFill("solid", fgColor="6C4CF1")
    for sheet in sheets:
        ws = wb.create_sheet(_safe_title(sheet.title))
        r = 1
        if business or sheet.subtitle:
            ws.cell(r, 1, f"{business} · {sheet.title}".strip(" ·")).font = Font(bold=True, size=13)
            r += 1
            if sheet.subtitle:
                ws.cell(r, 1, sheet.subtitle).font = Font(italic=True, color="666666")
                r += 1
            r += 1
        for c, h in enumerate(sheet.headers, 1):
            cell = ws.cell(r, c, h)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = Alignment(vertical="center")
        header_row = r
        widths = [len(str(h)) + 2 for h in sheet.headers]
        for row in sheet.rows:
            r += 1
            for c, value in enumerate(row, 1):
                if isinstance(value, datetime):
                    value = value.replace(tzinfo=None)
                cell = ws.cell(r, c, value)
                kind = sheet.kinds[c - 1] if c - 1 < len(sheet.kinds) else "text"
                if kind == "money":
                    cell.number_format = MONEY_FMT
                elif kind in ("number", "qty"):
                    cell.number_format = QTY_FMT
                elif kind == "pct":
                    cell.number_format = PCT_FMT
                elif kind == "date" or isinstance(value, date) and not isinstance(value, datetime):
                    cell.number_format = "dd/mm/yyyy"
                elif kind == "datetime" or isinstance(value, datetime):
                    cell.number_format = "dd/mm/yyyy hh:mm"
                widths[c - 1] = min(60, max(widths[c - 1], len(_display(value)) + 2))
        for c, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(c)].width = max(10, w)
        ws.freeze_panes = ws.cell(header_row + 1, 1)
        if sheet.rows:
            ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(sheet.headers))}{r}"
    if not wb.worksheets:
        wb.create_sheet("Vacío")
    wb.save(path)


def _display(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:,.0f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _safe_title(title: str) -> str:
    for ch in '[]:*?/\\':
        title = title.replace(ch, "-")
    return title[:31] or "Hoja"
