"""Stage 4 - Template extraction (the "questions").

Reads the marketplace upload template. Every column is one question to
answer for every product row. Columns the profile does not know (e.g. image
URLs) are reported as out of scope and left blank, never guessed.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl

from .common import job_paths, log_event, write_json


def read_template(path: Path, profile: dict) -> dict:
    tpl = profile["template"]
    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        ws = wb[tpl["sheet"]]
        columns = []
        for col in range(1, ws.max_column + 1):
            key = ws.cell(row=tpl["key_row"], column=col).value
            if not key:
                continue
            label = ws.cell(row=tpl["label_row"], column=col).value or key
            columns.append({"col": col, "key": str(key).strip(), "label": str(label).strip()})
        sku_col = next(c["col"] for c in columns if c["key"] == tpl["sku_key"])
        rows = []
        for r in range(tpl["first_data_row"], ws.max_row + 1):
            sku = ws.cell(row=r, column=sku_col).value
            if sku and str(sku).strip():
                rows.append({"sku": str(sku).strip(), "row": r})
    finally:
        wb.close()
    return {"file": path.name, "sheet": tpl["sheet"], "columns": columns, "rows": rows}


def field_list(template: dict, profile: dict) -> list[dict]:
    fields = []
    for c in template["columns"]:
        if c["key"] == profile["template"]["sku_key"]:
            continue
        spec = profile["_fields_by_key"].get(c["key"])
        if spec is None:
            fields.append({"key": c["key"], "label": c["label"], "kind": "unmapped", "col": c["col"]})
        else:
            fields.append({**spec, "label": spec.get("label", c["label"]), "col": c["col"]})
    return fields


def extract_template(job_id: str, profile: dict, manifest: dict) -> tuple[dict, list[dict]]:
    paths = job_paths(job_id)
    tfile = next(f for f in manifest["files"] if f["role"] == "template")
    template = read_template(paths["input"] / tfile["name"], profile)
    template["sha256"] = tfile["sha256"]
    fields = field_list(template, profile)
    write_json(paths["work"] / "template.json", template)
    write_json(paths["work"] / "fields.json", fields)
    unmapped = [f["key"] for f in fields if f["kind"] == "unmapped"]
    log_event(job_id, "template", "DONE", fields=len(fields), sku_rows=len(template["rows"]), unmapped=unmapped)
    return template, fields
