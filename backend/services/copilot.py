import json
import re
from pathlib import Path

import requests
from dotenv import dotenv_values

ENV = Path(__file__).resolve().parents[2] / ".env"
URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-20b"
OPS = {"<", ">", "<=", ">=", "=="}
ACTIONS = {"percent_increase", "percent_decrease", "flat_add", "flat_set"}

SYSTEM = """You turn a business pricing instruction into one JSON pricing rule.
Allowed field names: FIELDS
Allowed operators: <, >, <=, >=, ==
Allowed action types: percent_increase, percent_decrease, flat_add, flat_set
Use only the allowed field names, written exactly as given.
Booleans must be JSON true or false. Numbers must be plain numbers.
Reply with JSON only, in this shape:
{"conditions":[{"field":"is_raining","op":"==","value":true}],"action":{"type":"percent_increase","value":15},"summary":"Increase price by 15% when it is raining"}
Use several conditions when the instruction has several parts (they are combined with AND).
If the instruction cannot be expressed with the allowed fields, reply:
{"error":"short reason"}"""


class CopilotError(Exception):
    pass


def _validate(d, fields):
    if "error" in d:
        raise CopilotError(str(d["error"]))
    conds = d.get("conditions")
    act = d.get("action") or {}
    if not isinstance(conds, list) or not conds:
        raise CopilotError("No condition was found in that instruction.")
    for c in conds:
        if c.get("field") not in fields:
            raise CopilotError(f"Unknown field '{c.get('field')}'. Available: {', '.join(fields)}")
        if c.get("op") not in OPS:
            raise CopilotError("The AI returned an invalid condition.")
        if not isinstance(c.get("value"), (bool, int, float, str)):
            raise CopilotError("The AI returned an invalid value.")
    v = act.get("value")
    if act.get("type") not in ACTIONS or isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
        raise CopilotError("The AI returned an invalid price action.")
    return {"conditions": conds, "action": {"type": act["type"], "value": v}, "summary": str(d.get("summary", ""))}


def text_to_rule(text, fields):
    key = (dotenv_values(ENV).get("GROQ_API_KEY") or "").strip()
    if not key:
        raise CopilotError("GROQ_API_KEY is missing from the .env file.")
    body = {
        "model": MODEL,
        "reasoning_effort": "low",
        "temperature": 0,
        "max_tokens": 1500,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM.replace("FIELDS", ", ".join(fields))},
            {"role": "user", "content": text},
        ],
    }
    try:
        r = requests.post(URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=30)
    except requests.RequestException:
        raise CopilotError("Could not reach the AI service.")
    if r.status_code == 429:
        raise CopilotError("The AI service is busy. Try again in a minute.")
    if r.status_code != 200:
        raise CopilotError(f"The AI service returned an error ({r.status_code}).")
    raw = r.json()["choices"][0]["message"].get("content") or ""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise CopilotError("The AI reply could not be read.")
    try:
        return _validate(json.loads(m.group(0)), fields)
    except json.JSONDecodeError:
        raise CopilotError("The AI reply could not be read.")