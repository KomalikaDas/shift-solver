"""The single place where the project talks to the model.

Every call goes through call(), so the required settings and the
X-Item-Id header can't be forgotten anywhere else.
"""
import os
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parent


def load_env():
    env = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    # Real environment variables win, so the graders can point it elsewhere.
    for key in ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "MODEL"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


_env = load_env()
MODEL = _env.get("MODEL", "ibm-granite/granite-4.2-8b")

# max_retries=0 on purpose: a silent retry would be an extra call at the
# graders' proxy and could break the budget. Failures are handled upstream.
_client = OpenAI(
    api_key=_env["OPENROUTER_API_KEY"],
    base_url=_env["OPENROUTER_BASE_URL"],
    max_retries=0,
    timeout=180,
)


def call(item_id, messages, max_tokens=3000):
    resp = _client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=1.0,
        top_p=0.95,
        max_tokens=max_tokens,
        extra_body={"reasoning": {"enabled": False}},
        extra_headers={"X-Item-Id": item_id},
    )
    return resp.choices[0].message.content or ""