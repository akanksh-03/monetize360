import os
import sys
import json
from datetime import datetime, timezone

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BACKEND_DIR, "engine"))
sys.path.insert(0, BACKEND_DIR)

from engine import load_ruleset, calculate_price

try:
    from ml.predict_demand import predict_demand
    _ML_AVAILABLE = True
except Exception:
    _ML_AVAILABLE = False

RULES_DIR = os.path.join(BACKEND_DIR, "data", "rules")
VERSIONS_DIR = os.path.join(RULES_DIR, "_versions")
AUDIT_LOG_PATH = os.path.join(BACKEND_DIR, "data", "audit_log.json")


def get_domain_files() -> dict:
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


def _maybe_predict_demand(domain: str, context: dict):
    context = dict(context)
    predicted = {}
    if domain == "ecommerce" and "demand_score" not in context and _ML_AVAILABLE:
        try:
            val = round(predict_demand(context), 2)
            context["demand_score"] = val
            context["demand_score_source"] = "predicted"
            predicted["demand_score"] = val
        except Exception:
            pass
    return context, predicted


def get_price(domain: str, context: dict) -> dict:
    ruleset = load_ruleset(_resolve_path(domain))
    context, predicted = _maybe_predict_demand(domain, context)
    result = calculate_price(ruleset, context)
    result["predicted_fields"] = predicted
    _log_audit(domain, context, result)
    return result


def simulate(domain: str, contexts: list) -> list:
    ruleset = load_ruleset(_resolve_path(domain))
    results = []
    for ctx in contexts:
        ctx, predicted = _maybe_predict_demand(domain, ctx)
        result = calculate_price(ruleset, ctx)
        result["predicted_fields"] = predicted
        results.append(result)
    return results

# ---------- versioning ----------

def _versions_path(domain: str) -> str:
    return os.path.join(VERSIONS_DIR, f"{domain}.json")


def _load_versions(domain: str) -> dict:
    path = _versions_path(domain)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"versions": []}


def _save_version_snapshot(domain: str, action: str, rules: list) -> int:
    os.makedirs(VERSIONS_DIR, exist_ok=True)
    data = _load_versions(domain)
    next_version = len(data["versions"]) + 1
    entry = {
        "version": next_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "rule_count": len(rules),
        "rule_ids": [r["id"] for r in rules],
        "rules": rules,
    }
    data["versions"].append(entry)
    with open(_versions_path(domain), "w") as f:
        json.dump(data, f, indent=2)
    return next_version


def get_versions(domain: str) -> list:
    _resolve_path(domain)
    data = _load_versions(domain)
    if not data["versions"]:
        ruleset = load_ruleset(_resolve_path(domain))
        _save_version_snapshot(domain, "initial", ruleset["rules"])
        data = _load_versions(domain)
    versions = data["versions"]
    latest = versions[-1]["version"] if versions else None
    return [
        {
            "version": v["version"],
            "timestamp": v["timestamp"],
            "action": v["action"],
            "rule_count": v["rule_count"],
            "rule_ids": v["rule_ids"],
            "is_latest": v["version"] == latest,
        }
        for v in versions
    ]


def rollback(domain: str, version: int) -> int:
    data = _load_versions(domain)
    target = next((v for v in data["versions"] if v["version"] == version), None)
    if not target:
        raise ValueError(f"Version {version} not found for domain '{domain}'")
    path = _resolve_path(domain)
    ruleset = load_ruleset(path)
    ruleset["rules"] = target["rules"]
    with open(path, "w") as f:
        json.dump(ruleset, f, indent=2)
    return _save_version_snapshot(domain, f"rollback_to_v{version}", ruleset["rules"])


# ---------- rule CRUD ----------

def add_rule(domain: str, rule: dict) -> dict:
    path = _resolve_path(domain)
    ruleset = load_ruleset(path)
    existing_ids = [r["id"] for r in ruleset["rules"]]
    if rule["id"] in existing_ids:
        raise ValueError(f"Rule id '{rule['id']}' already exists")
    ruleset["rules"].append(rule)
    with open(path, "w") as f:
        json.dump(ruleset, f, indent=2)
    _save_version_snapshot(domain, f"add_rule:{rule['id']}", ruleset["rules"])
    return ruleset


def remove_rule(domain: str, rule_id: str) -> dict:
    path = _resolve_path(domain)
    ruleset = load_ruleset(path)
    before = len(ruleset["rules"])
    ruleset["rules"] = [r for r in ruleset["rules"] if r["id"] != rule_id]
    if len(ruleset["rules"]) == before:
        raise ValueError(f"Rule '{rule_id}' not found in domain '{domain}'")
    with open(path, "w") as f:
        json.dump(ruleset, f, indent=2)
    _save_version_snapshot(domain, f"remove_rule:{rule_id}", ruleset["rules"])
    return ruleset


# ---------- audit ----------

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