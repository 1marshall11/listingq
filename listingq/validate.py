"""Stages 8-10 - Check: validation, groundedness and confidence.

For every product x field we compute five signals (0-1) plus a criticality
gate, then a status:

  evidence_present  every cited evidence ID exists in the product's packet
  evidence_match    the value can be found in the cited evidence
                    (numbers after unit conversion; claims in copy text must
                    be backed by a cited line, with a test/declaration
                    reference where the profile demands proof)
  rules             marketplace + brand rules (length, banned characters and
                    phrases, repeated words, allowed values, patterns)
  source_agreement  no conflict between supplier files for this quantity
  basis             extracted 1.0 > converted 0.9 > composed 0.85
  criticality gate  legally required declarations need a higher score

Status:
  NOT_FOUND       no value, or score < 0.50 -> value withheld (fail-safe, no fabrication)
  NEEDS_REVIEW    a rule broke, a conflict exists, or score < threshold
  AUTO_APPROVED   everything checks out
  NOT_APPLICABLE  field does not apply to this product (only where the profile allows)
"""
from __future__ import annotations

import re

from .common import dims, job_paths, log_event, norm, now_iso, quantities, read_json, stable_hash, to_number, tokens, write_json
from .profile import load_profile

SKU_LIKE = re.compile(r"\b[A-Z]{2,}-[A-Z]{2,}[A-Z0-9-]*\b")
RULE_ISSUE_TAG = "[rule]"


def _close(a: float, b: float, tol: float = 0.005) -> bool:
    return abs(a - b) <= max(tol * max(abs(a), abs(b)), 0.01)


def is_required(field: dict, values: dict) -> bool:
    if field.get("required"):
        return True
    cond = field.get("required_if")
    if not cond:
        return False
    other = values.get(cond["field"])
    if other in (None, ""):
        return False
    if "not_in" in cond:
        return other not in cond["not_in"]
    if "in" in cond:
        return other in cond["in"]
    return False


def has_proof(text: str, profile: dict) -> bool:
    """True if the line carries a test report / declaration reference (e.g. LT-2291)."""
    stripped = SKU_LIKE.sub(" ", text)
    return bool(profile["_proof_ref"].search(stripped))


# --------------------------------------------------------------------------
# Signal: evidence match
# --------------------------------------------------------------------------


def _match_fact(field: dict, value, basis: str, cited: list[dict], answer: dict, profile: dict):
    text = "\n".join(e["text"] for e in cited)
    ftype = field.get("type", "text")
    issues: list[str] = []

    if ftype == "number":
        num = to_number(value)
        if num is None:
            return 0.0, ["value is not a number"]
        qkind = field.get("quantity")
        if qkind:
            found = [v for e in cited for k, v in quantities(e["text"]) if k == qkind]
        else:
            found = [to_number(m) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]
        if any(v is not None and _close(num, v) for v in found):
            if basis == "converted" and not answer.get("note"):
                issues.append("converted value needs a note explaining the conversion")
            return 1.0, issues
        return 0.0, [f"{value} is not stated in the cited evidence"]

    if ftype == "dims":
        mine = dims(value)
        theirs = [t for e in cited for t in dims(e["text"])]
        if mine and any(all(_close(a, b) for a, b in zip(sorted(mine[0]), sorted(t))) for t in theirs):
            return 1.0, []
        return 0.0, ["dimensions do not match the cited evidence"]

    if ftype == "enum":
        pats = profile["_synonyms"].get(str(value))
        ok = any(p.search(text) for p in pats) if pats else norm(value) in norm(text)
        if not ok:
            return 0.0, [f"'{value}' is not supported by the cited evidence"]
        # Contradiction check for opposite answers (e.g. Yes vs No), only where the profile asks for it.
        for other in (field.get("allowed", []) if field.get("contradiction_check") else []):
            if other != value and other in profile["_synonyms"]:
                if any(p.search(text) for p in profile["_synonyms"][other]):
                    return 0.5, [f"cited evidence supports both '{value}' and '{other}'"]
        return 1.0, []

    if ftype == "code":
        code = re.sub(r"\s", "", str(value))
        if re.search(rf"(?<!\d){re.escape(code)}(?!\d)", re.sub(r"\s", "", text)):
            return 1.0, []
        return 0.0, [f"code {value} is not in the cited evidence"]

    # free text: exact containment, else word overlap
    if norm(value) and norm(value) in norm(text):
        return 1.0, []
    mine = tokens(value)
    if not mine:
        return 0.0, ["value has no checkable words"]
    theirs = set(tokens(text))
    overlap = sum(1 for t in mine if t in theirs) / len(mine)
    if overlap >= 0.85:
        return 1.0, []
    return round(overlap, 2), [f"only {overlap:.0%} of the words are in the cited evidence"]


