import os
import sys
import json
from datetime import datetime, timezone

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BACKEND_DIR, "engine"))

from engine import load_ruleset, calculate_price

RULES_DIR = os.path.join(BACKEND_DIR, "data", "rules")
AUDIT_LOG_PATH = os.path.join(BACKEND_DIR, "data", "audit_log.json")


def get_domain_files() -> dict:
    """Scans the rules folder live — any rules_<domain>.json file becomes
    an available domain with zero code changes needed."""
    domains = {}
    if os.path.exists(RULES_DIR):
        for fname in os.listdir(RULES_DIR):
            if fname.startswith("rules_") and fname.endswith(".json"):
                domain = fname[len("rules_"):-len(".json")]
                domains[domain] = fname
    return domains


def _resolve_path(domain: str) -> str:
    domain_files = get_domain_files()
    if domain not in domain_files:
        raise ValueError(f"Unknown domain: {domain}. Valid options: {list(domain_files.keys())}")
    return os.path.join(RULES_DIR, domain_files[domain])


def get_price(domain: str, context: dict) -> dict:
    ruleset = load_ruleset(_resolve_path(domain))
    result = calculate_price(ruleset, context)
    _log_audit(domain, context, result)
    return result


def simulate(domain: str, contexts: list) -> list:
    ruleset = load_ruleset(_resolve_path(domain))
    return [calculate_price(ruleset, ctx) for ctx in contexts]


def add_rule(domain: str, rule: dict) -> dict:
    path = _resolve_path(domain)
    ruleset = load_ruleset(path)
    existing_ids = [r["id"] for r in ruleset["rules"]]
    if rule["id"] in existing_ids:
        raise ValueError(f"Rule id '{rule['id']}' already exists")
    ruleset["rules"].append(rule)
    with open(path, "w") as f:
        json.dump(ruleset, f, indent=2)
    return ruleset


def _log_audit(domain, context, result):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "domain": domain,
        "input": context,
        "result": result,
    }
    logs = []
    if os.path.exists(AUDIT_LOG_PATH):
        with open(AUDIT_LOG_PATH, "r") as f:
            try:
                logs = json.load(f)
            except json.JSONDecodeError:
                logs = []
    logs.append(entry)
    with open(AUDIT_LOG_PATH, "w") as f:
        json.dump(logs, f, indent=2)