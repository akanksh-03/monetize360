"""Run from the project root: python -m uvicorn backend.studio.app:app --port 8000"""
from collections import Counter, defaultdict, deque
from copy import deepcopy
from datetime import datetime
import json
import os
import secrets
import threading
import time
import uuid
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .storage import ROOT, Store, fingerprint, now
load_dotenv(ROOT / ".env", override=False)
from . import storage, signals, ml, copilot
from .catalog import config_for, summary
from .core import ENGINE_HASH, evaluate
from .validation import StudioError, name, validate_ruleset

# Reuse the existing application, including any locally-added ML endpoints.
from backend.api.main import app
import pricing_service as legacy_service

store = Store()
store.initialize()
# All legacy and Studio writes use one reentrant lock in the supported single worker.
legacy_service._rules_lock = storage.LOCK
legacy_service.RULES_DIR = str(store.rules)
legacy_service.VERSIONS_DIR = str(store.versions)

app.title = "Monetize360 · Pricing Studio"
router = APIRouter(prefix="/studio-api", tags=["Studio"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Location(StrictModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class PriceInput(StrictModel):
    domain: str = Field(min_length=1, max_length=64)
    context: dict
    evaluation_date: str | None = None
    live_weather: Location | None = None
    predict_demand: bool = False


class BatchInput(StrictModel):
    domain: str
    contexts: list[dict] = Field(min_length=1, max_length=250)
    evaluation_date: str | None = None


class CompareInput(BatchInput):
    candidate: dict


class ConfigInput(StrictModel):
    config: dict


class IntentInput(StrictModel):
    domain: str
    intent: str = Field(min_length=5, max_length=2000)


class ActivationInput(StrictModel):
    acknowledge_conflicts: bool = False


def authenticated(request):
    provided = request.headers.get("authorization", "")
    return provided.startswith("Bearer ") and secrets.compare_digest(provided[7:], store.admin_key)


def require_admin(request):
    if not authenticated(request):
        raise StudioError("Unlock administration with the key printed by studio_setup.py.", "ADMIN_REQUIRED", 401)


WINDOWS = defaultdict(deque)
RATE_LOCK = threading.Lock()


@app.middleware("http")
async def protection(request: Request, call_next):
    path = request.url.path
    is_api = not path.startswith(("/studio/", "/docs", "/openapi.json", "/redoc"))
    request_id = uuid.uuid4().hex[:12]
    if is_api:
        # Uses the socket address, not a spoofable forwarded header. Set an edge
        # rate limiter for hosted deployments; this limiter is single-process.
        ip = request.client.host if request.client else "unknown"
        bucket = "copilot" if "copilot" in path else "api"
        limit = 6 if bucket == "copilot" else int(os.environ.get("MONETIZE_RATE_LIMIT", "180"))
        stamp = time.monotonic()
        with RATE_LOCK:
            times = WINDOWS[(ip, bucket)]
            while times and stamp-times[0] > 60:
                times.popleft()
            if len(times) >= limit:
                return JSONResponse({"detail": "Request limit reached. Retry in a minute.", "code": "RATE_LIMITED"}, 429, headers={"Retry-After": "60"})
            times.append(stamp)
            if len(WINDOWS) > 1000:
                for key in list(WINDOWS):
                    if not WINDOWS[key] or stamp-WINDOWS[key][-1] > 60:
                        WINDOWS.pop(key, None)
        public_writes = {"/price", "/simulate", "/studio-api/price", "/studio-api/compare", "/studio-api/ml/predict"}
        replay = path.startswith("/studio-api/decisions/") and path.endswith("/replay")
        mutates = request.method in {"POST", "PUT", "PATCH", "DELETE"}
        private_read = path in {"/audit", "/studio-api/analytics", "/studio-api/decisions", "/studio-api/export"}
        if ((mutates and path not in public_writes and not replay) or private_read) and not authenticated(request):
            return JSONResponse({"detail": "Administration key required. Unlock editing in the console.", "code": "ADMIN_REQUIRED"}, 401)
        if mutates:
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 512000:
                    return JSONResponse({"detail": "Request exceeds 500 KB.", "code": "BODY_TOO_LARGE"}, 413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if is_api:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(StudioError)
async def studio_error(request, exc):
    return JSONResponse({"detail": str(exc), "code": exc.code}, exc.status)


@app.exception_handler(RequestValidationError)
async def request_error(request, exc):
    # Do not echo full submitted inputs or API keys into errors.
    issues = [{"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse({"detail": "Check the request fields.", "code": "INVALID_REQUEST", "issues": issues}, 422)


def make_price(req):
    start = time.perf_counter()
    config, revision = config_for(store, req.domain)
    context = deepcopy(req.context)
    sources, warnings = {}, []
    if req.live_weather:
        binding = config.get("studio", {}).get("signal_bindings", {}).get("weather")
        if not binding:
            raise StudioError("This domain has no configured weather binding.")
        signal = signals.weather(req.live_weather.latitude, req.live_weather.longitude)
        context[binding] = signal["is_raining"]
        sources[binding] = signal
        if signal["status"] == "stale":
            warnings.append(signal["warning"])
    if req.predict_demand:
        if not config.get("studio", {}).get("demand_adapter"):
            raise StudioError("This domain has no configured demand adapter.")
        prediction = ml.predict(context)
        if prediction.get("anomaly"):
            raise StudioError("The demand inputs are outside the model's calibrated region. Review them or explicitly switch to a manual demand score.", "MODEL_INPUT_ANOMALY")
        context["demand_score"] = prediction["demand_score"]
        sources["demand_score"] = prediction
        if prediction.get("source") == "synthetic_demo":
            warnings.append("Demand prediction comes from a synthetic-data demonstration model.")
    engine_start = time.perf_counter()
    result = evaluate(config, context, req.evaluation_date)
    engine_ms = (time.perf_counter()-engine_start)*1000
    if result["conflict"]:
        warnings.append("Opposing same-priority rules fired. Review the rule ordering before using this decision operationally.")
    receipt = {**result, "decision_id": uuid.uuid4().hex, "created_at": now(), "domain": req.domain,
               "currency": config.get("studio", {}).get("currency", "INR"), "input_context": req.context,
               "resolved_context": context, "config_snapshot": config, "active_revision": revision,
               "sources": sources, "warnings": warnings, "engine_latency_ms": round(engine_ms, 3),
               "latency_ms": round((time.perf_counter()-start)*1000, 3),
               "latency_scope": "resolution + evaluation; excludes audit commit and HTTP overhead"}
    # A successful response always has a committed receipt. No 'audit succeeded' guess.
    store.save_decision(receipt)
    return receipt


@router.get("/health")
def health():
    return {"status": "ok", "engine_hash": ENGINE_HASH, "domains": store.domains(),
            "copilot_configured": bool(os.environ.get("MISTRAL_API_KEY")),
            "ml_mode": "external_adapter" if os.environ.get("MONETIZE_DEMAND_ADAPTER") else "synthetic_demo",
            "storage": "SQLite + versioned JSON", "supported_workers": 1}


@router.get("/admin/check")
def check_admin(request: Request):
    require_admin(request)
    return {"authenticated": True}


@router.get("/domains")
def domains():
    return {"domains": [summary(store, d) for d in store.domains()]}


@router.get("/domains/{domain}")
def domain_details(domain: str):
    return summary(store, domain)


@router.post("/domains")
def import_domain(req: ConfigInput):
    return store.publish(req.config, create=True, action="Imported domain")


@router.post("/price")
def price(req: PriceInput):
    return make_price(req)


@router.get("/weather")
def weather(latitude: float = Query(ge=-90, le=90), longitude: float = Query(ge=-180, le=180)):
    return signals.weather(latitude, longitude)


@router.get("/ml/report")
def model_report():
    return ml.report()


@router.post("/ml/predict")
def model_prediction(context: dict):
    return ml.predict(context)


@router.post("/copilot")
def copilot_rule(req: IntentInput):
    config, _ = config_for(store, req.domain)
    return copilot.propose(config, req.intent)


@router.get("/decisions")
def decisions(domain: str | None = None, limit: int = Query(40, ge=1, le=200), offset: int = Query(0, ge=0)):
    total, rows = store.decisions(domain, limit, offset)
    keys = ("decision_id", "created_at", "domain", "base_price", "final_price", "fired_rules", "conflict", "latency_ms", "warnings", "currency")
    return {"total": total, "offset": offset, "entries": [{k: r[k] for k in keys} for r in rows]}


@router.get("/decisions/{decision_id}")
def decision(decision_id: str, request: Request):
    require_admin(request)
    return store.decision(decision_id)


@router.post("/decisions/{decision_id}/replay")
def replay(decision_id: str):
    old = store.decision(decision_id)
    if old["engine_hash"] != ENGINE_HASH:
        raise StudioError("Engine source changed. Replay requires the original engine version.", "ENGINE_VERSION_CHANGED", 409)
    result = evaluate(old["config_snapshot"], old["resolved_context"], old["evaluation_date"])
    keys = ("final_price", "base_price", "breakdown", "fired_rules", "constraints_applied", "conflict", "steps")
    differences = [k for k in keys if result[k] != old[k]]
    return {"decision_id": decision_id, "identical": not differences, "differences": differences,
            "original_price": old["final_price"], "replayed_price": result["final_price"],
            "evaluation_date": old["evaluation_date"], "external_calls": 0}


@router.get("/analytics")
def analytics(domain: str | None = None):
    total, rows = store.decisions(domain, 2000)
    fired = Counter(rule for r in rows for rule in r["fired_rules"])
    n = len(rows)
    latencies = sorted(r["latency_ms"] for r in rows)
    return {"total_decisions": total, "window_count": n, "window_limit": 2000,
            "conflicts": sum(r["conflict"] for r in rows),
            "constrained": sum(bool(r["constraints_applied"]) for r in rows),
            "warnings": sum(bool(r["warnings"]) for r in rows),
            "average_price": round(sum(r["final_price"] for r in rows)/n, 2) if n else 0,
            "p95_ms": latencies[min(n-1, int(.95*(n-1)))] if n else 0,
            "latency_scope": "resolution + evaluation; excludes audit commit and network",
            "rule_frequency": [{"rule": k, "count": v} for k, v in fired.most_common()],
            "trend": [{"time": r["created_at"], "price": r["final_price"], "base": r["base_price"],
                       "decision_id": r["decision_id"]} for r in reversed(rows[:60])]}


@router.get("/export")
def export(domain: str | None = None):
    _, rows = store.decisions(domain, 5000)
    body = "\n".join(json.dumps(r, allow_nan=False) for r in reversed(rows))
    return Response(body, media_type="application/x-ndjson", headers={"Content-Disposition": 'attachment; filename="monetize360_decisions.jsonl"'})


@router.get("/domains/{domain}/scenarios")
def scenarios(domain: str):
    config, _ = config_for(store, domain)
    fields = config["studio"]["fields"]
    base = {k: f["default"] for k, f in fields.items() if "default" in f}
    contexts = [base]
    for k, field in fields.items():
        variants = field.get("options", [])
        if field["type"] == "boolean":
            variants = [False, True]
        elif field["type"] == "number" and "min" in field and "max" in field:
            variants = [field["min"], (field["min"]+field["max"])/2, field["max"]]
        for value in variants:
            if value == base.get(k):
                continue
            ctx = {**base, k: value}
            try:
                evaluate(config, ctx)
                contexts.append(ctx)
            except StudioError:
                continue
    return {"source": "generated one-attribute scenario grid, not historical transactions", "contexts": contexts[:50]}


@router.post("/compare")
def compare(req: CompareInput):
    config, revision = config_for(store, req.domain)
    candidate = deepcopy(req.candidate)
    if candidate.get("domain") != req.domain:
        raise StudioError("Candidate domain differs from selected domain.")
    candidate.setdefault("studio", deepcopy(config["studio"]))
    validate_ruleset(candidate)
    day = req.evaluation_date or datetime.now(ZoneInfo(config["studio"]["timezone"])).date().isoformat()
    rows, changes = [], []
    for i, ctx in enumerate(req.contexts):
        try:
            current = evaluate(config, ctx, day)
            proposed = evaluate(candidate, ctx, day)
            delta = round(proposed["final_price"]-current["final_price"], 2)
            changes.append(delta)
            rows.append({"case": i+1, "current": current["final_price"], "proposed": proposed["final_price"],
                         "delta": delta, "conflict": proposed["conflict"],
                         "constraints": proposed["constraints_applied"], "fired_rules": proposed["fired_rules"], "error": None})
        except StudioError as e:
            rows.append({"case": i+1, "error": str(e), "code": e.code})
    ordered = sorted(changes)
    n = len(ordered)
    median = (ordered[(n-1)//2]+ordered[n//2])/2 if n else 0
    report = {"cases": len(rows), "valid_cases": n, "errors": len(rows)-n,
              "changed": sum(abs(x) > .001 for x in changes), "median_change": median,
              "largest_absolute_change": max(map(abs, changes), default=0),
              "conflicts": sum(bool(r.get("conflict")) for r in rows),
              "evaluation_date": day, "engine_hash": ENGINE_HASH, "rows": rows,
              "note": "Price comparison on supplied scenarios, not a revenue or causal-lift estimate. Checks do not prove absence of conflicts on unseen contexts."}
    did = store.save_draft(req.domain, revision, candidate, {**report, "contexts": req.contexts})
    return {**report, "draft_id": did, "base_revision": revision, "can_activate": report["errors"] == 0}


@router.post("/drafts/{draft_id}/activate")
def activate(draft_id: str, req: ActivationInput):
    with storage.LOCK:
        draft = store.draft(draft_id)
        if draft["status"] != "draft":
            raise StudioError("This draft was already activated.", "ALREADY_ACTIVATED", 409)
        report = draft["comparison"]
        if report["errors"]:
            raise StudioError("Resolve the failed scenarios and compare again before activation.")
        if report["conflicts"] and not req.acknowledge_conflicts:
            raise StudioError("Conflicts remain in tested scenarios. Review and explicitly acknowledge them before activation.", "CONFLICT_REVIEW_REQUIRED", 409)
        result = store.publish(draft["config"], draft["base_hash"], action=f"Activated tested draft {draft_id[:8]}")
        store.mark_activated(draft_id)
        return result


@router.get("/domains/{domain}/versions")
def versions(domain: str):
    current = store.read(domain)
    entries = store.version_entries(domain)
    return {"domain": domain, "current_hash": fingerprint(current), "versions": [
        {"version": e["version"], "timestamp": e["timestamp"], "action": e["action"],
         "rule_count": len(e["ruleset"]["rules"]), "matches_current": fingerprint(e["ruleset"]) == fingerprint(current)}
        for e in reversed(entries)]}


@router.post("/domains/{domain}/rollback/{version}")
def rollback(domain: str, version: int):
    with storage.LOCK:
        old = store.read(domain)
        entry = next((e for e in store.version_entries(domain) if e["version"] == version), None)
        if not entry:
            raise StudioError("Version not found.", "NOT_FOUND", 404)
        return store.publish(entry["ruleset"], fingerprint(old), action=f"Studio rollback to v{version}")


# Standard /price and /simulate also receive validation, with backwards-compatible
# request shapes. New fields in price responses are additive. Other local endpoints stay.
app.router.routes[:] = [r for r in app.router.routes if not (getattr(r, "path", "") in ("/price", "/simulate") and "POST" in getattr(r, "methods", set()))]


@app.post("/price", tags=["Pricing"])
def compatible_price(req: PriceInput):
    return make_price(req)


@app.post("/simulate", tags=["Pricing"])
def compatible_simulate(req: BatchInput):
    config, _ = config_for(store, req.domain)
    return [evaluate(config, ctx, req.evaluation_date) for ctx in req.contexts]


app.include_router(router)


@app.get("/studio", include_in_schema=False)
def studio_redirect():
    return RedirectResponse("/studio/")


app.mount("/studio", StaticFiles(directory=str(ROOT / "frontend/studio"), html=True), name="studio")
