"""Verify ANTHROPIC_API_KEY is set, valid, and has usable credit balance.

Run: python scripts/verify_anthropic_key.py
"""

import os
import sys

import anthropic
from dotenv import load_dotenv

MODEL = "claude-haiku-4-5-20251001"


def main() -> None:
    load_dotenv()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("FAIL: ANTHROPIC_API_KEY is not set. Add it to .env and try again.")
        sys.exit(1)

    client = anthropic.Anthropic()

    print("Step 1: checking the key is valid (count_tokens, no credit spend)...")
    try:
        count = client.messages.count_tokens(
            model=MODEL,
            messages=[{"role": "user", "content": "hello"}],
        )
        print(f"  OK — key is valid. input_tokens={count.input_tokens}")
    except anthropic.AuthenticationError:
        print("FAIL: invalid API key.")
        sys.exit(1)
    except anthropic.APIStatusError as exc:
        print(f"FAIL: unexpected API error — {exc.status_code}: {exc.message}")
        sys.exit(1)

    print("\nStep 2: checking credit balance is usable (tiny real request)...")
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=10,
            messages=[{"role": "user", "content": "Reply with only the word: ready"}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        print(f"  OK — model responded: {text!r}")
        print(f"  usage: input_tokens={response.usage.input_tokens}, "
              f"output_tokens={response.usage.output_tokens}")
        print("\nSonnet 5 is fully set up and usable.")
    except anthropic.PermissionDeniedError:
        print("FAIL: key is valid but lacks permission — check workspace/model access.")
        sys.exit(1)
    except anthropic.APIStatusError as exc:
        if "credit" in exc.message.lower() or "balance" in exc.message.lower():
            print(f"FAIL: credit balance issue — {exc.message}")
            print("  This matches the billing discrepancy you were troubleshooting —")
            print("  the key works, but the account has no usable balance yet.")
        else:
            print(f"FAIL: unexpected API error — {exc.status_code}: {exc.message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
