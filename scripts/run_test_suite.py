import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend", "engine"))

from engine import load_ruleset, calculate_price

RULES_DIR = os.path.join(ROOT, "backend", "data", "rules")
TEST_CASES_PATH = os.path.join(ROOT, "backend", "tests", "test_cases.json")


def run_domain_tests(domain_name, rules_file, test_cases):
    ruleset = load_ruleset(os.path.join(RULES_DIR, rules_file))
    passed, failed = 0, 0
    print(f"\n=== {domain_name.upper()} ===")
    for case in test_cases:
        result = calculate_price(ruleset, case["input"])
        expected = case.get("expected_final_price", case.get("expected_final_fare"))
        actual = result["final_price"]
        ok = abs(actual - expected) < 0.01
        status = "PASS" if ok else "FAIL"
        passed += ok
        failed += not ok
        print(f"[{status}] {case['test_id']}: expected={expected}, got={actual}, fired={result['fired_rules']}")
        if not ok:
            print(f"       breakdown={result['breakdown']}  constraints_applied={result['constraints_applied']}")
    total = passed + failed
    pct = round(passed / total * 100, 1) if total else 0
    print(f"{domain_name}: {passed}/{total} passed ({pct}%)")
    return passed, total


def main():
    with open(TEST_CASES_PATH) as f:
        all_cases = json.load(f)

    ec_p, ec_t = run_domain_tests("ecommerce", "rules_ecommerce.json", all_cases["ecommerce"])
    rh_p, rh_t = run_domain_tests("ride_hailing", "rules_ride_hailing.json", all_cases["ride_hailing"])

    total_p, total_t = ec_p + rh_p, ec_t + rh_t
    overall = round(total_p / total_t * 100, 1) if total_t else 0
    print(f"\n=== OVERALL: {total_p}/{total_t} passed ({overall}%) ===")


if __name__ == "__main__":
    main()