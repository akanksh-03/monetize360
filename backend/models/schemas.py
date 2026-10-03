from pydantic import BaseModel
from typing import List, Optional, Union, Dict, Any
from datetime import date


class Condition(BaseModel):
    field: str
    op: str  # one of: "<", ">", "<=", ">=", "=="
    value: Union[str, float, int, bool]


class Action(BaseModel):
    type: str  # one of: "percent_increase", "percent_decrease", "flat_add", "flat_set"
    value: float


class Rule(BaseModel):
    id: str
    conditions: List[Condition]
    action: Action
    priority: int
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


class RuleSet(BaseModel):
    domain: str
    base_price_field: str = "base_price"
    rules: List[Rule]
    constraints: Dict[str, Any] = {}


class BreakdownItem(BaseModel):
    rule_id: str
    description: str
    amount: float


class PriceResponse(BaseModel):
    base_price: float
    final_price: float
    fired_rules: List[str]
    breakdown: List[BreakdownItem]
    constraints_applied: List[str]
    conflict: bool = False
    conflicting_rules: List[str] = []