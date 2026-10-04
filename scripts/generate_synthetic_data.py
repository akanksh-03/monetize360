import json
import random
import os
import math

def gen_ecommerce(n=500):
    rows = []
    for i in range(n):
        mrp = random.choice([499, 999, 1499, 2999, 4999])
        base_price = round(mrp * random.uniform(0.55, 0.95))
        discount_ratio = 1 - (base_price / mrp)
        customer_segment = random.choice(["regular", "regular", "loyalty"])
        is_loyalty = 1 if customer_segment == "loyalty" else 0
        inventory_pct = round(random.uniform(0, 1), 2)

        # Deliberately NOT a linear function — diminishing-returns curve on
        # discount (sqrt) plus a loyalty×discount interaction term. A plain
        # linear model structurally can't capture this well; tree-based
        # models can. This is what makes the model comparison meaningful
        # rather than decorative.
        base_effect = 0.22 + 0.85 * math.sqrt(max(discount_ratio, 0))
        loyalty_interaction = 0.18 * discount_ratio * is_loyalty
        overstock_drag = -0.06 * max(inventory_pct - 0.7, 0)
        noise = random.uniform(-0.12, 0.12)

        demand_score = max(0, min(1, base_effect + loyalty_interaction + overstock_drag + noise))

        rows.append({
            "id": f"ec_{i}",
            "inventory_pct": inventory_pct,
            "demand_score": round(demand_score, 2),
            "customer_segment": customer_segment,
            "mrp": mrp,
            "cost_price": round(mrp * 0.55),
            "base_price": base_price
        })
    return rows

def gen_ride_hailing(n=500):
    rows = []
    for i in range(n):
        rows.append({
            "id": f"rh_{i}",
            "demand_supply_ratio": round(random.uniform(0.5, 4), 2),
            "is_raining": random.random() < 0.15,
            "is_rush_hour": random.random() < 0.3,
            "base_fare": random.choice([60, 90, 120, 180])
        })
    return rows

output_dir = "backend/data/transactions"
os.makedirs(output_dir, exist_ok=True)

data = {"ecommerce": gen_ecommerce(), "ride_hailing": gen_ride_hailing()}

with open(os.path.join(output_dir, "synthetic_transactions.json"), "w") as f:
    json.dump(data, f, indent=2)

print("Done. Generated", len(data["ecommerce"]), "ecommerce rows and", len(data["ride_hailing"]), "ride-hailing rows.")