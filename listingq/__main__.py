"""ListingQ command line.

    python3 -m listingq prepare <job>        stages 1-7: intake, parse, scope, template, packets
    (Claude Code fills work/answers/<sku>.json - see CLAUDE.md)
    python3 -m listingq check <job>          stages 8-10: validate, score, build output/review.xlsx
    python3 -m listingq apply-review <job> --reviewer "Name"   stage 11: read the reviewer's decisions
    python3 -m listingq deliver <job>        stages 12-13: filled template, lineage, report, flywheel
    python3 -m listingq status <job>         where the job stands
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from .common import job_paths, log_event, read_json
from .deliver import deliver
from .intake import intake
from .packets import build_packets
from .parse import parse_catalogues, parse_inputs
from .profile import DEFAULT_PROFILE, load_profile
from .review import apply_review, build_review_workbook
from .template import extract_template
from .validate import check_job


def cmd_prepare(job: str, profile_id: str) -> None:
    t0 = time.perf_counter()
    profile = load_profile(profile_id)
    manifest = intake(job, profile)
    evidence, supplier_skus = parse_inputs(job, profile, manifest)
    template, fields = extract_template(job, profile, manifest)
    sku_codes = list(dict.fromkeys([r["sku"] for r in template["rows"]] + supplier_skus))
    evidence = parse_catalogues(job, profile, manifest, sku_codes, evidence)
    skus = build_packets(job, evidence, template, fields, supplier_skus)
    ms = int((time.perf_counter() - t0) * 1000)
    log_event(job, "prepare", "DONE", ms=ms)
    print(f"Prepared {len(skus)} product packets from {len(manifest['files'])} files "
          f"({len(evidence)} evidence lines) in {ms} ms.")
    for f in manifest["files"]:
        print(f"  - {f['name']}: {f['role']}")
    unmapped = [f["key"] for f in fields if f["kind"] == "unmapped"]
    if unmapped:
        print(f"  Template columns this profile does not handle (left blank): {', '.join(unmapped)}")
    paths = job_paths(job)
    for sku in skus:
        p = read_json(paths["packets"] / f"{sku}.json")
        flag = f"  CONFLICTS: {[c['field'] for c in p['conflicts']]}" if p["conflicts"] else ""
        print(f"  packet {sku}: {len(p['evidence'])} evidence lines{flag}")
    print(f"Next: fill jobs/{job}/work/answers/<sku>.json for each packet (see CLAUDE.md), then run check.")


def cmd_check(job: str) -> None:
    check = check_job(job)
    review_path = build_review_workbook(job)
    print(f"Check run {check['run_no']}: {json.dumps(check['totals'])}")
    for sku, r in check["skus"].items():
        state = "ready" if r["ready_without_review"] else f"needs a person ({', '.join(r['blocking_fields']) or 'see issues'})"
        print(f"  {sku}: {json.dumps(r['counts'])} -> {state}")
        for issue in r["issues"]:
            print(f"    ! {issue}")
    if check["ai_fixable"]:
        print(f"{check['ai_fixable']} field(s) fail only on rules the AI can fix (look for ai_fixable in work/check.json).")
    print(f"Review sheet: {review_path}")


def cmd_status(job: str) -> None:
    paths = job_paths(job)
    events = paths["work"] / "events.jsonl"
    if not events.exists():
        print("No events yet. Run prepare first.")
        return
    for line in events.read_text(encoding="utf-8").splitlines()[-12:]:
        e = json.loads(line)
        extra = {k: v for k, v in e.items() if k not in ("ts", "job_id", "stage", "status")}
        print(f"{e['ts']}  {e['stage']:<13} {e['status']:<8} {json.dumps(extra)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="listingq", description="Supplier files in, marketplace-ready listings out.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("job")
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    sub.add_parser("check").add_argument("job")
    r = sub.add_parser("apply-review")
    r.add_argument("job")
    r.add_argument("--reviewer", required=True)
    d = sub.add_parser("deliver")
    d.add_argument("job")
    d.add_argument("--no-flywheel", action="store_true", help="do not add approved listings to kb/")
    sub.add_parser("status").add_argument("job")
    args = ap.parse_args(argv)

    if args.cmd == "prepare":
        cmd_prepare(args.job, args.profile)
    elif args.cmd == "check":
        cmd_check(args.job)
    elif args.cmd == "apply-review":
        res = apply_review(args.job, args.reviewer)
        print(f"Applied {len(res['decisions'])} decision(s) by {args.reviewer}.")
        for prob in res["problems"]:
            print(f"  ! {prob}")
    elif args.cmd == "deliver":
        res = deliver(args.job, flywheel=not args.no_flywheel)
        print(f"{res['ready']} of {res['total']} products ready. Upload file: {res['output']}")
        for s in res["skus"]:
            if not s["ready"]:
                print(f"  {s['sku']}: missing {', '.join(s['missing_required'])}")
    elif args.cmd == "status":
        cmd_status(args.job)
    return 0


if __name__ == "__main__":
    sys.exit(main())
