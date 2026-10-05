from copy import deepcopy
import json
from .storage import ROOT, fingerprint


def config_for(store, domain):
    raw = store.read(domain)
    config = deepcopy(raw)
    template = ROOT / "backend/studio/catalogs" / f"rules_{domain}.json"
    if "studio" not in config and template.exists():
        config["studio"] = json.loads(template.read_text(encoding="utf-8")).get("studio", {})
    ui = config.setdefault("studio", {})
    ui.setdefault("label", domain.replace("_", " ").title())
    ui.setdefault("currency", "INR")
    ui.setdefault("timezone", "Asia/Kolkata")
    fields = ui.setdefault("fields", {})
    base = config.get("base_price_field", "base_price")
    fields.setdefault(base, {"label": base.replace("_", " ").title(), "type": "number", "min": 0, "default": 100, "required": True})
    for rule in config["rules"]:
        for c in rule["conditions"]:
            v = c["value"]
            kind = "boolean" if isinstance(v, bool) else "number" if isinstance(v, (int, float)) else "string"
            fields.setdefault(c["field"], {"label": c["field"].replace("_", " ").title(), "type": kind, "default": v})
    constraints = config.get("constraints", {})
    if "max_price_field" in constraints:
        f = constraints["max_price_field"]
        fields.setdefault(f, {"label": f.replace("_", " ").title(), "type": "number", "min": 0, "required": True})
    if "min_price_multiplier_of_cost" in constraints:
        fields.setdefault("cost_price", {"label": "Cost price", "type": "number", "min": 0, "required": True})
    return config, fingerprint(raw)


def summary(store, domain):
    config, revision = config_for(store, domain)
    return {"domain": domain, "label": config["studio"]["label"], "revision": revision,
            "rule_count": len(config["rules"]), "config": config}