def _match_copy(value, answer: dict, packet: dict, ev_index: dict, profile: dict):
    """Marketing copy may be reworded, but every number and every regulated claim must be backed."""
    issues: list[str] = []
    checks = passed = 0
    all_q = [(k, v) for e in packet["evidence"] for k, v in quantities(e["text"])]
    for kind, num in quantities(value):
        checks += 1
        if any(k == kind and _close(num, v) for k, v in all_q):
            passed += 1
        else:
            issues.append(f"'{num:g}' ({kind}) is not in the supplier documents")
    all_dims = [t for e in packet["evidence"] for t in dims(e["text"])]
    for d in dims(value):
        checks += 1
        if any(all(_close(a, b) for a, b in zip(sorted(d), sorted(t))) for t in all_dims):
            passed += 1
        else:
            issues.append("dimensions in the text are not in the supplier documents")

    claims = answer.get("claims") or []
    for cl in claims:
        for eid in cl.get("evidence") or []:
            if eid not in ev_index:
                issues.append(f"claim cites unknown evidence {eid}")

    for rc in profile["_regulated"]:
        if not rc["rx"].search(str(value)):
            continue
        checks += 1
        verdict = "missing"
        for cl in claims:
            if not rc["rx"].search(cl.get("text", "")):
                continue
            evs = [ev_index[i] for i in cl.get("evidence") or [] if i in ev_index]
            evs = [e for e in evs if rc["rx"].search(e["text"])]
            if not evs:
                continue
            if rc.get("proof_required") and not any(has_proof(e["text"], profile) for e in evs):
                verdict = "no_proof"
                continue
            verdict = "ok"
            break
        if verdict == "ok":
            passed += 1
        elif verdict == "no_proof":
            issues.append(f"claim '{rc['label']}' needs a test or declaration reference in its source line")
        else:
            issues.append(f"claim '{rc['label']}' is not backed by a cited source line")
    if checks == 0:
        return 1.0, issues
    score = passed / checks
    return (score if not issues else min(score, 0.99)), issues


# --------------------------------------------------------------------------
# Signal: rules
# --------------------------------------------------------------------------


def _phrase_rx(phrase: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])")


def rules_check(field: dict, value, profile: dict, values: dict):
    issues: list[str] = []
    rules = field.get("rules", {}) or {}
    s = "" if value is None else str(value)
    brand = str(values.get("brand_name") or "")

    allowed = field.get("allowed")
    if allowed and value not in allowed:
        issues.append(f"'{value}' is not an allowed value ({', '.join(allowed)})")
    if field.get("type") == "number":
        num = to_number(value)
        if num is None or num <= 0:
            issues.append("must be a positive number")
    if "max_chars" in rules and len(s) > rules["max_chars"]:
        issues.append(f"{len(s)} characters; limit {rules['max_chars']}")
    if "min_chars" in rules and len(s) < rules["min_chars"]:
        issues.append(f"{len(s)} characters; minimum {rules['min_chars']}")
    if "max_bytes" in rules and len(s.encode("utf-8")) > rules["max_bytes"]:
        issues.append(f"{len(s.encode('utf-8'))} bytes; limit {rules['max_bytes']}")
    if rules.get("banned_chars"):
        check = s.replace(brand, "") if brand else s
        bad = [c for c in rules["banned_chars"] if c in check]
        if bad:
            issues.append("banned characters: " + " ".join(bad))
    if rules.get("max_word_repeats"):
        exempt = set(rules.get("repeat_exempt_words", []))
        counts: dict[str, int] = {}
        without_brand = s.replace(brand, " ") if brand else s  # words in the brand name are exempt
        for w in re.findall(r"[a-z]+", without_brand.lower()):
            if w not in exempt:
                counts[w] = counts.get(w, 0) + 1
        over = [w for w, n in counts.items() if n > rules["max_word_repeats"]]
        if over:
            issues.append("words used more than %d times: %s" % (rules["max_word_repeats"], ", ".join(over)))
    if rules.get("pattern") and s and not re.fullmatch(rules["pattern"], s):
        issues.append(f"does not match the required format {rules['pattern']}")
    if field.get("kind") == "copy":
        low = s.lower()
        hits = [p for p in profile.get("banned_phrases", []) if _phrase_rx(p).search(low)]
        if hits:
            issues.append("banned phrases: " + ", ".join(hits))
        if rules.get("lowercase") and s != s.lower():
            issues.append("must be lower case")
        if rules.get("no_commas") and "," in s:
            issues.append("must not contain commas")
        if rules.get("no_brand_names") and brand and brand.lower() in low:
            issues.append("must not contain the brand name")
    return (0.0 if issues else 1.0), [f"{RULE_ISSUE_TAG} {i}" for i in issues]


