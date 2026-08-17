# Jarvis ↔ n8n Bridge

Jarvis stays the assistant and the interface. n8n is the automation layer it reaches for
anything that means talking to an external service, API, scheduled job, or webhook — the
kinds of integrations that don't fit AppleScript (Gmail, Drive, social platforms, CRMs,
leads, content pipelines, future smart-home APIs).

```
Jarvis Core (server.py)
    |  LLM emits [ACTION:N8N] <workflow_id> ||| field=value ||| ...
    v
Jarvis Tool Layer  =  registry.py (this dir)
    v
n8n Integration  =  client.py  ->  N8nClient.trigger_workflow()
    v
n8n  ->  external services
```

The model router (`llm_provider.py`) never imports this package and this package never
imports it back. The LLM only ever sees a generic `[ACTION:N8N]` tag plus whatever workflows
are currently listed in `registry.py`'s `WORKFLOWS` — it works the same regardless of which
LLM provider is active.

## Local setup

1. Start n8n:
   ```bash
   docker compose -f docker-compose.n8n.yml up -d
   ```
2. Open http://localhost:5678, create an owner account (first run only).
3. Import `integrations/n8n/workflows/ping_test.json` (Workflows → Import from File),
   then **activate** it (the toggle in the top right) — n8n webhooks only respond once active.
4. In n8n, go to Settings → API and generate an API key.
5. Fill in `.env`:
   ```env
   N8N_BASE_URL=http://localhost:5678
   N8N_API_KEY=<the key from step 4>
   N8N_WEBHOOK_SECRET=<any random string you generate — used to sign callbacks Jarvis receives>
   ```
6. Restart Jarvis. Say something like *"ping the test workflow and say hello"* — Jarvis
   should trigger `ping_test` and speak back a confirmation.

Jarvis runs completely normally with none of this configured — `[ACTION:N8N]` just reports
"n8n isn't configured" rather than erroring, and `GET /api/n8n/health` reports the same.

## Adding a new workflow

This is the whole point of the bridge: adding an automation should never require touching
`server.py`.

1. **Build the workflow in n8n's UI** — a Webhook trigger node, whatever logic it needs, and
   either a "Respond to Webhook" node (synchronous — the workflow finishes fast and Jarvis
   gets the result immediately) or a callback to `POST {your Jarvis URL}/api/n8n/webhook`
   signed with `N8N_WEBHOOK_SECRET` (asynchronous — for anything slower than an HTTP timeout).
2. **Add one entry to `registry.py`**:
   ```python
   {
       "id": "your_workflow_id",
       "description": "One line — this is what the LLM reads to decide when to use it.",
       "webhook_path": "the-path-segment-from-n8n",
       "permission": "READ_ONLY",  # or CONFIRM, or AUTONOMOUS
       "fields": ["field_one", "field_two"],
       "timeout": 15,
   }
   ```
3. **List its expected fields** in that same entry (`fields`) — these are flat `key=value`
   pairs the LLM fills in on the `[ACTION:N8N]` tag, not JSON (see "Why flat fields, not
   JSON" below).
4. **Set its permission tier**:
   - `READ_ONLY` — retrieves information, changes nothing. Fires immediately.
   - `AUTONOMOUS` — you've explicitly decided this workflow is safe to run unattended. Fires
     immediately.
   - `CONFIRM` — the default for anything consequential (sending, publishing, spending,
     deleting, contacting people, modifying appointments). Jarvis prepares the action, asks
     you out loud, and only fires it if your next reply is a clear yes.

That's it — no code changes. The new workflow shows up in the LLM's context automatically
next turn (it's injected live from `registry.py`, not baked into the cached system prompt).

## Why flat fields, not JSON

Earlier work on Jarvis's other action tags (`ADD_TASK`, `MUSIC`) hit the same failure mode
twice: the LLM occasionally glues trailing narrative text onto the last `|||`-delimited
field of a tag (e.g. `volume|||0Done, sir.` instead of just `volume|||0`). Embedding raw JSON
as a tag argument would make this much worse — nested quotes inside an already-fragile parse.
`[ACTION:N8N]` sticks to flat `key=value` pairs instead, so a parsing hiccup corrupts at most
one field's value instead of the whole payload.

## Error handling

Every `N8nClient` call returns a structured result and never raises — an n8n outage, a
misconfigured webhook, or a workflow failure can't crash Jarvis. Results carry a `kind`:
`auth`, `rate_limit`, `workflow_failure`, `timeout`, `network`, `invalid_payload`, or
`unavailable`, each with its own spoken message so Jarvis can explain what actually went
wrong instead of a generic "something broke."

## Security

- `N8N_API_KEY` is sent as a bearer token on every outgoing request; never logged.
- Incoming callbacks to `POST /api/n8n/webhook` are rejected with 401 unless they carry a
  valid `X-N8N-Signature` header — an HMAC-SHA256 of the raw body using `N8N_WEBHOOK_SECRET`.
  Configure your n8n workflow's HTTP Request/Respond node to send that header when calling
  back.
- `.env` is gitignored — never commit real values for any of the `N8N_*` variables.
