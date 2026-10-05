# Monetize360 Studio — architecture and operation

## Integration boundary

Run `backend.studio.app:app` from the existing project root. This imports your original `backend.api.main.app`. Local routes such as your existing ML API remain registered. The wrapper replaces only the runtime `/price` and `/simulate` POST registrations; source files are unchanged. It adds a `/studio-api` API and `/studio/` UI.

The wrapper calls the original `rule_matches`, `calculate_price`, `apply_action`, and `apply_constraints`. For replay, it matches rules using the saved date, removes effective-date gates from a temporary copy of the already matched rules, and invokes the original engine. It neither reimplements condition matching nor edits `engine.py`. Ties retain their existing stable configuration order.

The dependency on the existing app is intentional. The installer cannot verify code that is only present on your Windows computer; run the included tests after installing in that local project.

## Files and responsibilities

| Module | Responsibility |
| --- | --- |
| `backend/studio/app.py` | API routes, admin checks, request limits, orchestration and mounting the UI |
| `validation.py` | Accepted operators/actions, context typing, date validation and feasible bounds |
| `core.py` | Original-engine adapter, reproducible dates, detailed waterfall and settlement checks |
| `storage.py` | SQLite receipts/drafts/events; atomic active JSON replacement and version snapshots |
| `catalog.py` | Configuration metadata and generic field inference |
| `signals.py` | Open-Meteo fetch, caching, provenance and unavailable/stale handling |
| `ml.py` | Portable NumPy inference, anomaly scoring and optional external adapter |
| `copilot.py` | Mistral structured draft generation and independent validation |
| `frontend/studio/` | HTML/CSS/JS console, schema-driven forms and SVG/CSS charts; no CDN/build step |

Domain metadata lives in a `studio` object alongside the existing `rules`, `base_price_field`, and `constraints`. Existing rules without this metadata receive UI metadata from the supplied domain templates, then generic inference for unknown fields. New imported packages can provide all attributes explicitly. The original engine ignores this extra metadata.

## Stored evidence

Every successful Studio price request commits a SQLite receipt before returning. A receipt contains the input and resolved context, full configuration snapshot, configuration SHA-256, engine SHA-256, evaluation date and timezone, external signal metadata, prediction version, rule effects, constraint effects, rounding, warning flags, and result.

Hashes identify versions; they are not digital signatures or tamper-proof audit certification. Preserve and back up the database. An operator with filesystem access could change it.

Old `backend/data/audit_log.jsonl` records remain untouched. Studio analytics use the new SQLite receipts, including calls to the wrapped `/price`. `/simulate` and strategy comparisons are simulations and do not appear as priced transactions. Drafts and activation events are recorded separately.

The in-app P95 statistic covers context resolution plus engine evaluation, excluding audit commit and HTTP overhead. `benchmark_studio.py` measures the actual HTTP round trip including the commit. Report the correct scope to judges.

## Safety and supported scope

- Run **one Uvicorn worker**. The file write lock and rate limiter are process-local. Multiple processes or replicas require a transactional shared configuration store and shared rate limiter.
- SQLite stores receipts, drafts and activation events. Active configurations and legacy-compatible versions remain JSON files to preserve your existing workflow. Cross-file publication and SQLite events are not a distributed transaction.
- Bounds are validated before pricing; contradictory lower/upper bounds return `INFEASIBLE_BOUNDS`. Missing required ceiling/cost inputs are rejected.
- The original engine's conflict definition is preserved: matching opposite-direction actions at the same priority. It does not prove every possible ambiguity has been found. Scenario checks are not exhaustive formal verification.
- `driver_payout_floor` is evaluated as a separate settlement check. If no actual payout is supplied, the interface explicitly says settlement is not verified. No payment is executed.
- Administration is a single shared bearer key kept in browser memory. This is suitable for a controlled demonstration, not a multi-tenant identity/roles system.
- Read-only public simulation is available. Rule mutations, activation, rollback, copilot calls, audit lists and analytics require the key. The original application's additional routes should also be reviewed before exposing a customized local app publicly.
- Imported configuration supports the original engine's four action types and five comparison operators. Arbitrary formulas, OR trees, billing tiers and real payment settlement are not added by this update.

