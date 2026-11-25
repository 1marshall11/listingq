"""Stages 12-13 - Write-back, lineage, report and the flywheel.

- Copies the marketplace template and writes only approved values into it.
  Pending and not-found cells stay blank, are shaded, and carry a comment
  saying why. Nothing unapproved ever reaches the upload file.
- Writes output/lineage.jsonl: one line per cell, from source file hash and
  evidence line to the final cell address and reviewer.
- Writes output/run_report.md.
- Adds fully approved products to kb/approved_listings.jsonl, so the next job
  has better examples (the data flywheel).
"""
from __future__ import annotations

import shutil

from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import PatternFill

from .common import job_paths, log_event, now_iso, read_json, read_jsonl, root, write_jsonl

WRITE_STATUSES = {"AUTO_APPROVED", "HUMAN_APPROVED", "HUMAN_EDITED"}
PENDING_FILL = PatternFill("solid", fgColor="FFF2CC")
MISSING_FILL = PatternFill("solid", fgColor="F8CBAD")
COPY_KEYS = ("item_name", "bullet_point1", "bullet_point2", "bullet_point3", "bullet_point4",
             "bullet_point5", "product_description", "generic_keywords")


def _final_status(f: dict, decision: dict | None) -> tuple[str, object, str]:
    """Combine the AI status with the reviewer's decision. Returns (status, value, approved_by)."""
    if decision and decision["answer_snapshot_hash"] != f["answer_hash"]:
        decision = None  # the AI answer changed after review: the old decision no longer applies
    if decision:
        if decision["decision"] == "APPROVE":
            return "HUMAN_APPROVED", f["value"], decision["reviewer"]
        if decision["decision"] == "EDIT":
            return "HUMAN_EDITED", decision["final_value"], decision["reviewer"]
        return "HUMAN_REJECTED", None, decision["reviewer"]
    if f["status"] == "AUTO_APPROVED":
        return "AUTO_APPROVED", f["value"], "auto (all checks passed)"
    if f["status"] == "NEEDS_REVIEW":
        return "PENDING_REVIEW", None, ""
    return f["status"], None, ""  # NOT_FOUND / NOT_APPLICABLE


def deliver(job_id: str, flywheel: bool = True) -> dict:
    paths = job_paths(job_id)
    manifest = read_json(paths["work"] / "manifest.json")
    template = read_json(paths["work"] / "template.json")
    check = read_json(paths["work"] / "check.json")
    dec_path = paths["work"] / "decisions.json"
    decisions = read_json(dec_path)["decisions"] if dec_path.exists() else []
    by_cell = {(d["sku"], d["key"]): d for d in decisions}
    files_by_name = {f["name"]: f for f in manifest["files"]}

    src = paths["input"] / template["file"]
    out_name = src.stem + "_filled" + src.suffix
    out_path = paths["output"] / out_name
    shutil.copyfile(src, out_path)
    wb = load_workbook(out_path)
    ws = wb[template["sheet"]]
    col_of = {c["key"]: c["col"] for c in template["columns"]}
    row_of = {r["sku"]: r["row"] for r in template["rows"]}

    lineage, sku_summary = [], []
    for sku, res in check["skus"].items():
        packet = read_json(paths["packets"] / f"{sku}.json")
        ev_index = {e["id"]: e for e in packet["evidence"]}
        statuses, missing_required, final_values = {}, [], {}
        for key, f in res["fields"].items():
            status, value, approved_by = _final_status(f, by_cell.get((sku, key)))
            statuses[status] = statuses.get(status, 0) + 1
            cell = ws.cell(row=row_of[sku], column=col_of[key])
            if status in WRITE_STATUSES:
                cell.value = value
                final_values[key] = value
            else:
                cell.value = None
                if status in ("PENDING_REVIEW", "NOT_FOUND", "HUMAN_REJECTED"):
                    cell.fill = PENDING_FILL if status == "PENDING_REVIEW" else MISSING_FILL
                    reason = "; ".join(f["issues"])[:400] or status
                    cell.comment = Comment(f"ListingQ {status}: {reason}", "ListingQ")
                if f["required"]:
                    missing_required.append(key)
            src_lines = []
            for eid in f["evidence"]:
                e = ev_index.get(eid)
                if e:
                    file_name = e["source"].split(" > ")[0]
                    src_lines.append({"id": eid, "source": e["source"], "text": e["text"],
                                      "file_sha256": files_by_name.get(file_name, {}).get("sha256")})
            lineage.append({
                "job_id": job_id, "sku": sku, "field": key, "final_status": status,
                "value_written": value if status in WRITE_STATUSES else None,
                "ai_value": f["value"], "basis": f["basis"], "confidence": f["score"], "signals": f["signals"],
                "issues": f["issues"], "evidence": src_lines, "packet_hash": res["packet_hash"],
                "answer_hash": f["answer_hash"], "check_run": check["run_no"], "approved_by": approved_by,
                "review": by_cell.get((sku, key)),
                "delivered_to": f"{out_name}!{template['sheet']}!{cell.coordinate}",
            })
        ready = not missing_required
        sku_summary.append({"sku": sku, "ready": ready, "missing_required": missing_required,
                            "statuses": statuses, "values": final_values})
    wb.save(out_path)
    write_jsonl(paths["output"] / "lineage.jsonl", lineage)

    added = _flywheel(job_id, sku_summary) if flywheel else 0
    report = _report(job_id, manifest, template, check, decisions, sku_summary, out_name, added)
    (paths["output"] / "run_report.md").write_text(report, encoding="utf-8")
    ready = sum(1 for s in sku_summary if s["ready"])
    log_event(job_id, "deliver", "DONE", ready=ready, total=len(sku_summary), flywheel_added=added)
    return {"output": str(out_path), "ready": ready, "total": len(sku_summary), "skus": sku_summary}


