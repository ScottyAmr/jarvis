"""
JARVIS n8n Workflow Registry — the ONLY place a new n8n automation needs to
be added. Nothing in server.py's dispatch chain changes when a workflow is
added here; the generic [ACTION:N8N] tag reads this list at request time.

Each entry:
  id           — short identifier the LLM uses in [ACTION:N8N] <id> ||| ...
  description  — one line the LLM sees so it knows when to use this workflow
  webhook_path — the path segment of the n8n webhook URL (after /webhook/)
  permission   — READ_ONLY | CONFIRM | AUTONOMOUS
                   READ_ONLY / AUTONOMOUS fire immediately.
                   CONFIRM holds for an explicit spoken yes/no first — use
                   this for anything consequential (sending, publishing,
                   spending, deleting, contacting people, modifying events).
  fields       — flat field names this workflow expects in its payload
  timeout      — seconds to wait for this specific workflow before giving up
"""

WORKFLOWS = [
    {
        "id": "ping_test",
        "description": "Connectivity test — echoes the payload straight back. No real-world effect, safe to run any time.",
        "webhook_path": "jarvis-ping-test",
        "permission": "READ_ONLY",
        "fields": ["message"],
        "timeout": 10,
    },
]


def get_workflow(workflow_id: str) -> dict | None:
    for wf in WORKFLOWS:
        if wf["id"] == workflow_id:
            return wf
    return None


def describe_workflows_for_prompt() -> str:
    """Short block for the LLM's per-turn dynamic context."""
    if not WORKFLOWS:
        return "No n8n workflows currently registered."
    lines = []
    for wf in WORKFLOWS:
        fields = ", ".join(wf["fields"]) or "no fields"
        lines.append(f"- {wf['id']} ({wf['permission']}): {wf['description']} [fields: {fields}]")
    return "\n".join(lines)
