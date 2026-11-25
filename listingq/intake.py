"""Stage 1 - Intake.

Looks at everything in jobs/<job>/input/, works out what each file is
(marketplace template, supplier sheet or supplier catalogue), fingerprints it
with SHA-256 and writes work/manifest.json. Input files are never changed.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl

from .common import ensure_dirs, job_paths, log_event, now_iso, read_json, sha256_file, write_json

SHEET_TYPES = {".xlsx", ".xlsm"}
TEXT_DOC_TYPES = {".pdf", ".docx", ".md", ".txt"}


def classify(path: Path, profile: dict) -> str:
    suffix = path.suffix.lower()
    if suffix in SHEET_TYPES:
        tpl = profile["template"]
        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception:  # noqa: BLE001 - a broken file is reported, not fatal
            return "unsupported"
        try:
            if tpl["sheet"] in wb.sheetnames:
                ws = wb[tpl["sheet"]]
                keys = [c.value for c in next(ws.iter_rows(min_row=tpl["key_row"], max_row=tpl["key_row"]))]
                if tpl["sku_key"] in keys:
                    return "template"
        finally:
            wb.close()
        return "supplier_sheet"
    if suffix == ".csv":
        return "supplier_sheet"
    if suffix in TEXT_DOC_TYPES:
        return "catalogue"
    return "unsupported"


def intake(job_id: str, profile: dict) -> dict:
    paths = job_paths(job_id)
    if not paths["input"].is_dir():
        raise SystemExit(f"No input folder: {paths['input']}. Put the supplier files there first.")
    ensure_dirs(paths)

    files = []
    for path in sorted(paths["input"].iterdir()):
        if not path.is_file() or path.name.startswith((".", "~$")):
            continue
        files.append({
            "name": path.name,
            "role": classify(path, profile),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        })

    roles = [f["role"] for f in files]
    problems = []
    if roles.count("template") != 1:
        problems.append(f"expected exactly 1 marketplace template, found {roles.count('template')}")
    if "supplier_sheet" not in roles and "catalogue" not in roles:
        problems.append("no supplier sheet or catalogue found")
    if problems:
        log_event(job_id, "intake", "FAILED", problems=problems)
        raise SystemExit("Intake failed: " + "; ".join(problems))

    manifest_path = paths["work"] / "manifest.json"
    previous = read_json(manifest_path) if manifest_path.exists() else None
    changed = None
    if previous:
        old = {f["name"]: f["sha256"] for f in previous.get("files", [])}
        new = {f["name"]: f["sha256"] for f in files}
        changed = sorted(n for n in set(old) | set(new) if old.get(n) != new.get(n))

    manifest = {
        "job_id": job_id,
        "profile_id": profile["profile_id"],
        "created_at": now_iso(),
        "files": files,
        "inputs_changed_since_last_run": changed,
        "status": "INTAKE_DONE",
    }
    write_json(manifest_path, manifest)
    log_event(job_id, "intake", "DONE", files=len(files), unsupported=roles.count("unsupported"))
    return manifest