# --------------------------------------------------------------------------
# Signal: agreement between sources
# --------------------------------------------------------------------------


def agreement(field: dict, value, packet: dict):
    issues = []
    for c in packet["conflicts"]:
        if c["field"] == field["key"]:
            detail = "; ".join(f"{s['file']} says {', '.join(f'{v:g}' for v in s['values'])}" for s in c["sources"])
            issues.append(f"sources disagree: {detail}")
    if field.get("kind") == "copy" and packet["conflicts"]:
        conflicted = {c["kind"] for c in packet["conflicts"]}
        if any(k in conflicted for k, _ in quantities(value)):
            issues.append("text mentions a quantity the sources disagree on")
    return (0.0 if issues else 1.0), issues


# --------------------------------------------------------------------------
# One field
# --------------------------------------------------------------------------


def check_field(field: dict, answer: dict, packet: dict, ev_index: dict, values: dict,
                profile: dict, stale: bool) -> dict:
    value = answer.get("value")
    basis = (answer.get("basis") or "").strip().lower()
    cited = [str(i) for i in (answer.get("evidence") or [])]
    required = is_required(field, values)
    critical = bool(field.get("critical"))
    base = {
        "key": field["key"],
        "label": field.get("label", field["key"]),
        "value": value,
        "basis": basis or None,
        "evidence": cited,
        "note": answer.get("note", ""),
        "required": required,
        "critical": critical,
        "answer_hash": stable_hash(answer),
    }

    if basis == "not_applicable":
        if field.get("allow_na") and not required:
            return {**base, "value": None, "status": "NOT_APPLICABLE", "score": 1.0, "signals": {}, "issues": []}
        basis = "not_found"
        base["basis"] = "not_found"
        na_issue = ["not applicable is not allowed for this field"]
    else:
        na_issue = []

    if basis in ("", "not_found") or value in (None, "", []):
        issues = na_issue + ([answer["note"]] if answer.get("note") else [])
        if required:
            issues.append("required field has no supported value")
        return {**base, "value": None, "status": "NOT_FOUND", "score": 0.0, "signals": {}, "issues": issues}

    issues: list[str] = []
    known = [i for i in cited if i in ev_index]
    unknown = [i for i in cited if i not in ev_index]
    if unknown:
        issues.append("unknown evidence IDs: " + ", ".join(unknown))
    present = 1.0 if known and not unknown else (0.5 if known else 0.0)
    if not known:
        issues.append("no valid evidence cited")
    cited_ev = [ev_index[i] for i in known]

    if field["kind"] == "copy":
        match, m_issues = _match_copy(value, answer, packet, ev_index, profile)
    else:
        match, m_issues = (_match_fact(field, value, basis, cited_ev, answer, profile) if cited_ev
                           else (0.0, []))
    issues += m_issues
    rules_score, r_issues = rules_check(field, value, profile, values)
    issues += r_issues
    agree, a_issues = agreement(field, value, packet)
    issues += a_issues
    for cc in profile.get("cross_checks", []):
        cond = cc["when"]
        other = values.get(cond["field"])
        applies = other not in (None, "") and (other not in cond["not_in"] if "not_in" in cond else other in cond.get("in", []))
        if cc["field"] == field["key"] and applies and re.search(cc["must_not_match"], str(value), re.I):
            issues.append(cc["message"])
            agree = 0.0
    strength = profile["basis_strength"].get(basis)
    if strength is None:
        issues.append(f"unknown basis '{basis}'")
        strength = 0.4

    w = profile["weights"]
    score = round(
        w["evidence_present"] * present + w["evidence_match"] * match + w["rules"] * rules_score
        + w["source_agreement"] * agree + w["basis"] * strength, 3)
    t = profile["thresholds"]
    threshold = t["auto_approve_critical"] if critical else t["auto_approve"]
    if stale:
        issues.append("answer was written for an older version of the evidence")
    issues = list(dict.fromkeys(issues))  # drop repeats, keep order

    if score < t["not_found_below"]:
        status = "NOT_FOUND"
        issues.append(f"confidence {score:.2f} is below {t['not_found_below']:.2f}; value withheld")
    elif issues or score < threshold:
        status = "NEEDS_REVIEW"
        if score < threshold and not issues:
            issues.append(f"confidence {score:.2f} is below the {threshold:.2f} auto-approve bar")
    else:
        status = "AUTO_APPROVED"

    fixable = status == "NEEDS_REVIEW" and issues and all(i.startswith(RULE_ISSUE_TAG) for i in issues)
    return {
        **base,
        "status": status,
        "score": score,
        "signals": {"evidence_present": present, "evidence_match": round(match, 2), "rules": rules_score,
                    "source_agreement": agree, "basis": strength},
        "issues": issues,
        "ai_fixable": bool(fixable),
    }


