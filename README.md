# ListingQ

**Supplier files in, marketplace-ready listings out. Every value is traced to its source line.**

ListingQ automates a junior e-commerce job: the catalogue or listing executive. That person turns a supplier's spec sheet and PDF catalogue into a marketplace upload template, which means a title, bullets, description and 20–40 attributes per product.

**How it works, in short:**

- Every column in the marketplace template is treated as a question.
- Answers come only from the supplier files, the brand guide and past approved listings.
- Each value gets a confidence score. Below 0.50 it is marked NOT_FOUND instead of guessed.
- Code checks and an AI repair loop run first, then a person reviews everything in `review.xlsx`.
- Every value is logged with its source file, evidence ID and reviewer, so you can trace where it came from.

## Quick start (5 minutes)

You need Python 3.10+ and [Claude Code](https://code.claude.com/docs/en/overview).

```bash
pip install -r requirements.txt
python3 -m pytest -q                      # 12 tests, about 2 seconds
```

**Run the demo end to end in Claude Code.** Open Claude Code in this folder and type:

```
/listing demo-001
```

Claude Code runs prepare, fills one answer file per product, runs the checks, repairs rule failures, and stops with a report. Your job is to open `jobs/demo-001/output/review.xlsx`, fill the Decision column, and then say "review done, I am <name>".

**Run it without Claude Code.** The demo already contains Claude Code's answer files, so you can replay every other stage:

```bash
python3 -m listingq prepare demo-001
python3 -m listingq check demo-001
python3 scripts/simulate_demo_review.py                  # demo only: a scripted reviewer
python3 -m listingq apply-review demo-001 --reviewer "Your Name"
python3 -m listingq deliver demo-001
```

**Run it unattended.** For example, a nightly job:

```bash
claude -p "/listing demo-001" --allowedTools "Read,Write,Edit,Bash(python3 -m listingq *)"
```

Do not add `--bare`. Bare mode skips `CLAUDE.md` and the skills that ListingQ needs.

## Your own job

1. Create `jobs/<job-id>/input/` and put in:
   - the marketplace template (`.xlsx` with a `Template` sheet: labels in row 1, attribute keys in row 2, SKUs from row 3)
   - the supplier files (`.xlsx`/`.csv` spec sheets and `.pdf`/`.docx`/`.md` catalogues)
2. In Claude Code, run `/listing <job-id>`.
3. Review `jobs/<job-id>/output/review.xlsx`, then ask Claude Code to apply the review and deliver.
4. Upload `jobs/<job-id>/output/<template>_filled.xlsx`. Shaded cells are blank on purpose, and each has a comment saying why.

For a different marketplace or category, copy `config/amazon_in_home_kitchen.yaml`, change the fields and rules, and pass `--profile <name>` to `prepare`.

## What you get

| File | What it is |
| --- | --- |
| `output/<template>_filled.xlsx` | The upload file. It contains only approved values; nothing unreviewed is written. |
| `output/review.xlsx` | One row per field that needs a person, with the reason and the quoted evidence. A Decision dropdown offers APPROVE, EDIT or REJECT. |
| `output/run_report.md` | Ready and not-ready products, what is still missing, reviewer decisions and input fingerprints |
| `output/lineage.jsonl` | One line per cell: source file hash, evidence line, confidence signals, reviewer and the destination cell |
| `work/events.jsonl` | Job telemetry (`python3 -m listingq status <job>`) |
| `kb/approved_listings.jsonl` | Grows with every approved product, so later jobs get better examples |

## Folder layout

```
CLAUDE.md                     operating manual for Claude Code (the fill rules)
.claude/skills/listing/       the /listing command
config/                       marketplace profiles (rules as YAML)
kb/                           brand guide + approved listings (the flywheel)
listingq/                     deterministic stages in Python
  intake.py parse.py template.py packets.py validate.py review.py deliver.py
jobs/demo-001/                fictional brand "Northwind Home": inputs, Claude Code answers, outputs
scripts/                      demo input generator, simulated reviewer
tests/                        pytest suite
```

## Limits of this MVP (by design)

- **One marketplace profile.** It is Amazon.in-style Home & Kitchen, simplified. Check limits against your category style guide before live use.
- **No images.** The `main_image_url` column is reported as out of scope and left blank.
- **Retrieval is scope-based, not vector-based.** This is enough when supplier files name product codes. Embeddings are on the improvements list for messy catalogues.
- **Only numbers and regulated claims are checked by code.** General marketing wording is checked by the reviewer, or by a future AI judge.
- **The demo data is invented.** The brand, supplier, addresses and test report numbers are all fictional.

## Licence

MIT. See [LICENSE](LICENSE).
