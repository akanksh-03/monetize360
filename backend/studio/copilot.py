"""Mistral proposes a rule. It never activates a strategy or calculates a fare."""
from copy import deepcopy
import json
import os
import httpx
from .validation import StudioError, validate_ruleset

RULE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "id": {"type": "string"}, "description": {"type": "string"},
        "priority": {"type": "integer"},
        "conditions": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "properties": {"field": {"type": "string"}, "op": {"type": "string", "enum": ["<", ">", "<=", ">=", "=="]},
                           "value": {"anyOf": [{"type": "number"}, {"type": "string"}, {"type": "boolean"}]}},
            "required": ["field", "op", "value"]}},
        "action": {"type": "object", "additionalProperties": False,
            "properties": {"type": {"type": "string", "enum": ["percent_increase", "percent_decrease", "flat_add", "flat_set"]},
                           "value": {"type": "number"}}, "required": ["type", "value"]},
        "effective_from": {"type": ["string", "null"]}, "effective_to": {"type": ["string", "null"]}
    }, "required": ["id", "description", "priority", "conditions", "action", "effective_from", "effective_to"]}


def propose(config, intent):
    key = os.environ.get("MISTRAL_API_KEY")
    if not key:
        raise StudioError("MISTRAL_API_KEY is not configured. Add your actual key to the existing .env file and restart. The manual rule builder works without a key.", "COPILOT_NOT_CONFIGURED", 503)
    fields = config.get("studio", {}).get("fields", {})
    prompt = ("Translate the user's pricing intent into ONE draft JSON pricing rule. Use only these fields and their units/ranges: "
              + json.dumps(fields) + ". All conditions use AND. Do not invent a field, an API, a formula, or a numerical business assumption. "
              "If the request is ambiguous or cannot be expressed, return rule=null and ask a concise clarification. "
              "Use null for unspecified effective dates. Existing IDs (new ID must differ): "
              + json.dumps([r["id"] for r in config["rules"]]))
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"rule": {"anyOf": [RULE_SCHEMA, {"type": "null"}]}, "explanation": {"type": "string"}},
              "required": ["rule", "explanation"]}
    try:
        response = httpx.post("https://api.mistral.ai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
            json={"model": os.environ.get("MISTRAL_MODEL", "mistral-small-latest"), "temperature": 0,
                  "max_tokens": 1200, "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": intent}],
                  "response_format": {"type": "json_schema", "json_schema": {"name": "pricing_draft", "strict": True, "schema": schema}}},
            timeout=20)
        if response.status_code in (401, 403):
            raise StudioError("Mistral rejected the key or model access. Check your account configuration.", "COPILOT_AUTH", 503)
        if response.status_code == 429:
            raise StudioError("Mistral quota or rate limit reached. Retry later; the manual builder remains available.", "COPILOT_RATE_LIMIT", 429)
        response.raise_for_status()
        result = json.loads(response.json()["choices"][0]["message"]["content"])
        if not isinstance(result, dict) or not isinstance(result.get("explanation"), str):
            raise ValueError("Invalid response structure")
        rule = result.get("rule")
        if rule is None:
            return {"rule": None, "explanation": result["explanation"], "status": "needs_clarification"}
        candidate = deepcopy(config)
        candidate["rules"].append(rule)
        validate_ruleset(candidate)
        for condition in rule["conditions"]:
            if condition["field"] not in fields:
                raise StudioError("Copilot used an unknown attribute; revise the instruction.", "INVALID_AI_DRAFT")
            spec, v = fields[condition["field"]], condition["value"]
            if spec["type"] == "number" and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < spec.get("min", -float("inf")) or v > spec.get("max", float("inf"))):
                raise StudioError("Copilot used a threshold outside the attribute's range; check units.", "INVALID_AI_DRAFT")
        return {"rule": rule, "explanation": result["explanation"], "status": "draft_only"}
    except StudioError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError, ImportError) as e:
        raise StudioError("Mistral did not return a usable rule. Nothing was activated; revise the instruction or use the form.", "COPILOT_UNAVAILABLE", 503) from e
