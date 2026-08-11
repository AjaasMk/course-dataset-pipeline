"""Verify DEEPSEEK_API_KEY is set and usable through the Anthropic-compatible endpoint.

Run: PYTHONPATH=. python scripts/verify_deepseek_key.py

Never prints the key. Mirrors scripts/verify_anthropic_key.py, minus the
count_tokens step -- DeepSeek's compatibility layer does not expose it, so the
cheapest real check is a tiny generation.
"""

import sys

import anthropic
from dotenv import load_dotenv

from src.extract.llm_clients import (
    DEEPSEEK_BASE_URL,
    MissingCredential,
    client_for,
    model_for,
)


def main() -> None:
    load_dotenv()

    try:
        client = client_for("deepseek")
    except MissingCredential as exc:
        print(f"FAIL: {exc}")
        print()
        print("Add this line to .env (which is gitignored):")
        print("  DEEPSEEK_API_KEY=your-key-here")
        sys.exit(1)

    model = model_for("deepseek", "fast")
    print(f"endpoint : {DEEPSEEK_BASE_URL}")
    print(f"model    : {model}  (maps to deepseek-v4-flash)")
    print()
    print("Sending a tiny real request...")

    try:
        # Not a tight max_tokens: DeepSeek always emits a `thinking` block
        # BEFORE the text block and it spends output tokens. At max_tokens=16
        # the reasoning consumed the whole budget and the text block came back
        # empty while the call still reported success.
        response = client.messages.create(
            model=model,
            max_tokens=256,
            messages=[{"role": "user", "content": "Reply with only the word: ready"}],
        )
    except anthropic.AuthenticationError:
        print("FAIL: DEEPSEEK_API_KEY was rejected as invalid.")
        sys.exit(1)
    except anthropic.PermissionDeniedError:
        print("FAIL: key is valid but lacks permission for this model.")
        sys.exit(1)
    except anthropic.APIStatusError as exc:
        detail = (exc.message or "").lower()
        if "balance" in detail or "credit" in detail or "insufficient" in detail:
            print(f"FAIL: no usable balance — {exc.message}")
        else:
            print(f"FAIL: API error {exc.status_code} — {exc.message}")
        sys.exit(1)
    except anthropic.APIConnectionError as exc:
        print(f"FAIL: could not reach {DEEPSEEK_BASE_URL} — {exc}")
        sys.exit(1)

    text = next((b.text for b in response.content if b.type == "text"), "")
    print(f"  OK — model responded: {text.strip()!r}")
    print(f"  usage: input_tokens={response.usage.input_tokens}, "
          f"output_tokens={response.usage.output_tokens}")
    print()
    print("DeepSeek is set up and usable.")


if __name__ == "__main__":
    main()
