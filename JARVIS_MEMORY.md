# JARVIS — Project Memory

_Last updated: 2026-08-16. Originally written 2026-08-15 by a Claude Code session
reconstructing context from scratch (no prior session history was available). Update this
file as the project evolves — future sessions should read it first._

## Purpose

A voice-first AI assistant for macOS ("Just A Rather Very Intelligent System"). You talk to
it in the browser (Web Speech API mic input), it talks back in a JARVIS-style voice, and it
can act on your behalf: read your Calendar/Mail/Notes, browse the web, control music, plan
your day, remember things you tell it, and spawn real Claude Code sessions to build or work
on software projects. British-butler personality, dry wit, terse voice responses (1-2
sentences).

## Where this lives

This repo (`~/Developer/jarvis`) **is** the live, actively-developed project — not a copy or
a fork-in-progress. `git log` shows 16 local commits ahead of `origin/main`, with the most
recent commit from today. Two other "Jarvis"-named things exist on this Mac and are **not**
part of this project's history:
- `~/Desktop/jarvis-project/` — an empty scaffold containing only a leftover `CLAUDE.md`
  build-prompt template. This is a byproduct of JARVIS's own `[ACTION:BUILD]` feature (it
  spawns Claude Code into fresh folders with a template like this) — not prior Jarvis history.
- `~/Downloads/Jarvis-os-2.0-main.zip` — a completely different, unrelated open-source
  "Jarvis OS" project (Docker + Postgres + Express + local GGUF LLM). Different author,
  different architecture. Likely downloaded for reference/inspiration only.

## Current features (what's actually built)

