import os
import sys
from typing import Dict, Any, List, Optional

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BACKEND_DIR, "services"))
sys.path.insert(0, os.path.join(BACKEND_DIR, "engine"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pricing_service import (get_price, simulate, add_rule, get_domain_files,
                             get_audit, list_versions, rollback, RULES_DIR)
from engine import load_ruleset

app = FastAPI(title="Monetize360 Pricing API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class PriceRequest(BaseModel):
    domain: str
    context: Dict[str, Any]


class SimulateRequest(BaseModel):
    domain: str
    contexts: List[Dict[str, Any]]


class RuleIn(BaseModel):
    id: str
    conditions: List[Dict[str, Any]]
    action: Dict[str, Any]
    priority: int
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None


@app.get("/")
def root():
    return {"status": "ok", "domains": list(get_domain_files().keys())}


@app.get("/domains")
def list_domains():
    return {"domains": list(get_domain_files().keys())}


@app.post("/price")
def price(req: PriceRequest):
    try:
        return get_price(req.domain, req.context)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/simulate")
def simulate_endpoint(req: SimulateRequest):
    try:
        return simulate(req.domain, req.contexts)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/rules/{domain}")
def get_rules(domain: str):
    domain_files = get_domain_files()
    if domain not in domain_files:
        raise HTTPException(status_code=404, detail=f"Unknown domain: {domain}")
    return load_ruleset(os.path.join(RULES_DIR, domain_files[domain]))


@app.post("/rules/{domain}")
def create_rule(domain: str, rule: RuleIn):
    try:
        return add_rule(domain, rule.dict(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/rules/{domain}/versions")
def rule_versions(domain: str):
    try:
        return list_versions(domain)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/rules/{domain}/rollback/{version}")
def rule_rollback(domain: str, version: int):
    try:
        return rollback(domain, version)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/audit")
def audit(limit: int = 20):
    return get_audit(limit)