"""
engine/treatment_schema.py — Treatment dataclass

Used by eligibility filter and cancer-specific treatment catalogues.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Treatment:
    name: str
    cancer_type: str
    stages: List[str]
    duration_h: float
    trial_orr: float                                    # Overall Response Rate (0–1)
    grade34_toxicity_rate: float
    evidence_level: str                                 # "1A" | "1B" | "2A" | "2B" | "3"
    line_of_therapy: int
    cost: float
    modality: str                                       # targeted | immuno | chemo | combo
    requires_human: bool = True
    required_biomarkers: Dict[str, Any] = field(default_factory=dict)
    organ_function_gates: Dict[str, Any] = field(default_factory=dict)
    contraindications: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    trial_reference: Optional[str] = None
    base_effectiveness: Optional[float] = None         # alias for trial_orr if not set

    def to_dict(self) -> dict:
        return {
            "name":                  self.name,
            "cancer_type":           self.cancer_type,
            "stages":                self.stages,
            "duration_h":            self.duration_h,
            "trial_orr":             self.trial_orr,
            "grade34_toxicity_rate": self.grade34_toxicity_rate,
            "evidence_level":        self.evidence_level,
            "line_of_therapy":       self.line_of_therapy,
            "cost":                  self.cost,
            "modality":              self.modality,
            "requires_human":        self.requires_human,
            "required_biomarkers":   self.required_biomarkers,
            "organ_function_gates":  self.organ_function_gates,
            "contraindications":     self.contraindications,
            "notes":                 self.notes,
            "trial_reference":       self.trial_reference,
            "base_effectiveness":    self.base_effectiveness or self.trial_orr,
        }