Far more than the README/CLAUDE.md describe — both are stale (written when `server.py` was
~2300 lines; it's now 3323, and ~10 backend modules exist that neither doc mentions).

**Core voice loop** — `server.py`: WebSocket handler, intent classification, the
`[ACTION:*]` tag system, LLM calls. Wired action tags as of 2026-08-16: `ADD_NOTE`,
`ADD_TASK`, `BROWSE`, `BUILD`, `COMPLETE_TASK`, `CREATE_EVENT`, `CREATE_NOTE`,
`DRAFT_REPLY`, `MUSIC`, `OPEN_TERMINAL`, `ORGANIZE`, `ORGANIZE_CONFIRM`, `PROMPT_PROJECT`,
`READ_NOTE`, `RECALL`, `REMEMBER`, `RESEARCH`, `SCREEN`, `SEND_EMAIL`, `SEND_MESSAGE`,
`SHOPPING`, `X`. Many of these (music, shopping list, mail/calendar checks, conversation
recall) also have a keyword fast-path in `detect_action_fast()` that skips the LLM entirely
for direct phrasing — the `[ACTION:*]` tag is the LLM-routed fallback for indirect phrasing.

**LLM layer** — `llm_provider.py`: pluggable backends (Anthropic primary, Gemini,
OpenAI-compatible providers) with an automatic fallback chain across models on
rate-limit/failure, aimed at stretching free-tier daily quotas. Not documented in
README/CLAUDE.md at all — added recently (commits `b11d482`, `37a386c`, `958a1bc`).

**Memory** — two separate systems, not overlapping:
- `memory.py` — facts, tasks, notes with SQLite FTS5 (`remember`, `recall`, task/note CRUD).
  Tasks have a `project` column, reused (not a separate store) for the shopping list —
  `project="shopping"`. See Known Issues for why this wasn't obvious until 2026-08-16.
- `conversation_memory.py` — raw turn-by-turn chat transcript with FTS5 search, wired in
  2026-08-15 (`[ACTION:RECALL]` + a `conversation_recall` fast-path).

**macOS integrations (AppleScript, no OAuth)**:
- `calendar_access.py` — read/write (`CREATE_EVENT` via `write_integrations.py`).
- `mail_access.py` — read/write (`SEND_EMAIL`/`DRAFT_REPLY` via `write_integrations.py`).
  Raises `MailAccessError` on failure/timeout (2026-08-15) rather than returning `""` — see
  Known Issues for a real-world timeout/process-leak bug found and fixed 2026-08-16.
- `notes_access.py` — read/write.
- `music_control.py` — Music.app/Spotify play/pause/skip/volume/now-playing. Wired in
  2026-08-15 (`[ACTION:MUSIC]` + fast-path).
- `write_integrations.py` — send/draft email, reply to a message, create calendar events,
  send iMessages. Wired in 2026-08-15. **`send_email`/`send_message` send immediately, no
  confirmation step — user explicitly chose this, see Design notes below.**
- `file_organizer.py` + `daily_organize.py` — dry-run scan of Downloads/Desktop clutter
  (`[ACTION:ORGANIZE]`) with a separate explicit-confirm apply step (`[ACTION:ORGANIZE_CONFIRM]`,
  refused if the scan is >1hr stale). `apply_plan()` only ever sorts into category subfolders
  or sends exact duplicates to the Trash — never a hard delete. A launchd job
  (`~/Library/LaunchAgents/com.jarvis.dailyorganize.plist`, 11:11am daily) runs the scan and
  posts a macOS notification; applying still requires asking JARVIS to confirm. Wired into
  `server.py` before this session (already done when this session started) but not yet
  reflected in this file — see Known Issues for a real crash bug found/fixed 2026-08-16.

**Shopping list** — no dedicated module; `server.py`'s `_shopping_add`/`_shopping_list_voice`/
`_shopping_check` (added 2026-08-16) are a thin voice layer over `memory.py`'s existing tasks
table (`project="shopping"`). Fast-path: "add X to my shopping list", "what's on my list",
"check off X". `[ACTION:SHOPPING]` tag covers indirect phrasing ("we're out of milk").

**Dev-task spawning** — `actions.py`, `dispatch_registry.py`, `work_mode.py`: spawns real
Claude Code subprocesses to build new projects (`[ACTION:BUILD]`) or connect to/continue
existing ones (`[ACTION:PROMPT_PROJECT]`), including persistent long-running sessions.

**Other backend modules**: `planner.py` (day planning from calendar+tasks), `browser.py`
(Playwright web automation), `screen.py` (screen-context awareness for responses),
`templates.py` + `templates/prompts` (prompt templating), and an undocumented
self-improvement/analytics layer — `evolution.py`, `learning.py`, `suggestions.py`,
`tracking.py`, `ab_testing.py`, `qa.py`. **A chunk of this layer (auto-QA + auto-retry on
completed `BUILD` tasks, in `ClaudeTaskManager._run_qa`) was removed from `server.py` in the
uncommitted 2026-08-15/16 diff** — looks deliberate (not a partial edit — the call site and
the method were both cleanly removed together) but wasn't confirmed with the user; flagging
rather than restoring it. The rest of this layer (`evolution.py` etc.) still exists on disk
and is presumably still wired elsewhere — not audited this session.

**Native overlay** — `desktop-overlay/JarvisOverlay.swift`: a native macOS Swift overlay app.
Not mentioned in any doc.

**Frontend** (`frontend/src/`) — Vite + TS + Three.js: `orb.ts` (audio-reactive particle
orb; `orb.backup.ts` is a leftover), `voice.ts` (Web Speech API + audio playback), `main.ts`
(state machine), `dashboard.ts`, `settings.ts`, `ws.ts`.

**TTS options** (configured via `.env`, all present on this machine): Fish Audio (paid,
best JARVIS voice, default), macOS `say` (free/offline), Piper (free/offline neural TTS,
model path already configured locally).

**Tests** — `tests/` (109 passing as of 2026-08-16): AppleScript escaping (a past
command-injection bug was fixed and is now regression-tested — `a3772ec`, `903f159`),
browser integration, intent classifier, e2e pipeline, feedback loop, `file_organizer.py`
(33 tests, added 2026-08-16), `mail_access.py`'s `_run_mail_script` (5 tests, added
2026-08-16), shopping list (28 tests, added 2026-08-16). Run with `pytest tests/ -q`.
`pyrightconfig.json` was added recently but pyright hasn't been acted on yet — a first run
(2026-08-16) found 160 pre-existing type diagnostics, 108 of them in `server.py`. Not a
regression from any recent change, just never checked before; worth triaging but is a
large, separate effort — not attempted this session beyond confirming it's not new.

