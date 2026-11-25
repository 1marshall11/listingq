"""Marketplace profile: the rules for one marketplace + brand, kept in YAML.

Adding a new marketplace (Flipkart, Noon, Shopify) means adding a new YAML
file in config/, not writing new code.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from .common import root

DEFAULT_PROFILE = "amazon_in_home_kitchen"


@lru_cache(maxsize=8)
def load_profile(profile_id: str = DEFAULT_PROFILE) -> dict:
    path = root() / "config" / f"{profile_id}.yaml"
    with open(path, encoding="utf-8") as fh:
        prof = yaml.safe_load(fh)
    prof["_path"] = str(path)
    prof["_fields_by_key"] = {f["key"]: f for f in prof["fields"]}
    # pre-compile patterns once
    prof["_regulated"] = [
        {**c, "rx": re.compile(c["pattern"], re.I)} for c in prof.get("regulated_claims", [])
    ]
    prof["_synonyms"] = {
        value: [re.compile(p, re.I) for p in pats] for value, pats in prof.get("synonyms", {}).items()
    }
    prof["_proof_ref"] = re.compile(prof.get("proof_reference_pattern", r"\b[A-Z]{2,4}-\d{2,}(?:-\d+)*\b"))
    return prof


def field_def(profile: dict, key: str) -> dict | None:
    return profile["_fields_by_key"].get(key)


def profile_path(profile_id: str) -> Path:
    return root() / "config" / f"{profile_id}.yaml"
