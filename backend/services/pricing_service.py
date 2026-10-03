import os
import sys
import json
import threading
from collections import deque
from datetime import datetime, timezone

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BACKEND_DIR, "engine"))

from engine import load_ruleset, calculate_price

RULES_DIR = os.path.join(BACKEND_DIR, "data", "rules")
AUDIT_LOG_PATH = os.path.join(BACKEND_DIR, "data", "audit_log.jsonl")

# One lock per shared file, so concurrent requests cannot corrupt or
# overwrite each other's writes.
_audit_lock = threading.Lock()
_rules_lock = threading.Lock()


def get_domain_files() -> dict:
    """Scans the rules folder live - any rules_<domain>.json file becomes
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
    with _rules_lock:
        path = _resolve_path(domain)
        ruleset = load_ruleset(path)
        existing_ids = [r["id"] for r in ruleset["rules"]]
        if rule["id"] in existing_ids:
            raise ValueError(f"Rule id '{rule['id']}' already exists")
        ruleset["rules"].append(rule)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ruleset, f, indent=2)
        return ruleset


def _log_audit(domain, context, result):
    """Append one JSON line per priced transaction (JSON Lines format).
    Append-only + lock = no lost or corrupted entries under concurrency."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "domain": domain,
        "input": context,
        "result": result,
    }
    line = json.dumps(entry) + "\n"
    with _audit_lock:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)


def get_audit(limit: int = 20) -> dict:
    """Returns the total number of audit entries and the most recent `limit`."""
    total = 0
    recent = deque(maxlen=max(limit, 0))
    with _audit_lock:
        if os.path.exists(AUDIT_LOG_PATH):
            with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    total += 1
                    recent.append(line)
    return {"total_entries": total, "entries": [json.loads(l) for l in recent]}