**Launchers** — `start.sh` / `JARVIS.command`: start backend (:8340) + frontend (:5173)
together, clear stale ports, auto-open Chrome, tear both down together on Ctrl+C or either
one dying.

## Architecture / tech stack

```
Mic -> Web Speech API -> WebSocket -> FastAPI (server.py) -> LLM (llm_provider.py,
Anthropic/Gemini/OpenAI-compatible w/ fallback chain) -> TTS (Fish/say/Piper) -> WebSocket
-> Speaker + Three.js orb
                                            |
                                            v
                              [ACTION:*] tag dispatch (actions.py / dispatch_registry.py)
                                            |
                       -----------------------------------------------
                       |                    |                        |
                Claude Code spawn      AppleScript bridge      memory.py / conversation_memory.py
              (build / work_mode)   (Calendar/Mail/Notes/Music)         (SQLite + FTS5)
```

Storage: SQLite at `data/jarvis.db` (gitignored). Certs: self-signed `cert.pem`/`key.pem`
for secure WebSocket (gitignored, regenerate per machine).

## How to run it

`.env` on this machine is already fully configured (Anthropic key, Gemini fallback key,
custom LLM fallback chain, Piper local TTS path, user name/locale). To start:

```bash
./start.sh
```

(or double-click `JARVIS.command`). This starts the backend on :8340 and frontend on :5173,
waits for both, and opens Chrome automatically. Click the page once to enable audio, then
speak.

Manual/first-time setup (if `.venv` or `frontend/node_modules` are missing):
```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj '/CN=localhost'
```

## Known issues / unfinished work

_Updated 2026-08-15, second session — the three orphaned modules are now wired in, docs are
refreshed, and a stress-testing pass found and fixed several real bugs. See below for what
changed and what's still open._

### Resolved this session
- `conversation_memory.py`, `music_control.py`, `write_integrations.py` are now imported and
  wired into `server.py`: fast keyword paths for music/recall in `detect_action_fast()`, new
  `[ACTION:SEND_EMAIL]` / `[ACTION:CREATE_EVENT]` / `[ACTION:SEND_MESSAGE]` / `[ACTION:MUSIC]`
  / `[ACTION:RECALL]` tags, and every turn is now logged to `conversation_memory` for
  cross-session recall. `[ACTION:DRAFT_REPLY]` now actually places the composed reply as a
  real Mail.app draft (via `write_integrations.reply_to_message`) instead of only speaking it.
- **User explicitly chose "send immediately, no confirmation"** for `send_email`/`send_imessage`
  when asked — this is deliberate, not an oversight. The system prompt documents it and warns
  the model to only fire those tags on unambiguous intent.
- `music_control.py` and `write_integrations.py` used synchronous `subprocess.run` for
  AppleScript calls — inconsistent with the rest of the codebase (`mail_access.py`,
  `notes_access.py`, `calendar_access.py` all use `asyncio.create_subprocess_exec`) and would
  have **blocked the entire server's event loop**, freezing every connected client, for the
  duration of any music/mail/calendar/message AppleScript call. Converted both modules to
  async subprocess calls to match convention. This was caught before it ever reached
  production — would have been a serious, hard-to-diagnose latency bug.
