"""Shared helpers for every ListingQ stage.

Plain-English summary:
- where files live (jobs/, config/, kb/)
- reading and writing JSON / JSONL files
- hashing (so every file, packet and answer has a fingerprint for lineage)
- the job event log (our telemetry)
- small text helpers: normalising text and pulling quantities such as
  "750 ml", "0.41 kg", "Rs 1,099" or "7.5 x 7.5 x 26.5 cm" out of a sentence
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------


def root() -> Path:
    """Project root. Tests can point this somewhere else with LISTINGQ_ROOT."""
    env = os.environ.get("LISTINGQ_ROOT")
    return Path(env).resolve() if env else Path(__file__).resolve().parent.parent


def job_paths(job_id: str) -> dict[str, Path]:
    base = root() / "jobs" / job_id
    work = base / "work"
    return {
        "base": base,
        "input": base / "input",
        "work": work,
        "packets": work / "packets",
        "answers": work / "answers",
        "output": base / "output",
    }


def ensure_dirs(paths: dict[str, Path]) -> None:
    for key in ("work", "packets", "answers", "output"):
        paths[key].mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Files, JSON and hashing
# --------------------------------------------------------------------------


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_hash(obj: Any) -> str:
    """Fingerprint of any JSON-able object (key order does not matter)."""
    return sha256_text(json.dumps(obj, sort_keys=True, ensure_ascii=False))[:16]


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def log_event(job_id: str, stage: str, status: str, **details: Any) -> None:
    """Append one line to work/events.jsonl. This is the job's telemetry."""
    paths = job_paths(job_id)
    append_jsonl(
        paths["work"] / "events.jsonl",
        {"ts": now_iso(), "job_id": job_id, "stage": stage, "status": status, **details},
    )


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "×": "x", " ": " "})


def norm(text: Any) -> str:
    """Lower case, plain dashes, single spaces."""
    if text is None:
        return ""
    s = str(text).translate(_DASHES).lower()
    return re.sub(r"\s+", " ", s).strip()


STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "are", "per", "each", "into", "your",
    "you", "our", "its", "all", "has", "have", "not", "but", "use", "made", "item", "items",
}


def tokens(text: Any) -> list[str]:
    """Significant words, lightly stemmed (jars -> jar), for overlap checks."""
    out = []
    for raw in re.findall(r"[a-z0-9]+", norm(text)):
        if len(raw) < 3 or raw in STOPWORDS:
            continue
        if len(raw) > 3 and raw.endswith("s") and not raw.endswith("ss"):
            raw = raw[:-1]
        out.append(raw)
    return out


def to_number(text: Any) -> float | None:
    """First number in a string: '1,099' -> 1099.0, '0.41 kg' -> 0.41."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(text))
    if not m:
        return None
    return float(m.group(0).replace(",", ""))


# Quantity patterns. Every match is turned into a base unit so that
# "1 ltr", "1L" and "1000 ml" all compare as 1000 (ml).
_Q_PATTERNS = [
    ("volume_ml", re.compile(r"(\d+(?:\.\d+)?)\s*(ml|millilit(?:re|er)s?|l|ltrs?|lit(?:re|er)s?)\b"),
     {"ml": 1, "l": 1000, "ltr": 1000, "ltrs": 1000}),
    ("weight_g", re.compile(r"(\d+(?:\.\d+)?)\s*(g|gm|gms|grams?|kg|kgs|kilograms?)\b"),
     {"g": 1, "gm": 1, "gms": 1, "gram": 1, "grams": 1, "kg": 1000, "kgs": 1000,
      "kilogram": 1000, "kilograms": 1000}),
    ("time_h", re.compile(r"(\d+(?:\.\d+)?)\s*(h|hrs?|hours?)\b"), {"h": 1, "hr": 1, "hrs": 1, "hour": 1, "hours": 1}),
]
_MONEY = re.compile(r"(?:₹|\brs\b\.?|\binr\b|\bmrp\b)\s*(?:\([^)]*\))?\s*:?\s*(\d[\d,]*(?:\.\d+)?)")
_DIMS = re.compile(r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)")


def _unit_factor(kind: str, unit: str, table: dict) -> float:
    unit = unit.lower()
    if kind == "volume_ml":
        if unit.startswith("ml") or unit.startswith("millilit"):
            return 1
        return 1000  # l, ltr, litre, liter
    return table.get(unit, 1)


def quantities(text: Any) -> list[tuple[str, float]]:
    """All quantities in a text as (kind, value_in_base_unit).

    kinds: volume_ml, weight_g, time_h, money_inr
    """
    s = norm(text)
    found: list[tuple[str, float]] = []
    for kind, rx, table in _Q_PATTERNS:
        for m in rx.finditer(s):
            found.append((kind, round(float(m.group(1)) * _unit_factor(kind, m.group(2), table), 3)))
    for m in _MONEY.finditer(s):
        found.append(("money_inr", float(m.group(1).replace(",", ""))))
    return found


def dims(text: Any) -> list[tuple[float, float, float]]:
    """Dimension triples in cm. '7.5 x 7.5 x 26.5' -> (7.5, 7.5, 26.5); mm are converted."""
    s = norm(text)
    factor = 0.1 if re.search(r"\bmm\b", s) else 1.0
    return [tuple(round(float(g) * factor, 3) for g in m.groups()) for m in _DIMS.finditer(s)]