# --------------------------------------------------------------------------
# The whole job
# --------------------------------------------------------------------------


def check_job(job_id: str, profile_id: str | None = None) -> dict:
    paths = job_paths(job_id)
    manifest = read_json(paths["work"] / "manifest.json")
    profile = load_profile(profile_id or manifest["profile_id"])
    template = read_json(paths["work"] / "template.json")
    skus = [r["sku"] for r in template["rows"]]
    previous = read_json(paths["work"] / "check.json") if (paths["work"] / "check.json").exists() else None
    run_no = (previous or {}).get("run_no", 0) + 1

    results: dict[str, dict] = {}
    for sku in skus:
        packet = read_json(paths["packets"] / f"{sku}.json")
        ev_index = {e["id"]: e for e in packet["evidence"]}
        ans_path = paths["answers"] / f"{sku}.json"
        sku_issues: list[str] = []
        if ans_path.exists():
            answer = read_json(ans_path)
            stale = answer.get("packet_hash") != packet["packet_hash"]
            if stale:
                sku_issues.append("answer file was written for an older packet; fill this product again")
        else:
            answer, stale = {"fields": {}}, False
            sku_issues.append("no answer file yet; run the fill step")
        values = {k: (v or {}).get("value") for k, v in answer.get("fields", {}).items()}
        fields = {}
        for f in packet["fields"]:
            fields[f["key"]] = check_field(f, answer.get("fields", {}).get(f["key"]) or {}, packet,
                                           ev_index, values, profile, stale)
        counts: dict[str, int] = {}
        for r in fields.values():
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        blocking = [k for k, r in fields.items() if r["required"] and r["status"] not in ("AUTO_APPROVED",)]
        results[sku] = {
            "sku": sku,
            "packet_hash": packet["packet_hash"],
            "issues": sku_issues,
            "counts": counts,
            "ready_without_review": not blocking and not sku_issues,
            "blocking_fields": blocking,
            "fields": fields,
        }

    totals: dict[str, int] = {}
    for r in results.values():
        for status, n in r["counts"].items():
            totals[status] = totals.get(status, 0) + n
    check = {
        "job_id": job_id,
        "profile_id": profile["profile_id"],
        "run_no": run_no,
        "checked_at": now_iso(),
        "totals": totals,
        "ai_fixable": sum(1 for r in results.values() for f in r["fields"].values() if f.get("ai_fixable")),
        "skus": results,
    }
    write_json(paths["work"] / "check.json", check)
    log_event(job_id, "check", "DONE", run_no=run_no, totals=totals, ai_fixable=check["ai_fixable"])
    return check