def _flywheel(job_id: str, sku_summary: list[dict]) -> int:
    path = root() / "kb" / "approved_listings.jsonl"
    rows = read_jsonl(path)
    seen = {(r.get("sku"), r.get("job_id")) for r in rows}
    added = 0
    for s in sku_summary:
        if not s["ready"] or (s["sku"], job_id) in seen:
            continue
        entry = {"sku": s["sku"], "job_id": job_id, "approved_at": now_iso()[:10]}
        entry.update({k: s["values"][k] for k in COPY_KEYS if k in s["values"]})
        rows.append(entry)
        added += 1
    if added:
        write_jsonl(path, rows)
    return added


def _report(job_id, manifest, template, check, decisions, sku_summary, out_name, added) -> str:
    totals: dict[str, int] = {}
    for s in sku_summary:
        for k, v in s["statuses"].items():
            totals[k] = totals.get(k, 0) + v
    cells = sum(totals.values()) - totals.get("NOT_APPLICABLE", 0)
    auto = totals.get("AUTO_APPROVED", 0)
    human = totals.get("HUMAN_APPROVED", 0) + totals.get("HUMAN_EDITED", 0)
    unmapped = [c["key"] for c in template["columns"] if c["key"] not in
                {k for r in check["skus"].values() for k in r["fields"]} | {"item_sku"}]
    lines = [
        f"# ListingQ run report - {job_id}",
        "",
        f"Generated {now_iso()} | profile `{check['profile_id']}` | check run {check['run_no']}",
        "",
        f"**{sum(1 for s in sku_summary if s['ready'])} of {len(sku_summary)} products are ready to upload.** "
        f"{auto} of {cells} applicable cells ({auto / max(cells, 1):.0%}) passed every check automatically, "
        f"and {human} more were approved or edited by a reviewer.",
        "",
        "## Products",
        "",
        "| SKU | Ready | Auto-approved | Reviewer-approved | Reviewer-rejected | Pending review | Not found | Not applicable | Missing required fields |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in sku_summary:
        st = s["statuses"]
        lines.append(
            f"| {s['sku']} | {'yes' if s['ready'] else 'NO'} | {st.get('AUTO_APPROVED', 0)} | "
            f"{st.get('HUMAN_APPROVED', 0) + st.get('HUMAN_EDITED', 0)} | {st.get('HUMAN_REJECTED', 0)} | "
            f"{st.get('PENDING_REVIEW', 0)} | {st.get('NOT_FOUND', 0)} | {st.get('NOT_APPLICABLE', 0)} | "
            f"{', '.join(s['missing_required']) or '-'} |"
        )
    lines += ["", "## What still needs a person", ""]
    pending = []
    for sku, res in check["skus"].items():
        decided = {d["key"] for d in decisions if d["sku"] == sku}
        for key, f in res["fields"].items():
            if f["status"] in ("NEEDS_REVIEW", "NOT_FOUND") and key not in decided:
                need = "required" if f["required"] else "optional"
                pending.append(f"- **{sku} / {f['label']}** ({f['status']}, {need}): {'; '.join(f['issues']) or 'no value'}")
    pending.sort(key=lambda line: ", optional)" in line)  # required gaps first
    lines += pending or ["- Nothing. Every field is approved, edited, rejected or not applicable."]
    lines += ["", "## Reviewer decisions", ""]
    lines += [f"- {d['sku']} / {d['key']}: {d['decision']} by {d['reviewer']}"
              + (f" -> `{d['final_value']}`" if d.get("final_value") is not None else "")
              + (f" ({d['note']})" if d.get("note") else "") for d in decisions] or ["- None yet."]
    lines += [
        "",
        "## Inputs (fingerprints)",
        "",
        "| File | Role | SHA-256 (first 16) |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {f['name']} | {f['role']} | `{f['sha256'][:16]}` |" for f in manifest["files"]]
    lines += [
        "",
        "## Notes",
        "",
        f"- Upload file: `output/{out_name}`. Shaded cells are blank on purpose; each has a comment with the reason.",
        f"- Template columns this profile does not handle (left blank): {', '.join(unmapped) or 'none'}.",
        f"- Approved listings added to the knowledge base this run: {added}.",
        "- Full trail for every cell: `output/lineage.jsonl`.",
        "",
    ]
    return "\n".join(lines)