- Live stress testing (a WebSocket test client driving the real server, not just unit tests)
  found: (a) a stale test (`tests/test_browser_integration.py::test_browse_action_keywords`)
  referencing a data structure (`ACTION_KEYWORDS`) that no longer exists — fixed to test the
  actual current mechanism (`extract_action` parsing `[ACTION:BROWSE]`); (b) the LLM
  occasionally glues trailing narrative text onto the last `|||` field of an action tag (same
  bug class already fixed once for `ADD_TASK`'s due_date in commit `f2e8141`) — hit this again
  for `[ACTION:MUSIC]`'s volume field (`"volume|||0Done, sir."` silently parsed as level 50
  instead of 0) and fixed with the same leading-token regex-extraction technique, applied to
  both the music volume and calendar event duration fields; (c) when a WebSocket connection
  died mid-turn, the error handler's own fallback "something went wrong" message ALSO failed to
  send (dead socket), and that failure was silently swallowed and the loop kept looping,
  producing a cascade of repeated full tracebacks for every subsequently-buffered message
  instead of ending the session cleanly — fixed by breaking the loop when the fallback send
  itself fails; (d) raw user input was logged unbounded (a 3000-char paste wrote 3000 chars to
  the log) — capped at 500 chars in the log line.
- Verified live end-to-end: `[ACTION:CREATE_EVENT]` correctly parsed "tomorrow at 9am for 15
  minutes" and created a real Calendar event in under a second (previously would have been a
  multi-second blocking call). **A test event titled "JARVIS Stress Test Delete Me" was created
  on 2026-08-16 09:00 — safe to delete, it's real.**
- Stray `data/jarvis.db.bak` and `frontend/src/orb.backup.ts` removed; `.gitignore` now also
  excludes `*.db.bak`.
- README.md and CLAUDE.md refreshed to list the newly-wired modules, the full current action
  tag set, and the pluggable-LLM/multi-voice-engine architecture.
- System prompt (`JARVIS_SYSTEM_PROMPT_STATIC` in `server.py`) updated: added a "BUSINESS
  MINDSET" trait (weighs cost/time/priority, flags a better path before acting) and loosened
  the personality to allow dry/playful wit rather than "never jokes" — still bounded by the
  1-2 sentence limit.

### Resolved 2026-08-16 (third session — Postiz/Ollama environment setup + Jarvis reliability pass)
User stepped out and asked me to "make Jarvis an effective assistant for all daily tasks" and
work around anything I couldn't do alone. Found `file_organizer.py`/`daily_organize.py` and
`ORGANIZE`/`ORGANIZE_CONFIRM` already wired into `server.py` (done before this session, just
never written up here), then found and fixed real bugs via live testing rather than
inventing new work blind:
- **Real crash, found via the launchd log**: today's 11:11am scheduled organize scan died
  with `InterruptedError: [Errno 4] Interrupted system call` while listing `~/Downloads`
  (`~/.jarvis/daily_organize.err`) — the job failed silently, no notification ever sent.
  Fixed by retrying the directory listing a few times on `InterruptedError` and skipping
  (not crashing) a directory that still can't be read (`file_organizer._listdir_retry`), and
  by wrapping `daily_organize.py`'s `main()` in a try/except that notifies on failure instead
  of dying silently. Regression-tested (`tests/test_file_organizer.py`, 33 tests — this
  module had zero test coverage before today despite moving real files).
- **Timeout mismatch, found via live testing**: `mail_access.py`'s `get_unread_count`/
  `get_unread_messages` were changed 2026-08-15 to need up to 75s on this real inbox, but
  `server.py`'s `_lookup_and_report()` (the voice "check my mail" background-lookup wrapper)
  still hard-coded a 30s outer `asyncio.wait_for` — so the voice mail-check path would
  reliably time out before the real 75s answer ever came back. Fixed by giving
  `_lookup_and_report` a `timeout` parameter and passing 90s for the mail lookup specifically.
- **Silent failure, found via code review**: `_draft_reply_and_report`'s exception handler
  logged the error but never spoke anything back to the user — unlike every other
  `_*_and_report` handler in the file, which all call `_speak(ws, "Something went wrong...")`
  on failure. Fixed for consistency.
