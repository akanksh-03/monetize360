"""Measure a RUNNING LOCAL Studio API; results are measured, not promises."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=5)
    args = parser.parse_args()
    body = json.dumps({"domain": "ride_hailing", "context": {
        "base_fare": 100, "demand_supply_ratio": 1.8, "is_raining": True, "is_rush_hour": False}}).encode()
    def call(_):
        started = time.perf_counter()
        req = urllib.request.Request(args.url.rstrip('/')+"/price", body, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                data = json.load(response)
            return (time.perf_counter()-started)*1000, data.get("final_price") == 149.5
        except (OSError, ValueError, urllib.error.HTTPError):
            return (time.perf_counter()-started)*1000, False
    for _ in range(5):
        call(0)
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(call, range(args.requests)))
    elapsed = time.perf_counter()-start
    success = sorted(ms for ms, ok in results if ok)
    def percentile(p):
        return round(success[min(len(success)-1, int((len(success)-1)*p))], 2) if success else None
    print(json.dumps({"requests": args.requests, "concurrency": args.concurrency, "successes": len(success),
        "errors": args.requests-len(success), "successful_requests_per_second": round(len(success)/elapsed, 2),
        "p50_ms": percentile(.5), "p95_ms": percentile(.95), "p99_ms": percentile(.99),
        "scope": "HTTP request including SQLite audit commit; no external weather/LLM call; local client and server",
        "note": "A rate-limited response counts as an error. These requests create real demo receipts."}, indent=2))


if __name__ == "__main__":
    main()
