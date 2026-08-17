# JARVIS — Voice AI Assistant

## Overview
JARVIS (Just A Rather Very Intelligent System) is a voice-first AI assistant for macOS. It runs locally on your machine, connecting to your Apple Calendar, Mail, Notes, and can spawn Claude Code sessions for development tasks.

## Quick Start
When a user clones this repo and starts Claude Code, help them:
1. Copy .env.example to .env
2. Get an Anthropic API key from console.anthropic.com
3. Get a Fish Audio API key from fish.audio
4. Install Python dependencies: pip install -r requirements.txt
5. Install frontend dependencies: cd frontend && npm install
6. Generate SSL certs: openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj '/CN=localhost'
7. Run the backend: python server.py
8. Run the frontend: cd frontend && npm run dev
9. Open Chrome to http://localhost:5173
10. Click to enable audio, speak to JARVIS

## Architecture
- **Backend**: FastAPI + Python (server.py, ~3300 lines)
- **Frontend**: Vite + TypeScript + Three.js (audio-reactive orb)
- **Communication**: WebSocket (JSON messages + binary audio)
- **AI**: pluggable backend (Anthropic Claude / Gemini / OpenAI-compatible) with automatic
  rate-limit fallback across models — see `llm_provider.py`
- **TTS**: Fish Audio (default), macOS `say`, or local Piper — see `VOICE_ENGINE`
- **System**: AppleScript for Calendar, Mail, Notes, Music, Messages, Terminal integration

## Key Files
- `server.py` — Main server, WebSocket handler, LLM integration, action system
- `frontend/src/orb.ts` — Three.js particle orb visualization
- `frontend/src/voice.ts` — Web Speech API + audio playback
- `frontend/src/main.ts` — Frontend state machine
- `memory.py` — SQLite memory system (facts/tasks/notes) with FTS5 search
- `conversation_memory.py` — persistent raw chat-transcript history + cross-session recall
- `calendar_access.py` — Apple Calendar (read); `write_integrations.py` creates events
- `mail_access.py` — Apple Mail (read); `write_integrations.py` sends/drafts
- `notes_access.py` — Apple Notes integration
- `music_control.py` — Music.app / Spotify playback control
- `actions.py` — System actions (Terminal, Chrome, Claude Code)
- `browser.py` — Playwright web automation
- `work_mode.py` — Persistent Claude Code sessions
- `llm_provider.py` — pluggable LLM backends + rate-limit fallback chain

## Environment Variables
- `ANTHROPIC_API_KEY` (required unless using another `LLM_PROVIDER`) — Claude API access
- `FISH_API_KEY` (required unless `VOICE_ENGINE=say`/`piper`) — Fish Audio TTS
- `FISH_VOICE_ID` (optional) — Voice model ID
- `USER_NAME` (optional) — Your name for JARVIS to use
- `CALENDAR_ACCOUNTS` (optional) — Comma-separated calendar emails
- See `.env.example` for the full list (LLM provider selection, voice engine, fallback models, etc.)

## Conventions
- JARVIS personality: British butler wit with room to be playful, plus a commercial/business-minded
  lens on requests (cost, priority, tradeoffs) — see `JARVIS_SYSTEM_PROMPT_STATIC` in `server.py`
- Max 1-2 sentences per voice response
- Action tags: [ACTION:BUILD], [ACTION:BROWSE], [ACTION:RESEARCH], [ACTION:SEND_EMAIL],
  [ACTION:CREATE_EVENT], [ACTION:SEND_MESSAGE], [ACTION:MUSIC], [ACTION:RECALL], etc. — full list
  and usage rules are in the system prompt
- AppleScript for all macOS integrations (no OAuth needed), always via `asyncio.create_subprocess_exec`
  (never synchronous `subprocess.run`, which would block the whole server's event loop)
- Mail/Calendar/Messages are read AND write — sending is immediate with no confirmation step by
  design choice; keep that in mind when changing action-dispatch code
- SQLite for all local data storage
- See `JARVIS_MEMORY.md` for the fuller project map, known issues, and design history
