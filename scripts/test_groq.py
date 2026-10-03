import requests
from pathlib import Path
from dotenv import dotenv_values

env = dotenv_values(Path(__file__).resolve().parent.parent / ".env")
key = (env.get("GROQ_API_KEY") or "").strip()
print("Key found:", bool(key), "| length:", len(key))

r = requests.post(
    "https://api.groq.com/openai/v1/chat/completions",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    json={"model": "openai/gpt-oss-20b",
          "messages": [{"role": "user", "content": "Reply with the word OK"}]},
    timeout=30,
)
print(r.status_code)
print(r.text[:300])