## Environment variables

| Variable | Behaviour |
| --- | --- |
| `MISTRAL_API_KEY` | Actual provider key, read from existing `.env` or server environment; optional |
| `MISTRAL_MODEL` | Model available to that key; defaults to `mistral-small-latest` |
| `MONETIZE_ADMIN_KEY` | Server-managed administrator secret. If absent locally, setup generates and stores one privately. |
| `MONETIZE_STUDIO_DATA` | SQLite, local key and runtime directory; default `.monetize-studio` in the project |
| `MONETIZE_RULES_DIR` | Active JSON configurations; default existing `backend/data/rules` |
| `MONETIZE_VERSIONS_DIR` | Version snapshots; default existing `backend/data/versions` |
| `MONETIZE_RATE_LIMIT` | General requests per minute per socket client address; default 180 |
| `MONETIZE_DEMAND_ADAPTER` | Optional `module.path:function_name` for your existing demand model |

The copilot limit is six requests per minute per socket address. A reverse proxy may present one address for many users; configure an edge rate limiter for a public deployment. Do not trust arbitrary forwarded IP headers.

## Connecting an existing demand model

The existing local model code was not published, so this update does not guess its loading or prediction function names. The ready-to-run portable demonstration stays separate in `backend/studio`.

To connect your actual trained model, create a small adapter in your own `backend/ml` that exposes this callable contract:

```python
def predict_for_studio(context: dict) -> dict:
    # Call your existing, already-working feature preparation and model inference.
    # Return its real numerical score and actual model version.
    return {
        "demand_score": score,
        "model_version": version,
        "anomaly": anomaly_flag,
    }
```

`score`, `version`, and `anomaly_flag` above represent values produced by your existing code; this is an interface contract, not a standalone runnable replacement. The rest of the update runs without this adapter.

Set `MONETIZE_DEMAND_ADAPTER` to that module and callable, for example `backend.ml.studio_adapter:predict_for_studio` **only after that file and function actually exist**. Restart Studio. It then uses the real adapter and hides the portable model's metrics rather than attributing them to your model. The score must be finite and between 0 and 1. Never load an untrusted pickle uploaded by a visitor.

## A complete new-domain configuration

Use `demo_staging/studio_parking.json` as the working example. Its default scenario is:

```json
{"base_price": 60, "occupancy": 0.9, "event_active": true}
```

The first rule adds 25%, giving 75. The next adds 20, giving 95. Its 2× cap is 120, so the final result is 95. The labels, field types and values come from the package, not from edits to the UI.

## API examples

The standard request remains compatible:

```json
{
  "domain": "ride_hailing",
  "context": {
    "base_fare": 100,
    "demand_supply_ratio": 1.8,
    "is_raining": true,
    "is_rush_hour": false
  }
}
```

Send to `POST /price` or `POST /studio-api/price`. Optional fields on the same body are `evaluation_date`, `predict_demand`, and `live_weather` (an object with numeric `latitude` and `longitude`). Historical replay never calls the live signal provider again. Supplying a past evaluation date does not turn a newly fetched live weather response into historical weather; its actual source timestamp remains recorded.

