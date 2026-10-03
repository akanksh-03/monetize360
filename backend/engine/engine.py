import json
from datetime import date


def load_ruleset(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def evaluate_condition(cond: dict, context: dict) -> bool:
    field = cond["field"]
    op = cond["op"]
    value = cond["value"]
    if field not in context:
        return False
    actual = context[field]
    if op == "<":
        return actual < value
    elif op == ">":
        return actual > value
    elif op == "<=":
        return actual <= value
    elif op == ">=":
        return actual >= value
    elif op == "==":
        return actual == value
    return False


def rule_matches(rule: dict, context: dict, today: date = None) -> bool:
    if today is None:
        today = date.today()
    eff_from = rule.get("effective_from")
    eff_to = rule.get("effective_to")
    if eff_from and today < date.fromisoformat(eff_from):
        return False
    if eff_to and today > date.fromisoformat(eff_to):
        return False
    return all(evaluate_condition(c, context) for c in rule["conditions"])


def apply_action(price: float, action: dict) -> float:
    t = action["type"]
    v = action["value"]
    if t == "percent_increase":
        return price * (1 + v / 100)
    elif t == "percent_decrease":
        return price * (1 - v / 100)
    elif t == "flat_add":
        return price + v
    elif t == "flat_set":
        return v
    return price


def apply_constraints(price: float, base_price: float, context: dict, constraints: dict):
    applied = []

    if "max_multiplier" in constraints:
        cap = base_price * constraints["max_multiplier"]
        if price > cap:
            price = cap
            applied.append(f"max_multiplier={constraints['max_multiplier']}")

    if "min_multiplier" in constraints:
        floor = base_price * constraints["min_multiplier"]
        if price < floor:
            price = floor
            applied.append(f"min_multiplier={constraints['min_multiplier']}")

    if "max_price_field" in constraints:
        field = constraints["max_price_field"]
        if field in context:
            cap = context[field]
            if price > cap:
                price = cap
                applied.append(f"max_price = {field}")

    if "min_price_multiplier_of_cost" in constraints:
        if "cost_price" in context:
            floor = context["cost_price"] * constraints["min_price_multiplier_of_cost"]
            if price < floor:
                price = floor
                applied.append(f"min_price = cost_price * {constraints['min_price_multiplier_of_cost']}")

    return price, applied


def calculate_price(ruleset: dict, context: dict) -> dict:
    base_field = ruleset.get("base_price_field", "base_price")
    base_price = context[base_field]

    matched = [r for r in ruleset["rules"] if rule_matches(r, context)]
    matched.sort(key=lambda r: r["priority"])

    # conflict check: same priority, opposite direction
    conflict = False
    conflicting_rules = []
    by_priority = {}
    for r in matched:
        by_priority.setdefault(r["priority"], []).append(r)
    for prio, rules_at_prio in by_priority.items():
        if len(rules_at_prio) > 1:
            directions = set()
            for r in rules_at_prio:
                t = r["action"]["type"]
                if t in ("percent_increase", "flat_add"):
                    directions.add("up")
                elif t == "percent_decrease":
                    directions.add("down")
            if len(directions) > 1:
                conflict = True
                conflicting_rules.extend(r["id"] for r in rules_at_prio)

    price = base_price
    breakdown = []
    fired_rules = []
    for r in matched:
        before = price
        price = apply_action(price, r["action"])
        breakdown.append({
            "rule_id": r["id"],
            "description": r.get("description", r["id"]),
            "amount": round(price - before, 2)
        })
        fired_rules.append(r["id"])

    price, constraints_applied = apply_constraints(price, base_price, context, ruleset.get("constraints", {}))

    return {
        "base_price": base_price,
        "final_price": round(price, 2),
        "fired_rules": fired_rules,
        "breakdown": breakdown,
        "constraints_applied": constraints_applied,
        "conflict": conflict,
        "conflicting_rules": list(set(conflicting_rules))
    }