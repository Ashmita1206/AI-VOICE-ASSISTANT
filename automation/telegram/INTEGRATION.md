# Telegram Hybrid Automation — Future Integration Guide

This document describes the exact minimal integration points required to connect `automation.telegram` into the root application pipeline.

> [!NOTE]
> Per the safety guidelines of this task, existing production files were left **100% untouched**. The integration patches below can be applied in a future pull request.

---

## 1. Environment Dependencies (`requirements.txt`)

Add the Pyrogram MTProto framework and its fast crypto library:

```diff
--- requirements.txt
+++ requirements.txt
@@ +38,0 +38,4 @@
+# Telegram MTProto Automation
+pyrogram>=2.0.0
+tgcrypto>=1.2.0
```

---

## 2. Git Ignored Files (`.gitignore`)

Add Pyrogram session file patterns to prevent committing secrets:

```diff
--- .gitignore
+++ .gitignore
@@ +85,0 +85,4 @@
+# Telegram Pyrogram Session Files
+*.session
+*.session-journal
+telegram_assistant.session*
```

---

## 3. Command Intent Registry (`agent/command_registry.py`)

Register the `send_telegram_message` intent definition:

```python
IntentDefinition(
    name="send_telegram_message",
    description="Send a message to a contact on Telegram after visual draft preview and voice confirmation.",
    keywords=["telegram", "message", "bhejo", "send", "bol do"],
    patterns=[
        IntentPattern(
            template="telegram pe {recipient} ko message bhejo ki {message}",
            slots=["recipient", "message"],
            regex=re.compile(r"^telegram\s+(?:pe|par)\s+(?P<recipient>.+?)\s+ko\s+message\s+bhejo\s+ki\s+(?P<message>.+)$", re.IGNORECASE)
        )
    ]
)
```

---

## 4. Execution Tool Registration (`execution/registry.py`)

Register the tool handler in the stateful execution engine:

```python
from automation.telegram import TelegramAutomationRouter, TelegramService
from execution.registry import register_tool
from execution.schemas import ExecutionResult

_service = TelegramService()
_router = TelegramAutomationRouter(_service)

@register_tool("send_telegram_message")
def handle_telegram_message(args: dict) -> ExecutionResult:
    """Execute Telegram hybrid messaging flow turn."""
    import asyncio
    text = args.get("command") or args.get("text") or ""
    res = asyncio.run(_router.handle_input(text))
    return ExecutionResult(
        success=(res.status not in (FlowStatus.ERROR, FlowStatus.CANCELLED)),
        tool="send_telegram_message",
        message=res.message,
        data=res.data
    )
```

---

## 5. Agentic Tool Registry (`agentic/tool_registry.py`)

Register tool definition for the Qwen/LLM planner:

```python
ToolDefinition(
    name="send_telegram_message",
    description="Safely draft and send a message via Telegram with visual draft preview and user voice confirmation.",
    parameters={
        "type": "object",
        "properties": {
            "recipient": {"type": "string", "description": "Target contact name or username"},
            "message": {"type": "string", "description": "Message content to send"}
        },
        "required": ["recipient", "message"]
    }
)
```