| Endpoint | Purpose |
| --- | --- |
| `GET /studio-api/health` | Readiness, domains, configured integration flags |
| `GET /studio-api/domains` | Full domain catalog and UI schemas |
| `POST /studio-api/domains` | Import a new domain; administrator required |
| `POST /studio-api/price` | Resolve optional context and record a price |
| `POST /studio-api/compare` | Compare candidate/current configs on 1–250 contexts |
| `POST /studio-api/drafts/{id}/activate` | Approve a tested, non-stale draft; administrator required |
| `GET /studio-api/decisions` | Paginated receipt summaries; administrator required |
| `GET /studio-api/decisions/{id}` | Full saved receipt; administrator required |
| `POST /studio-api/decisions/{id}/replay` | Replay a receipt with original evidence |
| `GET /studio-api/analytics` | Recent-window aggregate metrics; administrator required |
| `GET /studio-api/export` | Latest up to 5,000 receipts as JSONL; administrator required |
| `GET /studio-api/domains/{domain}/versions` | Legacy-compatible strategy history |
| `POST /studio-api/domains/{domain}/rollback/{version}` | Restore as a new version; administrator required |
| `GET /studio-api/ml/report` | Actual bundled model evaluation or external-adapter status |
| `POST /studio-api/copilot` | Optional Mistral rule proposal; administrator required |

The interactive schema is at `/docs`. Secrets are not included in API responses. Rule configuration is public in this demo; do not put secrets in rule metadata.

## Deployment instructions

No account was accessed and no site was deployed when preparing this package. Test locally before deploying your updated repository. Add all new code and domain files to git; do not commit the environment, keys, or runtime database.

For Render or another Python web-service host:

1. Connect your own repository and choose its updated branch.
2. Build command: `pip install -r requirements.txt -r requirements-studio.txt`.
3. Startup command: `uvicorn backend.studio.app:app --host 0.0.0.0 --port $PORT --workers 1`.
4. Set a strong `MONETIZE_ADMIN_KEY` using the host's secret manager. Add your real Mistral variables only if enabling it.
5. Open the deployment URL followed by `/studio/`. All frontend calls use that same origin.
6. To persist this file-backed architecture, attach actual persistent storage. For a disk mounted at `/var/data`, set `MONETIZE_STUDIO_DATA=/var/data/studio`, `MONETIZE_RULES_DIR=/var/data/rules`, and `MONETIZE_VERSIONS_DIR=/var/data/versions`. Initialization seeds missing configurations from your project, then templates; it preserves existing persistent files.

Render's free web-service filesystem is ephemeral. A free deployment is a resettable demonstration: its mutations, database and history can disappear on restart/spin-down. Free services do not support a persistent disk. This update does **not** implement a PostgreSQL backend, so do not enter a PostgreSQL URL and expect it to work. Durable free-tier deployment would require a separate database migration; do not claim it is included. Local execution remains durable on your own disk.

Sources: [Render free-instance limitations](https://render.com/docs/free), [Render persistent disks](https://render.com/docs/disks).

## Research and claims for the presentation

Keep the existing researched limits and distinguish configured business assumptions from legal obligations and measured business outcomes.

- [Open-Meteo documentation](https://open-meteo.com/en/docs): current information is weather-model output. Show source time, cache/stale status and attribution. Free API usage is non-commercial; see [terms](https://open-meteo.com/en/terms).
- [Mistral structured output](https://docs.mistral.ai/studio/conversations/structured-output/custom): schemas help structure output; independent validation and user approval still apply.
- [Hotel booking demand datasets](https://doi.org/10.1016/j.dib.2018.11.126): primary hospitality research covering real city/resort bookings. This code does not claim those records trained the bundled synthetic model or that booking counts equal occupancy without room inventory.
- [Government explanation of MVAG 2025](https://eparlib.sansad.in/bitstream/123456789/2992953/1/lsd_18_V_07-08-2025.pdf): the central guideline distinguishes driver-owned and aggregator-owned vehicles for payout percentages. The supplied 0.80 configuration is an illustrative driver-owned setting; applicable state requirements and business arrangements need their own configuration.
- [Department of Consumer Affairs FAQ](https://consumeraffairs.nic.in/sites/default/files/file-uploads/latestnews/LM_FAQs.pdf): scope MRP claims to covered packaged commodities instead of every possible e-commerce service.

Do not present a scenario price increase as measured revenue lift. Do not describe synthetic validation scores as accuracy on real transaction data. Do demonstrate the original golden cases, saved evidence, a live signal, model-selection evidence, and configuration-only domain import.
