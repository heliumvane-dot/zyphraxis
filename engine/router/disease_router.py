"""
router/disease_router.py — Zyphraxis Phase 7A: Disease Router

Routes a clinical case to the appropriate cancer-specific module.
NO fallback. Hard failure on unknown cancer_type.
NO cross-cancer imports permitted here.

Supported cancer types (Phase 7A):
  lung        → Phase 6 NSCLC pipeline (UNTOUCHED)
  breast      → clinical/cancers/breast/
  colorectal  → clinical/cancers/colorectal/
  prostate    → clinical/cancers/prostate/

Research use only. Not a licensed medical device.
"""
from __future__ import annotations

from typing import Any, Dict


# ---------------------------------------------------------------------------
# Routing table — built lazily to avoid circular imports
# Each entry is a callable: run(case: dict) -> dict
# ---------------------------------------------------------------------------

def _load_routes() -> Dict[str, Any]:
    """Lazy-load to prevent import side-effects at module level."""
    from core.registry import CANCER_REGISTRY
    return CANCER_REGISTRY


class DiseaseRouter:
    """
    Routes cases to cancer-specific decision pipelines.

    Usage:
        router = DiseaseRouter()
        result = router.route(case)
    """

    def route(self, case: dict) -> dict:
        """
        Route case to the appropriate cancer pipeline.

        Args:
            case: Must contain 'cancer_type' key.

        Returns:
            Decision dict from the cancer-specific pipeline.

        Raises:
            ValueError: If cancer_type is missing or unknown.
        """
        cancer_type = case.get("cancer_type", "").lower().strip()

        if not cancer_type:
            raise ValueError(
                "DiseaseRouter: 'cancer_type' field is required. "
                "Got empty or missing value."
            )

        registry = _load_routes()

        if cancer_type not in registry:
            raise ValueError(
                f"DiseaseRouter: Unknown cancer_type='{cancer_type}'. "
                f"Registered types: {sorted(registry.keys())}. "
                "No fallback permitted — add a module or correct the input."
            )

        handler = registry[cancer_type]
        return handler(case)


# Module-level singleton
DISEASE_ROUTER = DiseaseRouter()
