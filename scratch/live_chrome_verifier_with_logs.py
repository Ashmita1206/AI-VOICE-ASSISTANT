"""
Live Server SSE Pipeline + Auto-Confirm Verifier
=================================================

Submits text commands to http://127.0.0.1:5000/transcribe_stream.
If confirmation is requested, posts decision='proceed' to http://127.0.0.1:5000/confirm?stream=true
and records the actual execution logs and assistant responses!
"""

import sys
import json
import requests

BASE_STREAM_URL = "http://127.0.0.1:5000/transcribe_stream"
CONFIRM_URL = "http://127.0.0.1:5000/confirm?stream=true"

def test_live_command(command_text):
    print("\n" + "=" * 70)
    print(f"LIVE TEST: '{command_text}'")
    print("=" * 70)

    try:
        resp = requests.post(BASE_STREAM_URL, data={"text": command_text}, stream=True, timeout=35)
        events = []
        confirmation_id = None
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data:"):
                raw_json = line[5:].strip()
                try:
                    data = json.loads(raw_json)
                    events.append(data)
                    # Check for confirmation ID
                    conf_obj = data.get("data", {}).get("confirmation", {})
                    if conf_obj.get("id"):
                        confirmation_id = conf_obj.get("id")
                except Exception:
                    pass

        # If confirmation was requested, confirm 'proceed' to execute the plan!
        if confirmation_id:
            print(f"  [Gate] Confirmation requested (ID: {confirmation_id}). Auto-confirming 'proceed'...")
            c_resp = requests.post(
                CONFIRM_URL,
                json={"confirmation_id": confirmation_id, "decision": "proceed"},
                headers={"Accept": "text/event-stream"},
                stream=True,
                timeout=35
            )
            for line in c_resp.iter_lines(decode_unicode=True):
                if line and line.startswith("data:"):
                    raw_json = line[5:].strip()
                    try:
                        data = json.loads(raw_json)
                        events.append(data)
                    except Exception:
                        pass

        intent = "N/A"
        tool = "N/A"
        target = "N/A"
        response = "N/A"
        status = "N/A"

        for ev in events:
            stage = ev.get("stage")
            payload = ev.get("payload", {})
            data = ev.get("data", {})

            if stage == "intent":
                intent = payload.get("intent") or data.get("intent") or ev.get("intent") or intent
            elif stage == "planner":
                steps = payload.get("steps") or data.get("steps") or []
                if steps:
                    tool = steps[0].get("tool")
                    args = steps[0].get("args", {})
                    target = args.get("query") or args.get("application") or str(args)
            elif stage == "execution":
                logs = payload.get("logs") or data.get("logs") or []
                if logs:
                    target = str(logs[-1])
            elif stage == "response":
                response = payload.get("text") or data.get("response_text") or ev.get("response_text") or response
            elif stage in ("done", "completed"):
                status = data.get("status") or payload.get("status") or "completed"
                if not response or response == "N/A":
                    response = data.get("response_text") or payload.get("text") or response

        print(f"  -> Disambiguated Intent: {intent}")
        print(f"  -> Selected Tool: {tool}")
        print(f"  -> Target / Exec Log: {target}")
        print(f"  -> Final Assistant Response: {response}")
        print(f"  -> Pipeline Status: {status}")

    except Exception as e:
        print(f"Request error: {e}")

def main():
    test_commands = [
        "Open Microsoft Word",
        "Open Microsoft PowerPoint",
        "Open Microsoft Store",
        "Open Ubuntu Terminal",
        "Open Calculator",
        "Open Chrome",
        "Open Gmail",
        "Open SomeRandomUnknownTool"
    ]

    for cmd in test_commands:
        test_live_command(cmd)

if __name__ == "__main__":
    main()
