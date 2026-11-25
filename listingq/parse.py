"""Stages 2-3 - Parsing and scoping.

Turns every supplier file into small "evidence" records. Each record is one
spreadsheet cell or one sentence/line of a catalogue, with an ID (E001...),
its exact location, and its *scope*:

- SKU     : about one product (e.g. NW-BTL-750-BLK)
- FAMILY  : about a range, written in the catalogue as NW-BTL-*
- GLOBAL  : about the company (manufacturer address, consumer care)

Scope is how retrieval works in the MVP: a product only ever sees its own
evidence plus its family and global evidence. No vector database is needed for this.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import openpyxl

from .common import job_paths, log_event, write_jsonl

LABEL_LINE = re.compile(r"^[A-Z][A-Za-z ()/&.'-]{1,40}:\s")
SENTENCE_END = re.compile(r"[.:;!?)]$")
FAMILY_RX = re.compile(r"\b([A-Z]{2,}(?:-[A-Z0-9]+)*)-\*")


# --------------------------------------------------------------------------
# Supplier sheets (xlsx / csv)
# --------------------------------------------------------------------------


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _sheet_tables(path: Path):
    """Yield (sheet_name, rows) for each sheet of an xlsx or the single csv table."""
    if path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as fh:
            yield path.stem, [list(r) for r in csv.reader(fh)]
        return
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            yield ws.title, [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _find_header(rows: list[list]) -> int | None:
    for i, row in enumerate(rows[:15]):
        texts = [c for c in row if isinstance(c, str) and c.strip()]
        if len(texts) >= 3:
            return i
    return None


def _sku_column(header: list, patterns: list[str]) -> int | None:
    for col, name in enumerate(header):
        name = _cell_text(name).lower()
        if any(re.search(p, name) for p in patterns):
            return col
    return None


def parse_supplier_sheet(path: Path, file_sha: str, profile: dict, start_id: int) -> tuple[list[dict], list[str]]:
    evidence: list[dict] = []
    skus: list[str] = []
    patterns = profile["supplier_sheet"]["sku_header_patterns"]
    n = start_id
    for sheet, rows in _sheet_tables(path):
        h = _find_header(rows)
        if h is None:
            continue
        header = [_cell_text(c) for c in rows[h]]
        sku_col = _sku_column(header, patterns)
        if sku_col is None:
            continue
        for r_idx in range(h + 1, len(rows)):
            row = rows[r_idx]
            sku = _cell_text(row[sku_col]) if sku_col < len(row) else ""
            if not sku:
                continue
            if sku not in skus:
                skus.append(sku)
            for c_idx, cell in enumerate(row):
                value = _cell_text(cell)
                if c_idx == sku_col or not value:
                    continue
                label = header[c_idx] if c_idx < len(header) and header[c_idx] else f"Column {c_idx + 1}"
                n += 1
                evidence.append({
                    "id": f"E{n:03d}",
                    "scope": "SKU",
                    "sku": sku,
                    "source_type": "supplier_sheet",
                    "file": path.name,
                    "file_sha256": file_sha,
                    "loc": f"{sheet}!R{r_idx + 1}C{c_idx + 1} ({label})",
                    "text": f"{label}: {value}",
                })
    return evidence, skus


# --------------------------------------------------------------------------
# Catalogues (pdf / docx / md / txt)
# --------------------------------------------------------------------------


def _raw_lines(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            for pno, page in enumerate(pdf.pages, start=1):
                for line in (page.extract_text() or "").splitlines():
                    yield pno, line.strip()
    elif suffix == ".docx":
        import docx

        for para in docx.Document(str(path)).paragraphs:
            yield 1, para.text.strip()
    else:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                yield 1, line.strip().lstrip("#").strip()


def _is_heading(line: str, sku_codes: list[str], global_rx: list[re.Pattern]) -> bool:
    low = line.lower()
    return (
        any(code.lower() in low for code in sku_codes)
        or bool(FAMILY_RX.search(line))
        or any(rx.search(line) for rx in global_rx)
    )


def _merge_wrapped(lines, sku_codes, global_rx):
    """Join a sentence that the PDF wrapped over two lines back into one."""
    merged: list[list] = []  # [page, line_no, text, is_heading]
    for page, text in lines:
        if not text:
            continue
        heading = _is_heading(text, sku_codes, global_rx)
        if (
            merged
            and merged[-1][0] == page
            and not merged[-1][3]
            and not heading
            and not LABEL_LINE.match(text)
            and not SENTENCE_END.search(merged[-1][2])
        ):
            merged[-1][2] += " " + text
            continue
        line_no = sum(1 for m in merged if m[0] == page) + 1
        merged.append([page, line_no, text, heading])
    return merged


def parse_catalogue(path: Path, file_sha: str, profile: dict, sku_codes: list[str], start_id: int) -> list[dict]:
    global_rx = [re.compile(p, re.I) for p in profile["catalogue"]["global_section_patterns"]]
    evidence: list[dict] = []
    scope: dict = {"scope": "GLOBAL"}
    n = start_id
    for page, line_no, text, _heading in _merge_wrapped(_raw_lines(path), sku_codes, global_rx):
        codes = [c for c in sku_codes if c.lower() in text.lower()]
        families = FAMILY_RX.findall(text)
        if codes:
            scope = {"scope": "SKU", "sku": codes[0]} if len(codes) == 1 else {"scope": "MULTI", "skus": codes}
        elif families:
            scope = {"scope": "FAMILY", "families": families}
        elif any(rx.search(text) for rx in global_rx):
            scope = {"scope": "GLOBAL"}
        n += 1
        loc = f"p.{page} line {line_no}" if path.suffix.lower() == ".pdf" else f"para {line_no}"
        evidence.append({
            "id": f"E{n:03d}",
            **scope,
            "source_type": "catalogue",
            "file": path.name,
            "file_sha256": file_sha,
            "loc": loc,
            "text": text,
        })
    return evidence


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def parse_inputs(job_id: str, profile: dict, manifest: dict) -> tuple[list[dict], list[str]]:
    paths = job_paths(job_id)
    evidence: list[dict] = []
    supplier_skus: list[str] = []
    # Supplier sheets first: they tell us which product codes exist.
    for f in manifest["files"]:
        if f["role"] == "supplier_sheet":
            ev, skus = parse_supplier_sheet(paths["input"] / f["name"], f["sha256"], profile, len(evidence))
            evidence += ev
            supplier_skus += [s for s in skus if s not in supplier_skus]
    return evidence, supplier_skus


def parse_catalogues(job_id: str, profile: dict, manifest: dict, sku_codes: list[str], evidence: list[dict]) -> list[dict]:
    paths = job_paths(job_id)
    for f in manifest["files"]:
        if f["role"] == "catalogue":
            evidence += parse_catalogue(paths["input"] / f["name"], f["sha256"], profile, sku_codes, len(evidence))
    write_jsonl(paths["work"] / "evidence.jsonl", evidence)
    by_scope: dict[str, int] = {}
    for e in evidence:
        by_scope[e["scope"]] = by_scope.get(e["scope"], 0) + 1
    log_event(job_id, "parse", "DONE", evidence=len(evidence), by_scope=by_scope)
    return evidence
