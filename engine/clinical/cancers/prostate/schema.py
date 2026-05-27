"""
clinical/cancers/prostate/schema.py — Prostate Cancer Case Schema
Research use only. Not a licensed medical device.
"""
from __future__ import annotations

REQUIRED_FIELDS = ["cancer_type", "subtype", "stage", "line_of_therapy"]
VALID_SUBTYPES  = {"hormone_sensitive", "CRPC", "metastatic_CRPC", "localized"}


def validate_prostate_case(case: dict) -> None:
    for field in REQUIRED_FIELDS:
        if field not in case or case[field] is None:
            raise ValueError(
                f"Prostate schema validation failed: required field '{field}' missing. "
                f"Received keys: {list(case.keys())}"
            )
    if case["cancer_type"].lower() != "prostate":
        raise ValueError(
            f"Prostate schema: cancer_type must be 'prostate', got '{case['cancer_type']}'."
        )
