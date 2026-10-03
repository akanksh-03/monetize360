import json
import random
import os

def gen_ecommerce(n=500):
    rows = []
    for i in range(n):
        mrp = random.choice([499, 999, 1499, 2999, 4999])
        rows.append({
            "id": f"ec_{i}",
            "inventory_pct": round(random.uniform(0, 1), 2),
            "demand_score": round(random.uniform(0, 1), 2),
            "customer_segment": random.choice(["regular", "regular", "loyalty"]),
            "mrp": mrp,
            "cost_price": round(mrp * 0.55),
            "base_price": round(mrp * 0.8)
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