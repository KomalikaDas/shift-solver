"""The single place where the project talks to the model.

Every call goes through call(), so the required settings (temperature 1.0,
top_p 0.95, thinking disabled) and the X-Item-Id header can't be forgotten.

Two backends, chosen by the LLM_BACKEND setting:
  openrouter (default) - the provided endpoint. This is what the graders re-run.
  ollama               - the same Granite 4.2 8B weights served locally by
                         Ollama. Development only, as the brief allows.
"""
import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SETTINGS = ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "MODEL",
            "LLM_BACKEND", "OLLAMA_URL", "OLLAMA_MODEL")


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
    for key in SETTINGS:
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


_env = load_env()
BACKEND = _env.get("LLM_BACKEND", "openrouter").lower()
MODEL = _env.get("MODEL", "ibm-granite/granite-4.2-8b")
_client = None


def _openrouter(item_id, messages, max_tokens):
    global _client
    if _client is None:
        from openai import OpenAI
        # max_retries=0 on purpose: a silent retry would be an extra call at the
        # graders' proxy and could break the budget. Failures are handled upstream.
        _client = OpenAI(api_key=_env["OPENROUTER_API_KEY"],
                         base_url=_env["OPENROUTER_BASE_URL"],
                         max_retries=0, timeout=180)
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


def _ollama(item_id, messages, max_tokens):
    url = _env.get("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/chat"
    body = {
        "model": _env.get("OLLAMA_MODEL", "granite4.2:8b-q8_0"),
        "messages": messages,
        "stream": False,
        "think": False,  # non-thinking mode, as the brief requires
        "options": {"temperature": 1.0, "top_p": 0.95,
                    "num_predict": max_tokens, "num_ctx": 8192},
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "X-Item-Id": item_id})
    with urllib.request.urlopen(req, timeout=1800) as r:
        text = json.loads(r.read().decode("utf-8"))["message"]["content"] or ""
    # belt and braces: drop any thinking block that slips through
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def call(item_id, messages, max_tokens=3000):
    if BACKEND == "ollama":
        return _ollama(item_id, messages, max_tokens)
    return _openrouter(item_id, messages, max_tokens)
