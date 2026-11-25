"""ListingQ tests. Run: python3 -m pytest -q

Each test works on a temporary copy of the project, so the real demo job is never touched.
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
from openpyxl import load_workbook

PROJECT = Path(__file__).resolve().parent.parent
JOB = "demo-001"


@pytest.fixture()
def project(tmp_path, monkeypatch):
    for d in ("config", "kb"):
        shutil.copytree(PROJECT / d, tmp_path / d)
    shutil.copytree(PROJECT / "jobs" / JOB / "input", tmp_path / "jobs" / JOB / "input")
    shutil.copytree(PROJECT / "jobs" / JOB / "work" / "answers", tmp_path / "jobs" / JOB / "work" / "answers")
    # keep the knowledge base to the seed example so tests do not depend on earlier runs
    seed = (PROJECT / "kb" / "approved_listings.jsonl").read_text(encoding="utf-8").splitlines()[0]
    (tmp_path / "kb" / "approved_listings.jsonl").write_text(seed + "\n", encoding="utf-8")
    monkeypatch.setenv("LISTINGQ_ROOT", str(tmp_path))
    from listingq.__main__ import main

    main(["prepare", JOB])
    return tmp_path


def _packet(root: Path, sku: str) -> dict:
    return json.loads((root / "jobs" / JOB / "work" / "packets" / f"{sku}.json").read_text())


def _answer(root: Path, sku: str) -> dict:
    return json.loads((root / "jobs" / JOB / "work" / "answers" / f"{sku}.json").read_text())


def _check_one(root: Path, sku: str, key: str, answer_field: dict, values: dict | None = None) -> dict:
    from listingq.profile import load_profile
    from listingq.validate import check_field

    packet = _packet(root, sku)
    fields = {f["key"]: f for f in packet["fields"]}
    ev_index = {e["id"]: e for e in packet["evidence"]}
    base_values = {k: v.get("value") for k, v in _answer(root, sku)["fields"].items()}
    base_values.update(values or {})
    return check_field(fields[key], answer_field, packet, ev_index, base_values, load_profile("amazon_in_home_kitchen"), False)


# --------------------------------------------------------------------------- helpers


def test_quantities_convert_units():
    from listingq.common import dims, quantities

    assert ("volume_ml", 1000.0) in quantities("Cap: 1 ltr")
    assert ("volume_ml", 1000.0) in quantities("Insulated bottle 1L blue")
    assert ("weight_g", 410.0) in quantities("Wt: 0.41 kg")
    assert ("money_inr", 1099.0) in quantities("MRP (Rs): 1,099")
    assert ("time_h", 24.0) in quantities("keeps drinks cold for up to 24 hours")
    assert quantities("MRP (Rs): TBC") == []
    assert dims("Dim (cm): 7.5 x 7.5 x 26.5") == [(7.5, 7.5, 26.5)]
    assert dims("75 x 75 x 265 mm") == [(7.5, 7.5, 26.5)]


# --------------------------------------------------------------------------- prepare


def test_prepare_scopes_and_conflicts(project):
    pink = _packet(project, "NW-BTL-500-PNK")
    assert [c["field"] for c in pink["conflicts"]] == ["capacity_ml"]
    board = _packet(project, "NW-CUT-BMB-01")
    texts = " ".join(e["text"] for e in board["evidence"])
    assert "SS 304" not in texts, "steel range lines must not reach the bamboo board"
    assert "LT-2291" not in texts, "bottle range lines must not reach the bamboo board"
    lunch = _packet(project, "NW-LBX-3C-SS")
    assert lunch["conflicts"] == [], "'3 x 400 ml (1200 ml total)' agrees with '1200 ml total'"
    assert any("MD-304-2026" in e["text"] for e in lunch["evidence"]), "steel family line reaches the lunch box"


# --------------------------------------------------------------------------- check


def test_demo_answers_check_as_expected(project):
    from listingq.validate import check_job

    check = check_job(JOB)
    assert check["totals"] == {"AUTO_APPROVED": 133, "NOT_APPLICABLE": 6, "NEEDS_REVIEW": 1, "NOT_FOUND": 4}
    assert check["skus"]["NW-BTL-500-PNK"]["fields"]["capacity_ml"]["status"] == "NEEDS_REVIEW"
    assert check["skus"]["NW-CUT-BMB-01"]["blocking_fields"] == ["mrp_inr"]
    assert check["skus"]["NW-JAR-SET4-GLS"]["blocking_fields"] == ["manufacturer_details"]


def test_title_rules_are_ai_fixable(project):
    bad = copy.deepcopy(_answer(project, "NW-BTL-750-BLK")["fields"]["item_name"])
    bad["value"] = "Best Northwind Home Insulated Bottle! Bottle Bottle Bottle, 750 ml " + "x" * 120
    r = _check_one(project, "NW-BTL-750-BLK", "item_name", bad)
    assert r["status"] == "NEEDS_REVIEW" and r["ai_fixable"]
    joined = " ".join(r["issues"])
    assert "banned characters: !" in joined and "bottle" in joined and "limit 150" in joined and "best" in joined


def test_unproven_claims_are_blocked(project):
    # 'antibacterial' only appears in a supplier note with no test reference
    b = {"value": "Hygienic Surface: Antibacterial bamboo that stays fresh.", "basis": "composed",
         "evidence": ["E069"], "claims": [{"text": "Antibacterial", "evidence": ["E069"]}]}
    r = _check_one(project, "NW-CUT-BMB-01", "bullet_point2", b)
    assert r["status"] == "NEEDS_REVIEW"
    assert any("antibacterial" in i and "reference" in i for i in r["issues"])
    # 'food-safe' is stated by the catalogue but without a declaration reference
    f = {"value": "Food-Safe Finish: Moso bamboo with a food-safe mineral oil finish.", "basis": "composed",
         "evidence": ["E098"], "claims": [{"text": "food-safe mineral oil finish", "evidence": ["E098"]}]}
    r = _check_one(project, "NW-CUT-BMB-01", "bullet_point2", f)
    assert r["status"] == "NEEDS_REVIEW"


def test_wrong_or_uncited_facts(project):
    r = _check_one(project, "NW-BTL-750-BLK", "item_weight_g", {"value": 350, "basis": "extracted", "evidence": ["E006"]})
    assert r["status"] == "NEEDS_REVIEW" and "not stated" in r["issues"][0]
    r = _check_one(project, "NW-BTL-750-BLK", "mrp_inr", {"value": 899, "basis": "extracted", "evidence": ["E999"]})
    assert r["status"] == "NOT_FOUND", "no valid evidence = value withheld"
    r = _check_one(project, "NW-BTL-750-BLK", "colour", {"value": "Blue", "basis": "extracted", "evidence": ["E007"]})
    assert r["status"] == "NEEDS_REVIEW"


def test_imported_product_with_indian_manufacturer_is_flagged(project):
    mfr = _answer(project, "NW-BTL-750-BLK")["fields"]["manufacturer_details"]
    r = _check_one(project, "NW-JAR-SET4-GLS", "manufacturer_details", mfr, {"country_of_origin": "China"})
    assert r["status"] == "NEEDS_REVIEW"
    assert any("imported" in i for i in r["issues"])


def test_stale_answer_is_detected(project):
    from listingq.validate import check_job

    path = project / "jobs" / JOB / "work" / "answers" / "NW-BTL-750-BLK.json"
    data = json.loads(path.read_text())
    data["packet_hash"] = "0000000000000000"
    path.write_text(json.dumps(data))
    check = check_job(JOB)
    assert any("older packet" in i for i in check["skus"]["NW-BTL-750-BLK"]["issues"])
    assert "AUTO_APPROVED" not in check["skus"]["NW-BTL-750-BLK"]["counts"]


# --------------------------------------------------------------------------- review + deliver


def _set_decision(root: Path, sku: str, label: str, decision: str, final=None) -> None:
    path = root / "jobs" / JOB / "output" / "review.xlsx"
    wb = load_workbook(path)
    ws = wb["Review"]
    for row in ws.iter_rows(min_row=2):
        if row[0].value == sku and row[1].value == label:
            row[7].value, row[8].value = decision, final
    wb.save(path)


def test_deliver_writes_only_approved_values(project):
    from listingq.__main__ import main

    main(["check", JOB])
    main(["deliver", JOB, "--no-flywheel"])
    wb = load_workbook(project / "jobs" / JOB / "output" / "marketplace_template_filled.xlsx")
    ws = wb["Template"]
    keys = [c.value for c in ws[2]]
    rows = {ws.cell(r, 1).value: r for r in range(3, ws.max_row + 1)}
    cell = lambda sku, key: ws.cell(rows[sku], keys.index(key) + 1)  # noqa: E731
    assert cell("NW-BTL-750-BLK", "mrp_inr").value == 899
    assert cell("NW-BTL-500-PNK", "capacity_ml").value is None, "pending review is never written"
    assert cell("NW-BTL-500-PNK", "capacity_ml").comment is not None
    assert cell("NW-CUT-BMB-01", "mrp_inr").value is None
    lineage = [json.loads(l) for l in (project / "jobs" / JOB / "output" / "lineage.jsonl").read_text().splitlines()]
    assert len(lineage) == 6 * 24
    written = [l for l in lineage if l["value_written"] is not None]
    assert all(l["evidence"] or l["final_status"].startswith("HUMAN") for l in written), "every written value has a source"


def test_review_edit_is_validated_and_applied(project):
    from listingq.__main__ import main
    from listingq.review import apply_review

    main(["check", JOB])
    _set_decision(project, "NW-CUT-BMB-01", "Maximum Retail Price (INR)", "EDIT", -5)
    res = apply_review(JOB, "Test Reviewer")
    assert res["decisions"] == [] and "breaks a rule" in res["problems"][0]
    _set_decision(project, "NW-CUT-BMB-01", "Maximum Retail Price (INR)", "EDIT", 1199)
    res = apply_review(JOB, "Test Reviewer")
    assert res["decisions"][0]["final_value"] == 1199
    out = main(["deliver", JOB, "--no-flywheel"])
    assert out == 0
    report = (project / "jobs" / JOB / "output" / "run_report.md").read_text()
    assert "5 of 6 products are ready" in report
    # if the AI answer changes after review, the old decision no longer applies
    path = project / "jobs" / JOB / "work" / "answers" / "NW-CUT-BMB-01.json"
    data = json.loads(path.read_text())
    data["fields"]["mrp_inr"]["note"] = "changed after review"
    path.write_text(json.dumps(data))
    main(["check", JOB])
    main(["deliver", JOB, "--no-flywheel"])
    report = (project / "jobs" / JOB / "output" / "run_report.md").read_text()
    assert "4 of 6 products are ready" in report


def test_rechecking_keeps_reviewer_decisions(project):
    from listingq.__main__ import main

    main(["check", JOB])
    _set_decision(project, "NW-BTL-500-PNK", "Capacity (ml)", "REJECT")
    main(["check", JOB])  # e.g. someone re-runs check before applying the review
    ws = load_workbook(project / "jobs" / JOB / "output" / "review.xlsx")["Review"]
    kept = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[0] == "NW-BTL-500-PNK" and r[1] == "Capacity (ml)"]
    assert kept[0][7] == "REJECT"


def test_brand_words_do_not_count_as_repeats(project):
    t = copy.deepcopy(_answer(project, "NW-BTL-750-BLK")["fields"]["item_name"])
    t["value"] = "Northwind Home Insulated Water Bottle for Home and Office Home Use, 750 ml, Stainless Steel, Black"
    r = _check_one(project, "NW-BTL-750-BLK", "item_name", t)
    assert not any("more than 2 times" in i for i in r["issues"]), r["issues"]
