"""Stage 11 - Human review.

build_review_workbook  writes output/review.xlsx: one row per field that needs a
                       person (NEEDS_REVIEW or NOT_FOUND), with the proposed
                       value, the reason and the quoted evidence. A second
                       sheet lists every field so a reviewer can spot-check.
apply_review           reads the reviewer's decisions (APPROVE / EDIT / REJECT)
                       and stores them in work/decisions.json with the
                       reviewer's name and a hash of the value they saw.
                       If the AI answer changes after review, the old
                       decision no longer applies.
"""
from __future__ import annotations

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from .common import job_paths, log_event, now_iso, read_json, stable_hash, write_json
from .profile import load_profile
from .validate import rules_check

FILLS = {
    "AUTO_APPROVED": PatternFill("solid", fgColor="E2F0D9"),
    "NEEDS_REVIEW": PatternFill("solid", fgColor="FFF2CC"),
    "NOT_FOUND": PatternFill("solid", fgColor="F8CBAD"),
    "NOT_APPLICABLE": PatternFill("solid", fgColor="EDEDED"),
}
HEAD_FILL = PatternFill("solid", fgColor="1F3864")
COLUMNS = ["SKU", "Field", "Proposed value", "Status", "Confidence", "Why it needs you", "Evidence (quoted)",
           "Decision", "Final value (for EDIT)", "Reviewer note"]
WIDTHS = [18, 22, 48, 16, 11, 48, 60, 12, 40, 30]


def _quote(packet: dict, ids: list[str], limit: int = 320) -> str:
    idx = {e["id"]: e for e in packet["evidence"]}
    parts = [f"[{i}] {idx[i]['text']} ({idx[i]['source']})" for i in ids if i in idx]
    text = "\n".join(parts)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _write_sheet(ws, rows: list[list], status_col: int = 4) -> None:
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for row in rows:
        ws.append(row)
    for r in ws.iter_rows(min_row=2):
        for cell in r:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        status = r[status_col - 1].value
        if status in FILLS:
            r[status_col - 1].fill = FILLS[status]
    for i, width in enumerate(WIDTHS, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width
    ws.freeze_panes = "C2"


def _previous_decisions(path) -> dict:
    """Decisions already typed into an existing review.xlsx, keyed by (sku, field label)."""
    if not path.exists():
        return {}
    try:
        ws = load_workbook(path, data_only=True)["Review"]
    except Exception:  # noqa: BLE001 - an unreadable old sheet is simply not carried over
        return {}
    kept = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        row = (list(row) + [None] * 10)[:10]
        if row[0] and row[7]:
            kept[(row[0], row[1])] = {"proposed": row[2] or "", "decision": row[7], "final": row[8], "note": row[9]}
    return kept


def build_review_workbook(job_id: str) -> str:
    paths = job_paths(job_id)
    check = read_json(paths["work"] / "check.json")
    previous = _previous_decisions(paths["output"] / "review.xlsx")
    carried = 0
    review_rows, all_rows = [], []
    for sku, res in check["skus"].items():
        packet = read_json(paths["packets"] / f"{sku}.json")
        for key, f in res["fields"].items():
            row = [sku, f["label"], "" if f["value"] is None else str(f["value"]), f["status"],
                   f["score"], "\n".join(f["issues"]), _quote(packet, f["evidence"]), "", "", ""]
            all_rows.append(row)
            if f["status"] in ("NEEDS_REVIEW", "NOT_FOUND"):
                old = previous.get((sku, f["label"]))
                if old and old["proposed"] == row[2]:  # same proposal as before: keep the reviewer's work
                    row[7], row[8], row[9] = old["decision"], old["final"], old["note"]
                    carried += 1
                review_rows.append(row)
    wb = Workbook()
    ws = wb.active
    ws.title = "Review"
    _write_sheet(ws, review_rows)
    dv = DataValidation(type="list", formula1='"APPROVE,EDIT,REJECT"', allow_blank=True)
    ws.add_data_validation(dv)
    if review_rows:
        dv.add(f"H2:H{len(review_rows) + 1}")
    ws2 = wb.create_sheet("All fields")
    _write_sheet(ws2, all_rows)
    guide = wb.create_sheet("How to review")
    for line in [
        "How to review (ListingQ)",
        "1. Work down the 'Review' sheet. Read 'Why it needs you' and the quoted evidence.",
        "2. Decision: APPROVE keeps the proposed value. EDIT uses your 'Final value'. REJECT leaves the cell blank.",
        "3. For NOT_FOUND rows you can type a value you have confirmed (EDIT). Say where it came from in 'Reviewer note'.",
        "4. Save the file, then run: python3 -m listingq apply-review <job> --reviewer \"Your Name\"",
        "5. Rows on 'All fields' are for spot-checks only; decisions there are ignored.",
    ]:
        guide.append([line])
    guide.column_dimensions["A"].width = 110
    out = paths["output"] / "review.xlsx"
    wb.save(out)
    log_event(job_id, "review_sheet", "DONE", rows=len(review_rows), decisions_carried_over=carried)
    return str(out)


def apply_review(job_id: str, reviewer: str) -> dict:
    paths = job_paths(job_id)
    check = read_json(paths["work"] / "check.json")
    profile = load_profile(check["profile_id"])
    wb = load_workbook(paths["output"] / "review.xlsx", data_only=True)
    ws = wb["Review"]
    label_to_key = {}
    for sku, res in check["skus"].items():
        for key, f in res["fields"].items():
            label_to_key[(sku, f["label"])] = key

    decisions, problems = [], []
    for row in ws.iter_rows(min_row=2, values_only=True):
        sku, label, proposed, status, _score, _why, _ev, decision, final, note = (list(row) + [None] * 10)[:10]
        if not sku or not decision:
            continue
        decision = str(decision).strip().upper()
        key = label_to_key.get((sku, label))
        if key is None or decision not in ("APPROVE", "EDIT", "REJECT"):
            problems.append(f"{sku} / {label}: unreadable decision '{decision}'")
            continue
        f = check["skus"][sku]["fields"][key]
        if decision == "APPROVE" and f["status"] == "NOT_FOUND":
            problems.append(f"{sku} / {label}: cannot APPROVE an empty value; use EDIT with a confirmed value")
            continue
        entry = {
            "sku": sku, "key": key, "decision": decision, "reviewer": reviewer, "reviewed_at": now_iso(),
            "answer_snapshot_hash": f["answer_hash"], "proposed_value": f["value"], "note": note or "",
        }
        if decision == "EDIT":
            if final in (None, ""):
                problems.append(f"{sku} / {label}: EDIT needs a final value")
                continue
            values = {k: v["value"] for k, v in check["skus"][sku]["fields"].items()}
            field = next(x for x in read_json(paths["packets"] / f"{sku}.json")["fields"] if x["key"] == key)
            _s, rule_issues = rules_check(field, final, profile, values)
            if rule_issues:
                problems.append(f"{sku} / {label}: edited value breaks a rule: {'; '.join(rule_issues)}")
                continue
            entry["final_value"] = final
        decisions.append(entry)

    result = {"job_id": job_id, "applied_at": now_iso(), "reviewer": reviewer, "decisions": decisions,
              "problems": problems, "decisions_hash": stable_hash(decisions)}
    write_json(paths["work"] / "decisions.json", result)
    log_event(job_id, "review", "APPLIED", reviewer=reviewer, decisions=len(decisions), problems=len(problems))
    return result
