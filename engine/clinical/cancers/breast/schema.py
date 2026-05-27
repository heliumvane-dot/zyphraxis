"""
clinical/cancers/breast/schema.py — Breast Cancer Case Schema

Required fields: cancer_type, subtype, stage, line_of_therapy
Subtypes: HER2+, ER+, TNBC (triple-negative breast cancer)

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

REQUIRED_FIELDS = ["cancer_type", "subtype", "stage", "line_of_therapy"]
VALID_SUBTYPES  = {"HER2+", "ER+", "TNBC", "HER2+/ER+"}
VALID_STAGES    = {"I", "II", "III", "IV", "metastatic"}


def validate_breast_case(case: dict) -> None:
    """
    Validate a breast cancer case dict.
    Raises ValueError with a clear message on any failure.
    """
    for field in REQUIRED_FIELDS:
        if field not in case or case[field] is None:
            raise ValueError(
                f"Breast schema validation failed: required field '{field}' is missing. "
                f"Received keys: {list(case.keys())}"
            )

    subtype = case["subtype"]
    if subtype not in VALID_SUBTYPES:
        raise ValueError(
            f"Breast schema validation failed: unknown subtype='{subtype}'. "
            f"Valid subtypes: {VALID_SUBTYPES}"
        )

    if case["cancer_type"].lower() != "breast":
        raise ValueError(
            f"Breast schema: cancer_type must be 'breast', got '{case['cancer_type']}'."
        )
