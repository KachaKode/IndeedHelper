"""Print the chat models this API key can actually use, best first.

Which models an account can reach varies, so rather than guessing a name and
finding out at 2am mid-run, ask. Writes nothing; just prints.

    venv\\Scripts\\python.exe tools\\list_models.py

Put the one you want in input/model.txt (a single line), or set
INDEEDHELPER_MODEL. myGPT2.configured_model() reads them in that order.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import openai  # noqa: E402
from myGPT2 import configured_model  # noqa: E402


def load_key() -> str:
    for candidate in (ROOT / "input" / "api_key.txt", ROOT / "api_key.txt"):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()
    raise SystemExit("No input/api_key.txt found.")


# Newest and most capable first. Anything the account exposes that is not on
# this list still gets printed, just below the ranked ones.
PREFERENCE = [
    "gpt-5", "gpt-5-mini", "gpt-5-nano",
    "gpt-4.1", "gpt-4.1-mini",
    "gpt-4o", "gpt-4o-mini",
    "gpt-4-turbo", "gpt-4",
]

SKIP = ("embedding", "whisper", "tts", "dall-e", "moderation", "audio",
        "realtime", "transcribe", "image", "search", "codex")


def main() -> int:
    openai.api_key = load_key()
    print(f"currently configured: {configured_model()}\n")

    try:
        models = openai.Model.list()
    except Exception as exc:                       # noqa: BLE001
        print(f"Could not list models: {type(exc).__name__}: {exc}")
        print("\nThe key may be invalid, out of credit, or the SDK too old for this account.")
        return 1

    names = sorted({m["id"] for m in models["data"]})
    chat = [n for n in names if not any(s in n.lower() for s in SKIP)]

    ranked, rest = [], []
    for name in chat:
        base = name.split("-20")[0]                # strip a dated suffix
        if base in PREFERENCE:
            ranked.append((PREFERENCE.index(base), name))
        else:
            rest.append(name)
    ranked.sort()

    print("--- usable chat models, best first ---")
    for _, name in ranked:
        print(f"   {name}")
    if ranked:
        print(f"\nSuggested: echo {ranked[0][1]} > input/model.txt")
    else:
        print("   (none of the preferred models are available on this key)")

    if rest:
        print("\n--- other models this key exposes ---")
        for name in rest:
            print(f"   {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
