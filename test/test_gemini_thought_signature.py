"""
Test: inspect raw Gemini OpenAI-compatible response for thought_signature.

Usage: python test/test_gemini_thought_signature.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from openai import OpenAI
from config.config_manager import ConfigManager


def main():
    cfg = ConfigManager()
    provider = cfg.config.api_config.llm_provider
    print(f"Current provider: {provider}")

    if provider != "Gemini":
        print("This test is for Gemini. Switching config temporarily...")
        print(f"(Current provider is {provider}, test will still run against Gemini endpoint)")

    # Direct call to Gemini OpenAI-compatible endpoint using actual config
    _provider, model, base_url, api_key = cfg.get_llm_api_config()
    print(f"Model: {model}, Base URL: {base_url}")

    client = OpenAI(api_key=api_key)
    client.base_url = base_url

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Search for 'test' using the mcp_bing_search tool."},
    ]

    tools = [{
        "type": "function",
        "function": {
            "name": "mcp_bing_search",
            "description": "Search the web",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            }
        }
    }]

    print("\n--- Non-streaming call ---")
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        stream=False,
    )

    msg = response.choices[0].message
    tcs = getattr(msg, "tool_calls", []) or []
    print(f"Tool calls: {len(tcs)}")
    for i, tc in enumerate(tcs):
        print(f"  [{i}] id={tc.id} name={tc.function.name}")
        print(f"      arguments={tc.function.arguments}")
        print(f"      has thought_signature attr: {hasattr(tc, 'thought_signature')}")
        if hasattr(tc, 'function'):
            print(f"      function has thought_signature attr: {hasattr(tc.function, 'thought_signature')}")

    # --- Try to access raw response ---
    print("\n--- Raw response inspection ---")
    raw_text = ""
    for attr in ("_raw_http_response", "_response", "http_response", "httpx_response"):
        obj = getattr(response, attr, None)
        if obj is not None:
            print(f"Found raw response at: .{attr}")
            try:
                raw_text = obj.text if hasattr(obj, "text") else str(obj)
                break
            except Exception as e:
                print(f"  Failed to get text: {e}")
        else:
            print(f"  .{attr} = None")

    if not raw_text:
        for meth in ("to_json", "model_dump_json"):
            fn = getattr(response, meth, None)
            if callable(fn):
                try:
                    raw_text = fn()
                    print(f"Got raw via .{meth}()")
                    break
                except Exception as e:
                    print(f"  .{meth}() failed: {e}")

    if raw_text:
        print(f"\nRaw response length: {len(raw_text)} chars")
        try:
            data = json.loads(raw_text)
            raw_tcs = data.get("choices", [{}])[0].get("message", {}).get("tool_calls", [])
            print(f"Raw tool calls: {len(raw_tcs)}")
            for i, tc in enumerate(raw_tcs):
                sig = tc.get("thought_signature")
                fn_sig = tc.get("function", {}).get("thought_signature")
                extra = tc.get("extra_content")
                print(f"  [{i}] thought_signature={sig!r}")
                print(f"      function.thought_signature={fn_sig!r}")
                print(f"      extra_content={json.dumps(extra, indent=6) if extra else None!r}")
                print(f"      all keys: {list(tc.keys())}")
                if "function" in tc:
                    print(f"      function keys: {list(tc['function'].keys())}")
            # Also inspect the full message
            msg_raw = data.get("choices", [{}])[0].get("message", {})
            print(f"\nMessage-level keys: {list(msg_raw.keys())}")
            for k in msg_raw:
                if k not in ("tool_calls", "content"):
                    print(f"  message.{k} = {json.dumps(msg_raw[k], indent=2)[:500]}")
        except Exception as e:
            print(f"Failed to parse raw JSON: {e}")
            print(f"First 500 chars: {raw_text[:500]}")
    else:
        print("\n*** FAILED to access raw response! ***")
        print("This means thought_signature CANNOT be extracted.")
        print("List of response attributes:")
        for attr in dir(response):
            if not attr.startswith("_"):
                print(f"  .{attr}")
            elif attr.startswith("_raw") or attr.startswith("_response"):
                print(f"  .{attr} (private)")


if __name__ == "__main__":
    main()
