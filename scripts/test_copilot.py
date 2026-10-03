import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.copilot import text_to_rule, CopilotError

FIELDS = ["demand_supply_ratio", "is_raining", "is_rush_hour", "base_fare"]
TESTS = [
    "When it is raining, increase the price by 15 percent",
    "If demand to supply ratio is above 2, add 20 rupees",
    "During rush hour when it is not raining, increase fare by 10%",
    "Give a discount when the moon is full",
]

for t in TESTS:
    print("\nINSTRUCTION:", t)
    try:
        print(json.dumps(text_to_rule(t, FIELDS), indent=2))
    except CopilotError as e:
        print("ERROR:", e)