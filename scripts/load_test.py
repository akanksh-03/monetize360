"""
Load test for the Monetize360 pricing API.
Measures latency (p50/p95/p99) and throughput (requests/sec) per endpoint.
Standard library only.

Usage (server must already be running):
    python scripts/load_test.py
    python scripts/load_test.py --concurrency 20 --requests 2000
"""
import argparse
import http.client
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HOST = "127.0.0.1"

ECOM_CTX = {"inventory_pct": 0.1, "demand_score": 0.8, "customer_segment": "regular",
            "mrp": 1000, "cost_price": 550, "base_price": 800}
RIDE_CTX = {"demand_supply_ratio": 2.0, "is_raining": False,
            "is_rush_hour": False, "base_fare": 100}

AUDIT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "backend", "data", "audit_log.json")

_local = threading.local()


def _conn(port):
    c = getattr(_local, "conn", None)
    if c is None:
        c = http.client.HTTPConnection(HOST, port, timeout=30)
        _local.conn = c
    return c


def call(port, path, body):
    data = json.dumps(body)
    t0 = time.perf_counter()
    ok = False
    try:
        c = _conn(port)
        c.request("POST", path, body=data,
                  headers={"Content-Type": "application/json"})
        resp = c.getresponse()
        resp.read()
        ok = resp.status == 200
    except Exception:
        _local.conn = None
    return (time.perf_counter() - t0) * 1000, ok


def pct(sorted_vals, p):
    if not sorted_vals:
        return float("nan")
    return sorted_vals[min(len(sorted_vals) - 1, int(len(sorted_vals) * p / 100))]


def run_phase(port, name, path, body, total, conc, decisions_per_req=1):
    for _ in range(20):
        call(port, path, body)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=conc) as ex:
        results = list(ex.map(lambda _: call(port, path, body), range(total)))
    elapsed = time.perf_counter() - t0

    lat = sorted(r[0] for r in results if r[1])
    errors = sum(1 for r in results if not r[1])
    rps = total / elapsed
    return {
        "name": name, "requests": total, "errors": errors,
        "rps": rps, "decisions_per_sec": rps * decisions_per_req,
        "p50": pct(lat, 50), "p95": pct(lat, 95), "p99": pct(lat, 99),
        "max": lat[-1] if lat else float("nan"),
    }


def check_audit_log():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "backend", "data", "audit_log.jsonl")
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        for l in lines:
            json.loads(l)
        print(f"\nAudit log integrity: {len(lines)} entries, all valid JSON lines")
    except Exception as e:
        print(f"\nAudit log integrity: PROBLEM -> {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--requests", type=int, default=1000)
    args = ap.parse_args()

    try:
        c = http.client.HTTPConnection(HOST, args.port, timeout=5)
        c.request("GET", "/")
        r = c.getresponse()
        r.read()
        print(f"Server reachable on port {args.port} (status {r.status})")
    except Exception as e:
        print(f"Cannot reach server on {HOST}:{args.port} -> {e}")
        print("Start it first (uvicorn tab), then re-run.")
        return

    n, conc, port = args.requests, args.concurrency, args.port
    batch = [ECOM_CTX] * 100

    print(f"Running: {n} requests per phase, concurrency {conc}\n")
    phases = [
        run_phase(port, "simulate x1 (engine only)", "/simulate",
                  {"domain": "ecommerce", "contexts": [ECOM_CTX]}, n, conc),
        run_phase(port, "simulate x100 batch", "/simulate",
                  {"domain": "ecommerce", "contexts": batch}, max(n // 5, 100), conc, 100),
        run_phase(port, "price ecommerce (+audit)", "/price",
                  {"domain": "ecommerce", "context": ECOM_CTX}, n, conc),
        run_phase(port, "price ride_hailing (+audit)", "/price",
                  {"domain": "ride_hailing", "context": RIDE_CTX}, n, conc),
    ]

    hdr = f"{'phase':<30}{'reqs':>6}{'err':>5}{'RPS':>9}{'dec/s':>9}{'p50ms':>8}{'p95ms':>8}{'p99ms':>8}{'maxms':>8}"
    print(hdr)
    print("-" * len(hdr))
    for p in phases:
        print(f"{p['name']:<30}{p['requests']:>6}{p['errors']:>5}{p['rps']:>9.1f}"
              f"{p['decisions_per_sec']:>9.0f}{p['p50']:>8.1f}{p['p95']:>8.1f}"
              f"{p['p99']:>8.1f}{p['max']:>8.1f}")

    check_audit_log()
    print("\nNote: client and server share this one machine, so these numbers are conservative.")


if __name__ == "__main__":
    main()