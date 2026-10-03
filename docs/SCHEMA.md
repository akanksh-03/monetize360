# Pricing Rule Schema — Monetize360

This is the single contract every part of the system builds against — engine, API, and UI all agree on this exact shape. No one touches rule logic without matching this doc.

## File structure

Each domain's rules live in one file: `backend/data/rules/rules_<domain>.json`

```json
{
  "domain": "ecommerce",
  "rules": [ ... ],
  "constraints": { ... }
}
```

## Rule object

```json
{
  "id": "ec_001",
  "conditions": [
    {"field": "inventory_pct", "op": "<", "value": 0.2}
  ],
  "action": {"type": "percent_increase", "value": 8},
  "priority": 1,
  "effective_from": "2026-10-07",
  "effective_to": null
}
```

- `conditions`: a list of `{field, op, value}` checks. **All conditions must be true (AND logic)** for the rule to fire. Supported `op`: `<`, `>`, `<=`, `>=`, `==`.
- `action.type`: one of `percent_increase`, `percent_decrease`, `flat_add`, `flat_set`.
- `priority`: lower number = applied earlier. Two rules with the same priority that contradict each other get flagged as a conflict, never silently resolved.
- `effective_from` / `effective_to`: the date window the rule is active. `null` on `effective_to` means it never expires.

## Constraints object

Hard bounds the engine enforces *after* all rules have fired — not rules themselves.

```json
"constraints": {
  "max_multiplier": 2.0,
  "min_multiplier": 0.5,
  "driver_payout_floor": 0.80
}
```
(E-commerce uses `max_price_field` / `min_price_multiplier_of_cost` instead — see `rules_ecommerce.json`.)

## How a price gets calculated (the conflict/stacking policy)

1. Keep only rules whose `conditions` all evaluate true for the incoming request, and whose date window covers today.
2. Sort the matched rules by `priority`, ascending.
3. Apply each rule's `action` **multiplicatively**, one at a time, on the running price — not all on the original base price.
4. Clamp the result against the domain's `constraints` (e.g. never exceed MRP, never exceed 2x base fare).
5. Record every rule that fired and its individual contribution — this becomes the explanation breakdown.

## Explanation output format

Every price the API returns comes with this, not just a number:

```json
{
  "base_price": 800,
  "final_price": 864,
  "fired_rules": ["ec_001"],
  "breakdown": [
    {"rule_id": "ec_001", "description": "Low inventory surcharge", "amount": 64}
  ],
  "constraints_applied": []
}
```
If a constraint clamps the price, it shows up in `constraints_applied`, e.g. `["max_price = mrp"]`.

## Conflict handling

If two rules share the same `priority` and push the price in opposite directions for the same request, the engine returns `conflict: true` with both rule IDs instead of picking one silently. The config UI should also block saving two same-priority, contradictory rules without explicit confirmation.