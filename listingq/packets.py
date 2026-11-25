"""Stages 5-7 - Enrichment, retrieval and conflict detection -> one packet per product.

A packet is everything Claude Code needs to fill one product row:
the questions (fields + rules), the evidence it is allowed to use, any
conflicts between sources, and approved examples from earlier jobs.
"""
from __future__ import annotations

from .common import job_paths, log_event, quantities, read_jsonl, root, stable_hash, write_json


def in_scope(ev: dict, sku: str) -> bool:
    scope = ev["scope"]
    if scope == "GLOBAL":
        return True
    if scope == "SKU":
        return ev.get("sku") == sku
    if scope == "MULTI":
        return sku in ev.get("skus", [])
    if scope == "FAMILY":
        return any(sku.startswith(f + "-") for f in ev.get("families", []))
    return False


def detect_conflicts(sku_evidence: list[dict], fields: list[dict]) -> list[dict]:
    """Two source files that state different values for the same quantity = conflict.

    Only product-level (SKU) evidence is compared. A file that states several
    values (e.g. '3 x 400 ml (1200 ml total)') agrees if any value overlaps.
    """
    conflicts = []
    for f in fields:
        kind = f.get("conflict_check")
        if not kind:
            continue
        per_file: dict[str, dict] = {}
        for ev in sku_evidence:
            vals = {v for k, v in quantities(ev["text"]) if k == kind}
            if vals:
                slot = per_file.setdefault(ev["file"], {"values": set(), "evidence": []})
                slot["values"] |= vals
                slot["evidence"].append(ev["id"])
        if len(per_file) < 2:
            continue
        common = set.intersection(*(s["values"] for s in per_file.values()))
        if not common:
            conflicts.append({
                "field": f["key"],
                "kind": kind,
                "sources": [
                    {"file": name, "values": sorted(s["values"]), "evidence": s["evidence"]}
                    for name, s in per_file.items()
                ],
            })
    return conflicts


def _field_brief(f: dict) -> dict:
    keep = ("key", "label", "kind", "type", "quantity", "required", "required_if", "critical", "allow_na",
            "allowed", "rules", "conflict_check", "contradiction_check", "hint", "law")
    return {k: f[k] for k in keep if k in f}


def _examples(sku: str, job_id: str, limit: int = 2) -> list[dict]:
    """Approved listings from earlier jobs (the flywheel), same family first. Never this job's own."""
    rows = [r for r in read_jsonl(root() / "kb" / "approved_listings.jsonl") if r.get("job_id") != job_id]
    family = "-".join(sku.split("-")[:2])
    rows.sort(key=lambda r: r.get("approved_at", ""), reverse=True)          # newest first
    rows.sort(key=lambda r: not r.get("sku", "").startswith(family))          # same family first (stable)
    return rows[:limit]


def skeleton(fields: list[dict]) -> dict:
    out = {}
    for f in fields:
        if f["kind"] == "unmapped":
            continue
        entry = {"value": None, "basis": "", "evidence": [], "note": ""}
        if f["kind"] == "copy":
            entry["claims"] = []
        out[f["key"]] = entry
    return out


def build_packets(job_id: str, evidence: list[dict], template: dict, fields: list[dict],
                  supplier_skus: list[str]) -> list[str]:
    paths = job_paths(job_id)
    skus = [r["sku"] for r in template["rows"]] or supplier_skus
    not_requested = [s for s in supplier_skus if s not in skus]
    answerable = [f for f in fields if f["kind"] != "unmapped"]
    for sku in skus:
        ev = [e for e in evidence if in_scope(e, sku)]
        sku_only = [e for e in ev if e["scope"] in ("SKU", "MULTI")]
        packet = {
            "job_id": job_id,
            "sku": sku,
            "answer_file": f"jobs/{job_id}/work/answers/{sku}.json",
            "brand_guide": "kb/brand_guide.md",
            "fields": [_field_brief(f) for f in answerable],
            "evidence": [
                {"id": e["id"], "scope": e["scope"], "source": f"{e['file']} > {e['loc']}", "text": e["text"]}
                for e in ev
            ],
            "conflicts": detect_conflicts(sku_only, answerable),
            "has_product_evidence": bool(sku_only),
            "examples": _examples(sku, job_id),
        }
        packet["packet_hash"] = stable_hash({"evidence": packet["evidence"], "fields": packet["fields"]})
        packet["answer_skeleton"] = {
            "sku": sku,
            "packet_hash": packet["packet_hash"],
            "generated_by": "claude-code",
            "fields": skeleton(answerable),
        }
        write_json(paths["packets"] / f"{sku}.json", packet)
    log_event(job_id, "packets", "DONE", skus=len(skus), not_requested=not_requested)
    return skus
