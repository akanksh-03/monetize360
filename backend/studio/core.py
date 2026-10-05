"""Date-frozen adapter around the ORIGINAL rule engine, with no engine edits."""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import importlib.util
import math
from zoneinfo import ZoneInfo
from .storage import ROOT, fingerprint
from .validation import StudioError, validate_context, validate_ruleset

ENGINE_PATH = ROOT / "backend/engine/engine.py"
spec = importlib.util.spec_from_file_location("monetize_studio_original_engine", ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
ENGINE_HASH = hashlib.sha256(ENGINE_PATH.read_bytes()).hexdigest()


def evaluate(config, context, evaluation_date=None):
    validate_ruleset(config)
    lower, upper = validate_context(config, context)
    tz = config.get("studio", {}).get("timezone", "Asia/Kolkata")
    try:
        day = date.fromisoformat(evaluation_date) if evaluation_date else datetime.now(ZoneInfo(tz)).date()
    except (ValueError, TypeError):
        raise StudioError("evaluation_date must be YYYY-MM-DD.")
    # Use the engine's EXISTING date/condition matcher, then strip date gates on a
    # temporary copy. calculate_price can no longer read a different wall-clock day.
    matched = [r for r in config["rules"] if engine.rule_matches(r, context, today=day)]
    matched.sort(key=lambda r: r["priority"])  # stable ties preserve original order
    frozen = deepcopy(config)
    frozen["rules"] = []
    for rule in matched:
        item = deepcopy(rule)
        item.pop("effective_from", None)
        item.pop("effective_to", None)
        frozen["rules"].append(item)
    try:
        result = engine.calculate_price(frozen, context)
    except (OverflowError, TypeError, KeyError, ValueError) as e:
        raise StudioError(f"Pricing failed validation: {e}")
    if not math.isfinite(result["final_price"]) or result["final_price"] < 0:
        raise StudioError("The strategy produced a negative or non-finite price.")
    if result["final_price"] < lower - .011 or result["final_price"] > upper + .011:
        raise StudioError("The result violates a configured bound.", "BOUND_VIOLATION")
    # Trace exact intermediate values with the SAME action/constraint functions.
    running = result["base_price"]
    steps = []
    for rule in matched:
        before = running
        running = engine.apply_action(running, rule["action"])
        if not math.isfinite(running):
            raise StudioError("An intermediate price overflowed; reduce the adjustments.")
        steps.append({"kind": "rule", "id": rule["id"], "label": rule.get("description", rule["id"]),
                      "before": before, "after": running, "delta": running-before,
                      "conditions": rule["conditions"], "priority": rule["priority"]})
    before_constraints = running
    c = config.get("constraints", {})
    for key in ("max_multiplier", "min_multiplier", "max_price_field", "min_price_multiplier_of_cost"):
        if key in c:
            before = running
            running, applied = engine.apply_constraints(running, result["base_price"], context, {key: c[key]})
            if applied:
                steps.append({"kind": "constraint", "id": key, "label": applied[0],
                              "before": before, "after": running, "delta": running-before})
    if abs(result["final_price"]-running) > 1e-10:
        steps.append({"kind": "rounding", "id": "rounding", "label": "Currency rounding",
                      "before": running, "after": result["final_price"], "delta": result["final_price"]-running})
    settlement = None
    if "driver_payout_floor" in c:
        # Settlement is separate from the fare; an absent payout is NOT marked verified.
        minimum = math.ceil((result["final_price"] * c["driver_payout_floor"] - 1e-9) * 100) / 100
        actual = context.get("driver_payout")
        if actual is not None:
            from .validation import number
            number(actual, "driver_payout")
            if actual < minimum:
                raise StudioError(f"Driver payout {actual:.2f} is below configured minimum {minimum:.2f}.", "PAYOUT_VIOLATION")
        settlement = {"minimum": minimum, "actual": actual,
                      "status": "verified" if actual is not None else "not_supplied",
                      "note": "Configured settlement check; no payment is executed."}
    result["conflicting_rules"] = sorted(result.get("conflicting_rules", []))
    return {**result, "steps": steps, "pre_constraint_price": before_constraints,
            "evaluation_date": day.isoformat(), "timezone": tz, "config_hash": fingerprint(config),
            "engine_hash": ENGINE_HASH, "settlement": settlement}
