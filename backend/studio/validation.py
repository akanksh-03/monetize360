"""Validate configuration and requests BEFORE calling the original engine."""
from datetime import date
import math
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

OPS = {"<", ">", "<=", ">=", "=="}
ACTIONS = {"percent_increase", "percent_decrease", "flat_add", "flat_set"}
CONSTRAINTS = {"max_multiplier", "min_multiplier", "max_price_field",
               "min_price_multiplier_of_cost", "driver_payout_floor"}
NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class StudioError(ValueError):
    def __init__(self, message, code="INVALID_INPUT", status=422):
        super().__init__(message)
        self.code, self.status = code, status


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StudioError(f"{label} must be a number.")
    if not math.isfinite(value):
        raise StudioError(f"{label} must be finite.")
    return value


def name(value, label="Domain"):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise StudioError(f"{label}: use lowercase letters, numbers and underscores; start with a letter.")
    return value


def json_values(value, depth=0):
    if depth > 12:
        raise StudioError("JSON is nested too deeply.")
    if isinstance(value, dict):
        if len(value) > 300:
            raise StudioError("Too many fields.")
        for v in value.values():
            json_values(v, depth+1)
    elif isinstance(value, list):
        if len(value) > 500:
            raise StudioError("A list contains too many entries.")
        for v in value:
            json_values(v, depth+1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise StudioError("NaN and Infinity are not accepted.")
    elif isinstance(value, str) and len(value) > 10000:
        raise StudioError("A text field is too long.")


def validate_ruleset(config):
    if not isinstance(config, dict):
        raise StudioError("A domain package must be a JSON object.")
    json_values(config)
    name(config.get("domain"))
    name(config.get("base_price_field", "base_price"), "Base price field")
    rules = config.get("rules")
    if not isinstance(rules, list) or len(rules) > 200:
        raise StudioError("rules must be a list of at most 200 rules.")
    ids = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise StudioError("Every rule must be an object.")
        rid = rule.get("id")
        if not isinstance(rid, str) or not rid.strip() or len(rid) > 100 or rid in ids:
            raise StudioError("Every rule needs a unique, non-empty id (at most 100 characters).")
        ids.add(rid)
        priority = rule.get("priority")
        if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 100000:
            raise StudioError(f"{rid}: priority must be an integer from 0 to 100000.")
        conditions = rule.get("conditions")
        if not isinstance(conditions, list) or len(conditions) > 30:
            raise StudioError(f"{rid}: conditions must be a list with at most 30 entries.")
        for cond in conditions:
            if not isinstance(cond, dict) or set(cond) != {"field", "op", "value"}:
                raise StudioError(f"{rid}: each condition needs exactly field, op and value.")
            name(cond["field"], "Condition field")
            if cond["op"] not in OPS:
                raise StudioError(f"{rid}: unsupported operator {cond['op']}.")
            if not isinstance(cond["value"], (str, bool, int, float)):
                raise StudioError(f"{rid}: condition value must be a string, boolean or number.")
            if cond["op"] != "==":
                number(cond["value"], f"{rid} comparison value")
        action = rule.get("action", {})
        if not isinstance(action, dict) or set(action) != {"type", "value"} or action["type"] not in ACTIONS:
            raise StudioError(f"{rid}: unsupported action. Allowed: {', '.join(sorted(ACTIONS))}.")
        v = number(action["value"], f"{rid} adjustment")
        if action["type"] in ("percent_increase", "percent_decrease", "flat_set") and v < 0:
            raise StudioError(f"{rid}: this adjustment cannot be negative.")
        if action["type"] == "percent_decrease" and v > 100:
            raise StudioError(f"{rid}: a percentage discount cannot exceed 100%.")
        dates = []
        for field in ("effective_from", "effective_to"):
            try:
                dates.append(date.fromisoformat(rule[field]) if rule.get(field) else None)
            except (ValueError, TypeError):
                raise StudioError(f"{rid}: {field} must be YYYY-MM-DD.")
        if all(dates) and dates[0] > dates[1]:
            raise StudioError(f"{rid}: effective_from is after effective_to.")
    constraints = config.get("constraints", {})
    if not isinstance(constraints, dict) or set(constraints) - CONSTRAINTS:
        raise StudioError("Unsupported constraint. Studio rejects constraints the engine cannot interpret.")
    for key, value in constraints.items():
        if key == "max_price_field":
            name(value, "Maximum price field")
        elif number(value, key) < 0:
            raise StudioError(f"{key} cannot be negative.")
    if constraints.get("driver_payout_floor", 0) > 1:
        raise StudioError("driver_payout_floor must be between 0 and 1.")
    if constraints.get("min_multiplier", 0) > constraints.get("max_multiplier", float("inf")):
        raise StudioError("Minimum multiplier exceeds maximum multiplier.", "INFEASIBLE_BOUNDS")
    ui = config.get("studio", {})
    if not isinstance(ui, dict):
        raise StudioError("studio metadata must be an object.")
    if not isinstance(ui.get("currency", "INR"), str) or not re.fullmatch(r"[A-Z]{3}", ui.get("currency", "INR")):
        raise StudioError("Currency must be a three-letter uppercase code, for example INR.")
    for label in ("label", "description"):
        if label in ui and not isinstance(ui[label], str):
            raise StudioError(f"studio.{label} must be text.")
    bindings = ui.get("signal_bindings", {})
    if not isinstance(bindings, dict) or set(bindings)-{"weather"}:
        raise StudioError("Only the weather signal adapter is installed.")
    if bindings.get("weather"):
        name(bindings["weather"], "Weather target field")
    try:
        ZoneInfo(ui.get("timezone", "Asia/Kolkata"))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise StudioError("Unknown domain timezone.")
    fields = ui.get("fields", {})
    if not isinstance(fields, dict):
        raise StudioError("studio.fields must be an object.")
    for key, field in fields.items():
        name(key, "Attribute")
        if not isinstance(field, dict) or field.get("type") not in ("number", "boolean", "string"):
            raise StudioError(f"{key}: field type must be number, boolean or string.")
        for limit in ("min", "max"):
            if limit in field:
                number(field[limit], f"{key}.{limit}")
        if field.get("min", -float("inf")) > field.get("max", float("inf")):
            raise StudioError(f"{key}: minimum exceeds maximum.")
        if "options" in field and (not isinstance(field["options"], list) or not all(isinstance(x, (str, bool, int, float)) for x in field["options"])):
            raise StudioError(f"{key}: options must be a list of scalar values.")
        if "label" in field and not isinstance(field["label"], str):
            raise StudioError(f"{key}: label must be text.")
    return config


def validate_context(config, context):
    if not isinstance(context, dict):
        raise StudioError("context must be a JSON object.")
    json_values(context)
    base = config.get("base_price_field", "base_price")
    if base not in context or number(context[base], base) < 0:
        raise StudioError(f"Provide a non-negative {base}.")
    for key, field in config.get("studio", {}).get("fields", {}).items():
        if key not in context:
            if field.get("required", False):
                raise StudioError(f"Missing required attribute: {key}.")
            continue
        value, kind = context[key], field["type"]
        if kind == "number":
            number(value, key)
            if value < field.get("min", -float("inf")) or value > field.get("max", float("inf")):
                raise StudioError(f"{key} is outside the configured range.")
        elif kind == "boolean" and not isinstance(value, bool):
            raise StudioError(f"{key} must be true or false.")
        elif kind == "string" and not isinstance(value, str):
            raise StudioError(f"{key} must be text.")
        if field.get("options") and value not in field["options"]:
            raise StudioError(f"{key} must be one of {field['options']}.")
    for rule in config["rules"]:
        for cond in rule["conditions"]:
            key = cond["field"]
            if key in context:
                value = cond["value"]
                if cond["op"] != "==" or (isinstance(value, (int, float)) and not isinstance(value, bool)):
                    number(context[key], key)
                elif isinstance(value, bool) and not isinstance(context[key], bool):
                    raise StudioError(f"{key} must be a boolean.")
    c, lower, upper = config.get("constraints", {}), 0.0, float("inf")
    if "min_multiplier" in c:
        lower = max(lower, context[base] * c["min_multiplier"])
    if "max_multiplier" in c:
        upper = min(upper, context[base] * c["max_multiplier"])
    if "max_price_field" in c:
        key = c["max_price_field"]
        if key not in context:
            raise StudioError(f"{key} is required to enforce the maximum price.")
        upper = min(upper, number(context[key], key))
    if "min_price_multiplier_of_cost" in c:
        if "cost_price" not in context or number(context["cost_price"], "cost_price") < 0:
            raise StudioError("A non-negative cost_price is required to enforce the cost floor.")
        lower = max(lower, context["cost_price"] * c["min_price_multiplier_of_cost"])
    if lower > upper + 1e-9:
        raise StudioError(f"No valid price exists: minimum {lower:.2f} exceeds maximum {upper:.2f}. Review the cost, ceiling or margin rule.", "INFEASIBLE_BOUNDS")
    return lower, upper