- **Process leak + a second, more serious mail bug, found via live testing (not just unit
  tests)**: called `/api/inbox-summary` for real. It took the full 75-90s and failed twice in
  a row. A raw `osascript` run of the same *count* query outside the server finished in 35s —
  so I checked `ps aux` and found two orphaned `osascript` processes still running minutes
  later, from the heavier `get_unread_messages` script (fetches sender/subject/date/content
  preview for up to 30 messages). Root cause: `asyncio.wait_for`'s `TimeoutError` only stops
  *awaiting* the subprocess — it never kills the underlying OS process, so a timed-out
  osascript call keeps running indefinitely in the background. Killed the two leaked
  processes and fixed `_run_mail_script` to `proc.kill()` + `proc.wait()` on any
  timeout/error path. Regression-tested (`tests/test_mail_access.py`, 5 tests, using a mock
  subprocess whose `.communicate()` never resolves).
  **Not fixed — flagging instead**: the underlying reason mail checks are this slow at all is
  that this inbox has **2,643 unread messages**, and Mail.app's AppleScript `messages of
  inbox whose read status is false` filter is a known-slow pattern against a large mailbox
  (likely an O(n) per-message round-trip, not a real server-side filter). Even the corrected
  90s outer timeout may not be enough, and it'll only get slower as unread count grows.
  Rewriting the AppleScript query (e.g. avoiding the `whose` filter, or capping how far back
  it scans) would need to be tested live against this real inbox to trust the fix — didn't
  want to risk it unsupervised. Worth a look together.
- **New feature, built end-to-end**: a shopping list, using `memory.py`'s existing
  `tasks` table (`project="shopping"`) rather than a new store — "add milk to my shopping
  list", "what's on my list", "check off milk", plus an `[ACTION:SHOPPING]` LLM-fallback tag
  for indirect phrasing ("we're out of milk"), mirroring the existing MUSIC dual-layer
  pattern exactly. 28 new tests, all against an isolated tmp_path DB (never the real
  `data/jarvis.db`). Picked this because the user was literally headed to the shop when they
  asked me to work on "daily tasks" — timely and low-risk (pure DB feature, no external
  calls), not because it was flagged anywhere as missing.
- Backend was restarted (old PID killed, fresh one on :8340) to load all of the above —
  confirmed clean startup and `/api/settings/status` responding. Full test suite: 109 passing.
- Environment (not Jarvis code, but relevant to where this project is heading): installed
  Colima + docker + docker-compose via Homebrew (no Docker Desktop needed) and stood up
  Postiz (`~/Downloads/postiz-app-main`, self-hosted social scheduler) at `localhost:4007`,
  intended to eventually post Aura AI Agency content and be wired into Jarvis as an action.
  Installed and started Ollama (`brew install ollama`, running at `localhost:11434`) — a
  candidate local-LLM fallback for `llm_provider.py`, not wired in yet. Postiz's own account
  signup and every platform's OAuth connection need the user directly (never enter
  credentials/create accounts on their behalf) — parked at the sign-up screen.

### Resolved 2026-08-17 (fourth session — n8n bridge, browser.py fix, dev-tooling pass)
- **Built the n8n workflow-automation bridge** (`integrations/n8n/`): `client.py`
  (`N8nClient` — never raises, classifies every failure into
  auth/rate_limit/workflow_failure/timeout/network/invalid_payload/unavailable),
  `registry.py` (the only place new workflows get added — one entry today, `ping_test`),
  a generic `[ACTION:N8N] workflow_id ||| field=value ||| ...` tag (flat fields, not JSON —
  deliberately sidesteps the trailing-garbage-on-last-field bug hit twice already), a
  `CONFIRM` permission tier reusing the exact `pending_self_dispatch` pattern, two REST
  endpoints (`/api/n8n/health`, `/api/n8n/webhook` with HMAC signature validation), a
  standalone `docker-compose.n8n.yml`, an importable test workflow JSON, and 21 new mocked
  tests. Planned via `EnterPlanMode` first since it was genuinely architectural — the user
  explicitly values that step, confirmed when asked directly. n8n itself isn't installed on
  this machine, so the real end-to-end trigger→n8n→response round trip is mocked in tests,
  not live-fired; only the health/dispatch/parsing/confirmation logic was live-verified.
- **`browser.py` fixed for real UX harm, though it turned out to be a red herring for the
  original complaint**: the user saw 4 unexpected "Google Chrome for Testing" tabs pop up
  and take over their screen, asked me to make Jarvis quieter. Investigated and had to walk
  back my first guess — `browser.py`'s `JarvisBrowser` (Playwright) is **not called anywhere
  in `server.py`**, so it couldn't have caused that specific incident, and even if it were
  wired in, Playwright's bundled browser reports as "Chromium," not "Google Chrome for
  Testing" (a different, testing-specific binary) — so the actual source of those tabs is
  still unknown, likely unrelated to Jarvis entirely. Fixed `browser.py` anyway since it was
  bad-by-design regardless of whodunnit: was hardcoded `headless=False` with a comment
  ("so user can watch JARVIS browse") and `search()`/`visit()` deliberately never closed
  their pages ("keep it visible") — a `research()` call leaks up to 4 tabs forever. Now
  headless by default (`JARVIS_BROWSER_HEADLESS=false` to opt back into watching it), pages
  close in a `finally` block, two bits of now-pointless dead code removed (an unreachable
  `sleep(3)` after a `return`, a `sleep(2)` "let the user see it" delay with no user watching
  anymore). Still not wired into any action — fixed in place, not connected.
- **Full module-wiring sweep**: cross-referenced every root `.py` file against `server.py`'s
  import graph. Found a whole disconnected subsystem — `qa.py` (verifies Claude Code output,
  auto-retries failures) + `tracking.py` (SQLite success-rate tracking) + `suggestions.py`
  (post-task follow-up suggestions, imports qa.py) + `ab_testing.py` (template A/B testing) +
  `evolution.py` (auto-generates improved templates from failure patterns) + `learning.py`
  (usage-pattern tracking) — ~1,360 lines, real and tested (`test_feedback_loop.py`,
  `test_e2e_pipeline.py`) but zero production wiring. **Notable**: the 2026-08-16 session's
  notes above already flagged that `ClaudeTaskManager._run_qa` was found removed from an
  uncommitted `server.py` diff, "looks intentional but wasn't confirmed with the user" — so
  this may not be purely unbuilt, it may have been wired in at some point and deliberately or
  accidentally disconnected. Needs the user's call, not a guess. Also flagged `conversation.py`
  (252 lines, `PlanningSession`/`ConversationMode`) as likely superseded by `planner.py`'s
  `TaskPlanner` — same-day initial commit, overlapping concepts, only `planner.py` is ever
  instantiated. All 11 disconnected modules still import cleanly — no bit-rot from disuse.
- **Added `tests/test_module_wiring.py`** specifically so this class of discovery (a real,
  working module nobody remembered to connect) stops requiring a manual archaeology sweep —
  it walks server.py's import graph via `ast`, and fails if a root module is neither
  imported, has a `__main__` guard (standalone CLI tools are fine), nor is explicitly listed
  in the test's `KNOWN_DISCONNECTED` dict with a one-line reason. Verified it actually catches
  a real orphan (added a throwaway file, confirmed the test failed, removed it) rather than
  trusting it blind.
- **`start.sh` now passes `--reload`** to the backend (the flag already existed in
  `server.py`'s argparse, just was never actually used) — every backend edit this whole
  multi-session engagement has needed a manual kill+restart until now. Tried also scoping
  uvicorn's `reload_dirs`/`reload_excludes` to quiet log noise from the app's own runtime
  writes (`data/*.db-wal`, `usage_log.jsonl`) triggering "N changes detected" spam — that
  combination **crashed inside uvicorn's own `resolve_reload_patterns()`**, a real reproduced
  bug in uvicorn itself. Reverted rather than ship a startup-crash risk for cosmetic log
  noise; confirmed via direct testing that the noise never actually triggers a real restart
  (`--reload`'s default `*.py`-only `reload_includes` filters it out) — so it's genuinely just
  noise, not a functional problem, and not worth chasing further.
- **`.env.example` was out of sync with reality** — `JARVIS_LANGUAGE`, `JARVIS_REGION`,
  `LLM_BASE_URL`, `LLM_VISION`, and the new `JARVIS_BROWSER_HEADLESS` were all real, working
  env vars read via `os.getenv()` with zero documentation. Filled in; wrote a small script
  (not saved as a repo file, just run ad hoc) that diffs `os.getenv()` calls against
  `.env.example` — worth re-running periodically, or better, worth turning into an actual
  test the way `test_module_wiring.py` did for the orphaned-module problem.
- **Added `.github/workflows/tests.yml`** (macOS runner — the suite exercises real
  AppleScript, a Linux runner would just fail on those) and **`.github/dependabot.yml`**
  (pip + npm/frontend + github-actions, weekly).
- Consciously **skipped** moving `check_models.py`/`monitor.py`/`daily_organize.py` into a
  `scripts/` folder (an earlier brainstormed idea) after discovering `daily_organize.py` is
  referenced by an absolute path in an already-installed, live launchd schedule
  (`~/Library/LaunchAgents/com.jarvis.dailyorganize.plist`, runs daily 11:11am) — moving it
  would've silently broken a real scheduled task for cosmetic directory tidiness. Not worth it.
- **Forked to `github.com/ScottyAmr/jarvis`** via the Claude-in-Chrome browser tools (the
  user's own logged-in Chrome, explicitly requested twice). Local `origin` now points at the
  fork, the old `origin` (`ethanplusai/jarvis`) was renamed to `upstream` for pulling future
  updates from the original project. CI/Dependabot will actually run once this is pushed.
  **Not pushed yet** — 30 files of accumulated, uncommitted multi-session work would go
  public the moment that happens, and no commit has been organized/requested. Needs an
  explicit go-ahead, not assumed under "do everything."
- **Resolved the qa/tracking/suggestions/ab_testing/evolution/learning decision**: dug into
  git history first (`git log -S`). Finding: `ClaudeTaskManager._run_qa` (auto-QA-verify +
  auto-retry on completed builds) existed in the **very first commit**, but called
  `qa_agent`/`success_tracker`/`suggest_followup` **without ever importing them anywhere** —
  it would have raised `NameError` the first time any build completed. So this was never a
  working feature that got disconnected later; it shipped non-functional from day one, and
  was presumably cleaned out of the (uncommitted) working tree at some point without anyone
  noticing it never actually ran. `ab_testing.py`/`evolution.py` have zero trace of ever being
  wired in at any point in history. Decision: **archive, don't build** — auto-retry with real
  API-cost implications on every build deserves its own scoped design pass (like the n8n
  bridge got), not a blind reconnect bundled into a larger cleanup. Files left in place
  (physically moving them would've required untangling `tests/test_e2e_pipeline.py`, which
  mixes active imports like `planner`/`templates` with archived ones — not worth the churn);
  `tests/test_module_wiring.py`'s `KNOWN_DISCONNECTED` dict now documents the corrected
  history inline so this doesn't get re-litigated from scratch next time.
- **`conversation.py` deleted** — confirmed zero references anywhere first. Recoverable via
  `git show d7e0702:conversation.py` if that turns out to be wrong.

### Still open
- **Push to the new fork (`github.com/ScottyAmr/jarvis`)?** Remote is configured
  (`origin`→fork, `upstream`→`ethanplusai/jarvis`), CI/Dependabot are ready, but nothing's
  been pushed — 30 files of uncommitted, unorganized multi-session work would go public the
  moment that happens. Needs an explicit decision on committing (as one or several commits?)
  before pushing, not something to assume.
- **If the self-improvement subsystem ever gets built for real**, treat it as its own scoped
  project the way the n8n bridge was (plan mode, live testing) — not a quick reconnect. See
  the 2026-08-17 entry above for why it's more involved than it looks.
- **The Groq free-tier primary model rate-limits under even modest back-to-back load** — a
  stress test sending a message roughly every 6 seconds triggered repeated 429s, and the
  existing retry+fallback chain (deliberately capped at `RATE_LIMIT_MAX_RETRIES=2` /
  `RATE_LIMIT_MAX_WAIT=6.0`s per model in `llm_provider.py`) can still stack up to 20-40+
  seconds of latency when several fallback models are rate-limited in sequence. This is a
  known, documented tradeoff in the existing code (comment explicitly caps wait time), not
  something changed this session — flagging it because the stress test made the real-world
  cost of that tradeoff concrete. Worth a look if slow responses become noticeable in daily use.
- **Mail checks are slow on this real inbox (2,643 unread) and may still time out** — see
  2026-08-16 entry above. The AppleScript query itself likely needs rework, not just a bigger
  timeout number.
- `send_email`/`send_message`/`create_calendar_event`'s happy paths were not live-fired against
  a real third party during stress testing (only the malformed/guard-clause paths and a
  self-contained calendar event were tested live) — code-reviewed and unit-parsed, but ask if
  you want a real end-to-end email/iMessage send tested.
- AppleScript round-trips for music control can take a few seconds (each check like
  `_app_running()` is its own `osascript` call through System Events) — not a bug, just
  noticeable latency worth knowing about if "play some jazz" feels slow to respond.
- **pyright backlog**: 160 pre-existing type diagnostics (108 in `server.py`), never
  triaged — see Tests note above. Not attempted this session; large surface area, better
  tackled with the user's input on priority than blind unsupervised fixes.
- **`ClaudeTaskManager._run_qa` (auto-QA + auto-retry on completed BUILD tasks) was removed**
  from the uncommitted `server.py` diff — looks intentional but wasn't confirmed with the
  user. See "Other backend modules" above. Flagged, not restored.

## Design / personality notes (do not drift from these)

- British butler, dry wit *with room to be playful* (loosened 2026-08-15 from "never jokes" —
  user explicitly asked for a fun/playful character), plus a business-minded lens (cost,
  priority, tradeoffs) — max 1-2 sentences per voice response either way.
- Mail/Calendar/Messages are read **and write** as of 2026-08-15 — the old "read-only by
  design" principle was a deliberate earlier choice that the user explicitly reversed when
  asked (chose "send immediately, no confirmation" over draft-only or confirm-before-send).
  If you're reading old context that says mail is read-only, it's stale — check `server.py`'s
  system prompt CAPABILITIES section for the current truth.
- No telemetry/analytics sent externally; no data leaves the Mac beyond the configured LLM/TTS
  API calls.
- AppleScript, not OAuth, for every macOS integration — keep new integrations consistent
  with the existing escape-then-interpolate pattern (`actions.py:applescript_escape`) since
  this codebase has already had one AppleScript injection CVE-style bug fixed and
  regression-tested (`tests/test_applescript_escape.py`).
- `server.py` being a large single file is accepted/expected per `CONTRIBUTING.md` ("it
  works"); modularizing is welcome but not required.

## Notes for future sessions

- This file is the fast-context entry point — read it before re-deriving project state from
  scratch.
- When something here goes stale (a file is renamed, a module gets wired in, a known issue
  gets fixed), update this file in the same commit/session rather than leaving it to drift
  like README/CLAUDE.md did.
