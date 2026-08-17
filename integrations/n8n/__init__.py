"""
JARVIS n8n Integration — workflow-automation bridge.

Jarvis stays the assistant and the model router (llm_provider.py) stays
independent of this module entirely; the LLM only ever sees a generic
[ACTION:N8N] tag plus whatever workflows are currently registered in
registry.py. Adding a new workflow never requires touching server.py —
see registry.py's docstring for the four-step process.
"""

from .client import N8nClient, get_client, reset_client
from .registry import WORKFLOWS, get_workflow, describe_workflows_for_prompt

__all__ = [
    "N8nClient",
    "get_client",
    "reset_client",
    "WORKFLOWS",
    "get_workflow",
    "describe_workflows_for_prompt",
]
