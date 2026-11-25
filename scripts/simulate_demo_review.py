"""SIMULATED reviewer for the demo only.

In real use a person opens output/review.xlsx, reads each row and fills the
Decision column. This script fills it for demo-001 so the whole loop can be
shown end to end. It only uses facts already in the supplier files: it never
types in a value that the supplier did not give.

Run after `python3 -m listingq check demo-001`:
    python3 scripts/simulate_demo_review.py
    python3 -m listingq apply-review demo-001 --reviewer "Demo reviewer (simulated)"
    python3 -m listingq deliver demo-001
"""
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / "jobs" / "demo-001" / "output" / "review.xlsx"

# (sku, field label) -> (decision, final value, note)
DECISIONS = {
    ("NW-BTL-500-PNK", "Capacity (ml)"): (
        "REJECT", None,
        "Spec sheet says 500 ml, catalogue says 550 ml. Leave blank and ask the supplier to confirm."),
}


def main() -> None:
    wb = load_workbook(REVIEW)
    ws = wb["Review"]
    done = 0
    for row in ws.iter_rows(min_row=2):
        key = (row[0].value, row[1].value)
        if key in DECISIONS:
            decision, final, note = DECISIONS[key]
            row[7].value, row[8].value, row[9].value = decision, final, note
            done += 1
    wb.save(REVIEW)
    print(f"Simulated reviewer filled {done} decision(s). Other rows are left for the supplier or brand.")


if __name__ == "__main__":
    main()
