#!/usr/bin/env python3
"""DeepSeek prompt translation for comfy-panel (RunningHub mode).
Falls back to identity (no translation) if no API key is configured.
"""
import json
import os
import urllib.request

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
# Key lookup order: env > .env file next to this module
_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _load_key():
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key.strip()
    try:
        with open(_ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


_SYS = (
    "You are a professional translation engine for AI image generation prompts. "
    "Translate the user's Chinese prompt into English for an anime illustration model "
    "(Anima Base). Requirements:\n"
    "1. Keep LoRA trigger words (like jt_style3_v1, jt_char3_v1, jt_style3_v2) verbatim.\n"
    "2. Output ONLY the English prompt text, no explanations, no quotes, no prefix.\n"
    "3. Use standard anime/Danbooru tags, comma separated.\n"
    "4. Do not translate or remove any English words already present."
)


def translate_prompt(chinese_text: str, timeout: int = 30) -> str:
    """Translate Chinese prompt to English via DeepSeek. Returns original text if no key."""
    key = _load_key()
    if not key:
        return chinese_text  # identity fallback

    body = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": _SYS},
            {"role": "user", "content": chinese_text},
        ],
        "max_tokens": 1024,
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            r = json.loads(resp.read().decode("utf-8"))
        out = r["choices"][0]["message"]["content"].strip()
        return out
    except Exception:
        return chinese_text  # fail soft: send original text


if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "一个女孩在花园里"
    print(translate_prompt(t))
