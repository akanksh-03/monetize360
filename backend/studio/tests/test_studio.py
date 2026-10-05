"""Integration checks using isolated temporary rules, versions and SQLite storage."""
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
AUTH = {"Authorization": "Bearer studio-integration-test-only"}
EC = {"base_price": 800, "inventory_pct": .15, "demand_score": .3, "customer_segment": "regular", "mrp": 1000, "cost_price": 550}
RH = {"base_fare": 100, "demand_supply_ratio": 1.8, "is_raining": True, "is_rush_hour": False}


@pytest.fixture(scope="session")
def runtime(tmp_path_factory):
    work = tmp_path_factory.mktemp("studio-isolated")
    settings = {"MONETIZE_STUDIO_DATA": str(work / "data"), "MONETIZE_RULES_DIR": str(work / "rules"),
                "MONETIZE_VERSIONS_DIR": str(work / "versions"), "MONETIZE_ADMIN_KEY": "studio-integration-test-only", "MONETIZE_RATE_LIMIT": "10000"}
    prior = {k: os.environ.get(k) for k in settings}
    os.environ.update(settings)
    mod = importlib.import_module("backend.studio.app")
    with TestClient(mod.app) as client:
        yield client, mod
    for k, v in prior.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def client(runtime):
    client, app = runtime
    app.WINDOWS.clear()
    app.signals.CACHE.clear()
    for path in app.store.rules.glob("rules_*.json"):
        path.unlink()
    shutil.rmtree(app.store.versions, ignore_errors=True)
    app.store.initialize()
    with app.store.db() as db:
        for table in ["decisions", "drafts", "events"]:
            db.execute("DELETE FROM "+table)
    return client


CASES = json.loads((ROOT / "backend/tests/test_cases.json").read_text(encoding="utf-8"))
GOLDEN = [(domain, c) for domain, cases in CASES.items() for c in cases]


@pytest.mark.parametrize("domain,case", GOLDEN, ids=[c["test_id"] for _, c in GOLDEN])
def test_original_golden_cases(client, domain, case):
    response = client.post("/price", json={"domain": domain, "context": case["input"]})
    assert response.status_code == 200, response.text
    r = response.json()
    expected = case.get("expected_final_price", case.get("expected_final_fare"))
    assert abs(r["final_price"]-expected) < .01
    assert abs(r["base_price"]+sum(s["delta"] for s in r["steps"])-r["final_price"]) < 1e-8
    assert r["decision_id"]


def test_infeasible_floor_cannot_override_mrp(client):
    r = client.post("/price", json={"domain": "ecommerce", "context": {**EC, "cost_price": 980}})
    assert r.status_code == 422
    assert r.json()["code"] == "INFEASIBLE_BOUNDS"


@pytest.mark.parametrize("ctx", [{**EC, "base_price": True}, {**EC, "inventory_pct": "low"},
    {k: v for k, v in EC.items() if k != "mrp"}, {**EC, "demand_score": 2}, {**EC, "base_price": -1}])
def test_invalid_input(client, ctx):
    r = client.post("/price", json={"domain": "ecommerce", "context": ctx})
    assert r.status_code == 422
    assert r.json()["detail"]


def test_waterfall_includes_constraint(client):
    r = client.post("/price", json={"domain": "ecommerce", "context": {**EC, "base_price": 1000, "demand_score": .9}}).json()
    assert r["final_price"] == 1000
    assert any(s["kind"] == "constraint" and s["delta"] < 0 for s in r["steps"])


def test_date_frozen_replay_survives_rule_changes(client, runtime):
    _, mod = runtime
    cfg = mod.store.read("ecommerce")
    cfg["rules"].append({"id": "future", "conditions": [], "action": {"type": "flat_add", "value": 20},
                         "priority": 10, "effective_from": "2030-01-01", "effective_to": "2030-01-31"})
    mod.store.publish(cfg)
    r = client.post("/price", json={"domain": "ecommerce", "context": EC, "evaluation_date": "2030-01-10"}).json()
    assert r["final_price"] == 884
    cfg["rules"] = []
    mod.store.publish(cfg)
    replay = client.post(f"/studio-api/decisions/{r['decision_id']}/replay").json()
    assert replay["identical"] and replay["external_calls"] == 0
    assert replay["replayed_price"] == 884


def test_changed_engine_refuses_replay(client, runtime, monkeypatch):
    _, mod = runtime
    r = client.post("/price", json={"domain": "ride_hailing", "context": RH}).json()
    monkeypatch.setattr(mod, "ENGINE_HASH", "changed")
    assert client.post(f"/studio-api/decisions/{r['decision_id']}/replay").status_code == 409


