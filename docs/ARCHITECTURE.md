# System Architecture — Monetize360

## The flow, in one picture

Config UI (frontend/)
   Business user adds/edits rules — no code, just a form
        |
        | CRUD calls
        v
API Layer (backend/api/)
   /rules   /price   /simulate   — thin FastAPI routes only
        |
        | delegates to
        v
Services (backend/services/)
   pricing_service · simulation_service · conflict_service
   orchestrates engine calls, logs audit trail
        |
        | calls
        v
Rule Engine (backend/engine/)
   match conditions → sort by priority → stack adjustments
   → apply constraints (cap/floor) → build explanation
   PURE LOGIC — same code for every domain, no domain names
   hardcoded anywhere inside it
        |
        | reads
        v
Data Layer (backend/data/)
   rules/        — per-domain JSON rule configs
   transactions/ — synthetic context data for testing
   references/   — market-research facts (MVAG cap, MRP, etc.)

## Why this shape matters (say this part to judges)

The engine box in the middle never contains the word "ecommerce" or "ride_hailing" anywhere in its code. It only knows how to read {conditions, action, priority} objects and apply them to whatever context JSON it's given. Swapping domains means swapping the JSON file in data/rules/ — nothing in engine/ changes. That's the entire proof of "configuration, not rewrite."

## Layer responsibilities

| Layer | Responsibility | Must NOT do |
|---|---|---|
| models/ | Typed definitions (Rule, Condition, Action, Context) shared by everything else | Contain logic |
| engine/ | Evaluate rules against a context, return price + breakdown | Know about HTTP, databases, or specific domains |
| services/ | Orchestrate engine calls, handle audit logging, run simulations | Contain pricing math itself |
| api/ | Expose services over HTTP | Contain business logic |
| data/ | Hold rule configs, synthetic data, research references | — |

## Request flow example

1. A ride-hailing app sends POST /price with {demand_supply_ratio: 1.8, is_raining: true, base_fare: 100}
2. api/ hands this to pricing_service
3. pricing_service loads rules_ride_hailing.json, calls engine/ with the rules + context
4. engine/ matches rh_001 and rh_003, applies them in priority order, checks the max_multiplier constraint, builds the breakdown
5. Response: {"final_price": 149.5, "breakdown": [...]}
6. pricing_service logs this to the audit trail before returning it