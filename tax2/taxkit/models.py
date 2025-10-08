from __future__ import annotations
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional, List, Dict

class FilingStatus(str, Enum):
    single = "single"
    married_joint = "married_joint"

class Bracket(BaseModel):
    up_to: Optional[float] = Field(None, description="Upper bound (annual taxable). None = no upper bound")
    rate: float

class Phaseout(BaseModel):
    start_income: float
    rate_per_dollar: float

class Credit(BaseModel):
    name: str
    amount: Optional[float] = 0.0
    amount_per_child: Optional[float] = None
    refundable_cap: Optional[float] = None
    phaseout: Optional[Phaseout] = None

class TaxRules(BaseModel):
    year: int
    jurisdiction: str
    filing_statuses: List[FilingStatus]
    standard_deduction: Dict[FilingStatus, float]
    brackets: Dict[FilingStatus, List[Bracket]]
    credits: List[Credit] = []

class TaxInput(BaseModel):
    annual_income: float
    filing_status: FilingStatus
