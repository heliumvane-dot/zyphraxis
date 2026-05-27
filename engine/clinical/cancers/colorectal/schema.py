"""
clinical/cancers/colorectal/schema.py — Colorectal Cancer Case Schema

Required fields: cancer_type, subtype, stage, line_of_therapy
Key biomarkers: KRAS, NRAS, BRAF, MSI/MMR, HER2

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

REQUIRED_FIELDS = ["cancer_type", "subtype", "stage", "line_of_therapy"]
VALID_SUBTYPES  = {"RAS_wt", "KRAS_mut", "NRAS_mut", "BRAF_V600E", "MSI-H", "MSS"}


def validate_colorectal_case(case: dict) -> None:
    for field in REQUIRED_FIELDS:
        if field not in case or case[field] is None:
            raise ValueError(
                f"Colorectal schema validation failed: required field '{field}' missing. "
                f"Received keys: {list(case.keys())}"
            )
    if case["cancer_type"].lower() != "colorectal":
        raise ValueError(
            f"Colorectal schema: cancer_type must be 'colorectal', got '{case['cancer_type']}'."
        )