def test_admin_guards_old_and_new_mutations(client):
    assert client.post("/rules/ecommerce", json={}).status_code == 401
    assert client.post("/studio-api/domains", json={}).status_code == 401
    assert client.get("/studio-api/decisions").status_code == 401
    assert client.get("/studio-api/admin/check", headers=AUTH).status_code == 200


def test_fourth_domain_without_code_changes(client):
    cfg = json.loads((ROOT / "demo_staging/studio_parking.json").read_text())
    r = client.post("/studio-api/domains", json={"config": cfg}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert "occupancy" in client.get("/studio-api/domains/parking").json()["config"]["studio"]["fields"]
    result = client.post("/price", json={"domain": "parking", "context": {"base_price": 60, "occupancy": .9, "event_active": True}})
    assert result.json()["final_price"] == 95
    assert client.post("/studio-api/domains", json={"config": cfg}, headers=AUTH).status_code == 409


def test_unsupported_operator_rejected(client):
    cfg = client.get("/studio-api/domains/hotel").json()["config"]
    cfg["domain"] = "bad_hotel"
    cfg["rules"][0]["conditions"][0]["op"] = "execute"
    assert client.post("/studio-api/domains", json={"config": cfg}, headers=AUTH).status_code == 422


def candidate(client):
    cfg = client.get("/studio-api/domains/ecommerce").json()["config"]
    cfg["rules"][0]["action"]["value"] = 10
    return client.post("/studio-api/compare", json={"domain": "ecommerce", "candidate": cfg, "contexts": [EC]}).json()


def test_comparison_is_non_destructive_and_stale_activation_blocked(client, runtime):
    _, mod = runtime
    before = mod.storage.fingerprint(mod.store.read("ecommerce"))
    r = candidate(client)
    assert r["rows"][0]["current"] == 864 and r["rows"][0]["proposed"] == 880
    assert before == mod.storage.fingerprint(mod.store.read("ecommerce"))
    cfg = mod.store.read("ecommerce")
    cfg["rules"][0]["action"]["value"] = 9
    mod.store.publish(cfg)
    response = client.post(f"/studio-api/drafts/{r['draft_id']}/activate", json={}, headers=AUTH)
    assert response.status_code == 409
    assert response.json()["code"] == "STALE_DRAFT"


def test_activation_then_rollback(client):
    r = candidate(client)
    assert client.post(f"/studio-api/drafts/{r['draft_id']}/activate", json={}, headers=AUTH).status_code == 200
    assert client.post("/price", json={"domain": "ecommerce", "context": EC}).json()["final_price"] == 880
    restore = client.post("/studio-api/domains/ecommerce/rollback/1", headers=AUTH)
    assert restore.json()["version"] == 3
    assert client.post("/price", json={"domain": "ecommerce", "context": EC}).json()["final_price"] == 864


def test_failed_scenarios_block_activation(client):
    cfg = client.get("/studio-api/domains/ecommerce").json()["config"]
    cfg["constraints"]["min_price_multiplier_of_cost"] = 3
    r = client.post("/studio-api/compare", json={"domain": "ecommerce", "candidate": cfg, "contexts": [EC]}).json()
    assert r["errors"] == 1 and not r["can_activate"]
    assert client.post(f"/studio-api/drafts/{r['draft_id']}/activate", json={}, headers=AUTH).status_code == 422


def test_conflict_requires_acknowledgement(client):
    cfg = client.get("/studio-api/domains/ecommerce").json()["config"]
    cfg["rules"].append({"id": "opposing", "priority": 1, "conditions": [], "action": {"type": "percent_decrease", "value": 5}})
    r = client.post("/studio-api/compare", json={"domain": "ecommerce", "candidate": cfg, "contexts": [EC]}).json()
    assert r["conflicts"] == 1
    assert client.post(f"/studio-api/drafts/{r['draft_id']}/activate", json={}, headers=AUTH).status_code == 409
    assert client.post(f"/studio-api/drafts/{r['draft_id']}/activate", json={"acknowledge_conflicts": True}, headers=AUTH).status_code == 200


def test_weather_outage_not_silently_no_rain(client, runtime, monkeypatch):
    _, mod = runtime
    def fail(*a, **kw):
        raise mod.signals.httpx.ConnectError("offline")
    monkeypatch.setattr(mod.signals.httpx, "get", fail)
    r = client.post("/price", json={"domain": "ride_hailing", "context": RH, "live_weather": {"latitude": 15.3, "longitude": 75.1}})
    assert r.status_code == 503
    assert r.json()["code"] == "WEATHER_UNAVAILABLE"


def test_live_signal_provenance(client, runtime, monkeypatch):
    _, mod = runtime
    response = mod.signals.httpx.Response(200, json={"current": {"rain": 1.2, "showers": 0,
        "weather_code": 61, "time": int(time.time()), "interval": 900}}, request=mod.signals.httpx.Request("GET", "https://api.open-meteo.com"))
    monkeypatch.setattr(mod.signals.httpx, "get", lambda *a, **k: response)
    r = client.post("/price", json={"domain": "ride_hailing", "context": {**RH, "is_raining": False}, "live_weather": {"latitude": 15.3, "longitude": 75.1}}).json()
    assert r["final_price"] == 149.5
    assert r["resolved_context"]["is_raining"] is True and r["input_context"]["is_raining"] is False
    assert r["sources"]["is_raining"]["provider"] == "Open-Meteo"


def test_settlement_not_falsely_verified(client):
    r = client.post("/price", json={"domain": "ride_hailing", "context": RH}).json()
    assert r["settlement"]["status"] == "not_supplied"
    assert client.post("/price", json={"domain": "ride_hailing", "context": {**RH, "driver_payout": 1}}).status_code == 422


def test_numpy_model_and_evaluation_report(client):
    r = client.get("/studio-api/ml/report").json()
    assert r["source"] == "synthetic_demo" and len(r["candidates"]) == 3
    assert r["test_metrics"]["mae"] < r["test_metrics"]["mean_baseline_mae"]
    response = client.post("/price", json={"domain": "ecommerce", "context": {**EC, "traffic_index": .65,
        "promotion": False, "competitor_price_ratio": 1, "hour": 17}, "predict_demand": True})
    assert response.status_code == 200, response.text
    assert response.json()["sources"]["demand_score"]["source"] == "synthetic_demo"


def test_anomaly_gate(client):
    r = client.post("/price", json={"domain": "ecommerce", "context": {**EC, "traffic_index": .65,
        "promotion": False, "competitor_price_ratio": 5, "hour": 17}, "predict_demand": True})
    assert r.status_code == 422 and r.json()["code"] == "MODEL_INPUT_ANOMALY"


def test_mistral_missing_key(client, monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    r = client.post("/studio-api/copilot", json={"domain": "ecommerce", "intent": "Discount loyal customers"}, headers=AUTH)
    assert r.status_code == 503 and r.json()["code"] == "COPILOT_NOT_CONFIGURED"


def test_mistral_response_is_draft_only(client, runtime, monkeypatch):
    _, mod = runtime
    monkeypatch.setenv("MISTRAL_API_KEY", "unit-test-not-a-real-key")
    rule = {"id": "ai_draft", "description": "Loyalty adjustment", "priority": 4,
        "conditions": [{"field": "customer_segment", "op": "==", "value": "loyalty"}],
        "action": {"type": "percent_decrease", "value": 3}, "effective_from": None, "effective_to": None}
    response = mod.copilot.httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"rule": rule, "explanation": "Draft"})}}]}, request=mod.copilot.httpx.Request("POST", "https://api.mistral.ai"))
    monkeypatch.setattr(mod.copilot.httpx, "post", lambda *a, **kw: response)
    before = mod.storage.fingerprint(mod.store.read("ecommerce"))
    r = client.post("/studio-api/copilot", json={"domain": "ecommerce", "intent": "Discount loyalty by 3 percent"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "draft_only"
    assert before == mod.storage.fingerprint(mod.store.read("ecommerce"))


def test_concurrent_pricing_audit(client):
    def call(_):
        return client.post("/price", json={"domain": "ride_hailing", "context": RH})
    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(call, range(15)))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["decision_id"] for r in responses}) == 15
    assert client.get("/studio-api/decisions?domain=ride_hailing", headers=AUTH).json()["total"] == 15
    assert client.get("/studio-api/analytics?domain=ride_hailing", headers=AUTH).json()["window_count"] == 15


def test_rate_and_body_limits(client, runtime, monkeypatch):
    _, mod = runtime
    monkeypatch.setenv("MONETIZE_RATE_LIMIT", "2")
    assert client.get("/studio-api/health").status_code == 200
    assert client.get("/studio-api/health").status_code == 200
    assert client.get("/studio-api/health").status_code == 429
    mod.WINDOWS.clear()
    assert client.post("/price", content=b"x"*512001, headers={"Content-Type": "application/json"}).status_code == 413


def test_console_assets(client):
    assert "Every price, explained." in client.get("/studio/").text
    assert client.get("/studio/studio.js").status_code == 200
    assert client.get("/studio/studio.css").status_code == 200
