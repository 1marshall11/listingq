---
name: listing
description: Run the ListingQ pipeline for one job folder in jobs/. Supplier files go in and a marketplace-ready listing template comes out, with every value backed by a source line. Use when asked to process, fill, list or catalogue products for a job.
argument-hint: <job-id>
allowed-tools: Read Write Edit Bash(python3 -m listingq *)
---

Run ListingQ for job `$ARGUMENTS`. `CLAUDE.md` in the project root has the full rules, and they apply here.

1. Run `python3 -m listingq prepare $ARGUMENTS`. Read its output, then read `kb/brand_guide.md` once.
2. For each file in `jobs/$ARGUMENTS/work/packets/`, write `jobs/$ARGUMENTS/work/answers/<SKU>.json`. Start from the packet's `answer_skeleton` and follow the fill rules in `CLAUDE.md`:
   - evidence only
   - cite IDs
   - no unproven regulated claims
   - conflicts go to a person
3. Run `python3 -m listingq check $ARGUMENTS`.
4. If `work/check.json` has fields with `"ai_fixable": true`, fix only those answers and run check again. Do at most 2 repair rounds.
5. Stop and report in plain English:
   - which products are ready to upload
   - what needs the reviewer, and why
   - which facts are missing from the supplier files
   - the review sheet: `jobs/$ARGUMENTS/output/review.xlsx`
6. Do not run `apply-review` or `deliver` until the person confirms the review is finished and gives the reviewer's name.
