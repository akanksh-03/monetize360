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
VERSIONS_DIR = os.path.join(BACKEND_DIR, "data", "versions")
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


# ---------------------------------------------------------------------------
# Versioning: every rule change is saved as an immutable snapshot
# backend/data/versions/<domain>/v0001.json, v0002.json, ...
# Version 1 is the baseline (state before the first change). Rollback restores
# an old snapshot AND records the restore as a new version, so history is
# append-only and the rollback itself can be undone.
# ---------------------------------------------------------------------------

def _version_dir(domain: str) -> str:
    return os.path.join(VERSIONS_DIR, domain)


def _version_numbers(domain: str) -> list:
    d = _version_dir(domain)
    nums = []
    if os.path.exists(d):
        for fname in os.listdir(d):
            if fname.startswith("v") and fname.endswith(".json"):
                try:
                    nums.append(int(fname[1:-5]))
                except ValueError:
                    pass
    return sorted(nums)


def _version_path(domain: str, n: int) -> str:
    return os.path.join(_version_dir(domain), f"v{n:04d}.json")


def _record_version(domain: str, ruleset: dict, action: str) -> int:
    """Caller must hold _rules_lock."""
    os.makedirs(_version_dir(domain), exist_ok=True)
    nums = _version_numbers(domain)
    n = (nums[-1] + 1) if nums else 1
    entry = {
        "version": n,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "ruleset": ruleset,
    }
    with open(_version_path(domain, n), "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2)
    return n


def _ensure_baseline(domain: str, ruleset: dict):
    """Caller must hold _rules_lock. Saves the current rules as v1 if no
    history exists yet."""
    if not _version_numbers(domain):
        _record_version(domain, ruleset, "initial state")


def add_rule(domain: str, rule: dict) -> dict:
    with _rules_lock:
        path = _resolve_path(domain)
        ruleset = load_ruleset(path)
        existing_ids = [r["id"] for r in ruleset["rules"]]
        if rule["id"] in existing_ids:
            raise ValueError(f"Rule id '{rule['id']}' already exists")
        _ensure_baseline(domain, ruleset)
        ruleset["rules"].append(rule)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ruleset, f, indent=2)
        _record_version(domain, ruleset, f"added rule {rule['id']}")
        return ruleset


def list_versions(domain: str) -> dict:
    with _rules_lock:
        path = _resolve_path(domain)
        _ensure_baseline(domain, load_ruleset(path))
        nums = _version_numbers(domain)
        versions = []
        for n in nums:
            with open(_version_path(domain, n), "r", encoding="utf-8") as f:
                entry = json.load(f)
            versions.append({
                "version": entry["version"],
                "timestamp": entry["timestamp"],
                "action": entry["action"],
                "rule_count": len(entry["ruleset"].get("rules", [])),
                "rule_ids": [r["id"] for r in entry["ruleset"].get("rules", [])],
                "is_latest": n == nums[-1],
            })
        return {"domain": domain, "versions": versions}


def rollback(domain: str, version: int) -> dict:
    with _rules_lock:
        path = _resolve_path(domain)
        _ensure_baseline(domain, load_ruleset(path))
        target = _version_path(domain, version)
        if not os.path.exists(target):
            raise ValueError(
                f"Version {version} does not exist for '{domain}'. "
                f"Available: {_version_numbers(domain)}")
        with open(target, "r", encoding="utf-8") as f:
            ruleset = json.load(f)["ruleset"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ruleset, f, indent=2)
        new_version = _record_version(domain, ruleset, f"rollback to v{version}")
        return {
            "domain": domain,
            "rolled_back_to": version,
            "new_version": new_version,
            "ruleset": ruleset,
        }


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

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