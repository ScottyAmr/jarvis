# JARVIS

**Just A Rather Very Intelligent System.**

> **macOS only** -- JARVIS uses AppleScript for Calendar, Mail, Notes, and Music integration. Linux/Windows contributions welcome.

A voice-first AI assistant that runs on your Mac. Talk to it, and it talks back -- with a British accent, dry wit, and an audio-reactive particle orb straight out of the MCU.

JARVIS connects to your Apple Calendar, Mail, and Notes. It can browse the web, spawn Claude Code sessions to build entire projects, and plan your day -- all through natural voice conversation.

> "Will do, sir."

---

## What It Does

- **Voice conversation** -- speak naturally, get spoken responses with a JARVIS voice
- **Builds software** -- say "build me a landing page" and watch Claude Code do the work
- **Reads your calendar** -- "What's on my schedule today?"
- **Reads and sends email** -- "Any unread messages?" / "Email Sarah about the meeting"
- **Browses the web** -- "Search for the best restaurants in Austin"
- **Manages tasks** -- "Remind me to call the client tomorrow"
- **Takes notes** -- "Save that as a note"
- **Remembers things** -- "I prefer React over Vue" (it remembers next time)
- **Plans your day** -- combines calendar, tasks, and priorities into a plan
- **Sees your screen** -- knows what apps are open for context-aware responses
- **Controls music** -- "Play some jazz" (Music.app / Spotify)
- **Sends messages** -- "Text Mom I'll be late" (iMessage/SMS)
- **Audio-reactive orb** -- a Three.js particle visualization that pulses with JARVIS's voice

## Requirements

- **macOS** (Sonoma or later recommended)
- **Python 3.11+**
- **Node.js 18+**
- **Google Chrome** (required for Web Speech API)

You'll also need at least one LLM provider. Options from free to paid:

| Provider | Cost | Setup |
|----------|------|-------|
| [OmniRoute](https://github.com/diegosouzapw/OmniRoute) | Free | `npm i -g omniroute && omniroute` |
| [Groq](https://console.groq.com/) | Free tier | Get API key |
| [Gemini](https://aistudio.google.com/app/apikey) | Free tier | Get API key |
| [Anthropic](https://console.anthropic.com/) | Paid | Get API key (best quality) |

Voice options:

| Engine | Cost | Quality |
|--------|------|---------|
| macOS `say` | Free | Built-in, decent |
| [Piper](https://github.com/rhasspy/piper) | Free | Neural TTS, good |
| [Fish Audio](https://fish.audio/) | Paid | Best JARVIS voice |

## Quick Start (with Claude Code)

The fastest way to get running -- Claude Code reads `CLAUDE.md` and walks you through everything:

```bash
git clone https://github.com/ScottyAmr/jarvis.git
cd jarvis
claude
```

## Manual Setup

```bash
# 1. Clone the repo
git clone https://github.com/ScottyAmr/jarvis.git
cd jarvis

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# 3. Set up environment
cp .env.example .env
# Edit .env with your API keys (see Configuration below)

# 4. Install Python dependencies
pip install -r requirements.txt
playwright install chromium

# 5. Install frontend dependencies
cd frontend && npm install && cd ..

# 6. Generate SSL certificates (needed for secure WebSocket)
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj '/CN=localhost'

# 7. Start everything
./start.sh
```

Chrome opens automatically. Click the page once to enable audio, then speak. JARVIS will respond.

### Free Setup (no API keys needed)

To run JARVIS with zero cost, use OmniRoute + macOS `say`:

```bash
# Install and start OmniRoute (routes across free AI providers)
npm i -g omniroute
omniroute &

# Set these in your .env:
# LLM_PROVIDER=omniroute
# LLM_FAST_MODEL=auto
# LLM_DEEP_MODEL=auto/coding
# VOICE_ENGINE=say
```

## Configuration

Edit your `.env` file. See `.env.example` for the full list of options.

```env
# LLM provider (default: anthropic)
# Options: anthropic, gemini, groq, openrouter, ollama, omniroute, custom
# LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-anthropic-api-key-here

# Voice (default: fish)
# Options: fish (paid, best), say (free), piper (free, neural)
# VOICE_ENGINE=fish
FISH_API_KEY=your-fish-audio-api-key-here

# Optional -- your name (JARVIS will address you personally)
USER_NAME=Tony

# Optional -- specific calendar accounts (comma-separated)
CALENDAR_ACCOUNTS=you@gmail.com,work@company.com
```

## Architecture

```
Mic -> Web Speech API -> WebSocket -> FastAPI -> LLM (pluggable) -> TTS -> WebSocket -> Speaker + Three.js orb
                                                   |
                                                   v
                                         [ACTION:*] tag dispatch
                                                   |
                                  -----------------------------------------
                                  |                |                      |
                           Claude Code        AppleScript            SQLite
                         (build/dev work)  (Calendar/Mail/Notes    (memory/tasks/
                                            Music/Messages)        conversation)
```

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Python (`server.py`, ~3900 lines) |
| Frontend | Vite + TypeScript + Three.js |
| Communication | WebSocket (JSON messages + binary audio) |
| AI | Pluggable: Anthropic, Gemini, Groq, OpenRouter, Ollama, OmniRoute, or any OpenAI-compatible API |
| TTS | Fish Audio, macOS `say`, or Piper (local neural TTS) |
| System | AppleScript for all macOS integrations (no OAuth needed) |

## How the Voice Loop Works

1. You speak into your microphone
2. Chrome's Web Speech API transcribes your speech in real-time
3. The transcript is sent to the server via WebSocket
4. JARVIS detects intent -- conversation, action, or build request
5. For actions: spawns a Claude Code subprocess or runs AppleScript
6. Generates a response via the configured LLM (optimized for speed)
7. TTS converts the response to speech with the JARVIS voice
8. Audio streams back to the browser via WebSocket
9. The Three.js orb deforms and pulses in response to the audio
10. Background tasks notify you proactively when they complete

## Key Files

| File | Purpose |
|------|---------|
| `server.py` | Main server -- WebSocket handler, LLM, action system |
| `frontend/src/orb.ts` | Three.js particle orb visualization |
| `frontend/src/voice.ts` | Web Speech API + audio playback |
| `frontend/src/main.ts` | Frontend state machine |
| `memory.py` | SQLite memory system (facts/tasks/notes) with FTS5 full-text search |
| `conversation_memory.py` | Persistent raw chat-transcript history + recall across sessions |
| `calendar_access.py` | Apple Calendar integration via AppleScript (read/write) |
| `mail_access.py` | Apple Mail integration (read/send) |
| `write_integrations.py` | Send/draft mail, create calendar events, send iMessages |
| `notes_access.py` | Apple Notes integration |
| `music_control.py` | Music.app / Spotify playback control via AppleScript |
| `actions.py` | System actions (Terminal, Chrome, Claude Code) |
| `browser.py` | Playwright web automation |
| `work_mode.py` | Persistent Claude Code sessions |
| `planner.py` | Multi-step task planning with smart questions |
| `llm_provider.py` | Pluggable LLM backends (Anthropic/Gemini/OpenAI-compatible) with rate-limit fallback chain |

## Features in Detail

### Action System
JARVIS uses action tags to trigger real system actions:
- `[ACTION:BUILD]` -- spawns Claude Code to build a project
- `[ACTION:BROWSE]` -- opens Chrome to a URL or search query
- `[ACTION:RESEARCH]` -- deep research with the configured deep model, outputs an HTML report
- `[ACTION:PROMPT_PROJECT]` -- connects to an existing project via Claude Code
- `[ACTION:ADD_TASK]` -- creates a tracked task with priority and due date
- `[ACTION:REMEMBER]` -- stores a fact for future context
- `[ACTION:DRAFT_REPLY]` -- reads an email and leaves a reply sitting in Mail as a draft (never sends)
- `[ACTION:SEND_EMAIL]` -- composes and sends a new email immediately (no confirmation step)
- `[ACTION:CREATE_EVENT]` -- creates a new Calendar event from natural-language time ("tomorrow 3pm")
- `[ACTION:SEND_MESSAGE]` -- sends an iMessage/SMS immediately
- `[ACTION:MUSIC]` -- play/pause/skip/volume/now-playing on Music.app or Spotify (most direct
  commands are also handled instantly without an LLM round trip)
- `[ACTION:RECALL]` -- searches past conversations across sessions

### Memory System
JARVIS remembers things you tell it using SQLite with FTS5 full-text search. Preferences, decisions, and facts persist across sessions. Separately, `conversation_memory.py` keeps the raw back-and-forth transcript so JARVIS can recall what you talked about, not just durable facts.

### Calendar & Mail
All macOS integrations use AppleScript -- no OAuth flows, no token management. Just native system access. JARVIS can read and write both: it drafts replies for review by default, but will compose-and-send a new email or calendar invite immediately when you clearly ask it to -- there's no confirmation step, so be specific when you want a send rather than a draft.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines. Some areas that could use work:

- **Linux/Windows support** -- replace AppleScript with cross-platform alternatives
- **Alternative TTS engines** -- add ElevenLabs, OpenAI TTS, or local models
- **Mobile client** -- a companion app for voice interaction on the go
- **Plugin system** -- make it easy to add new actions and integrations

Please open an issue before submitting large PRs so we can discuss the approach.

## License

MIT License. See [LICENSE](LICENSE) for details.

## Credits

Originally inspired by [ethanplusai/jarvis](https://github.com/ethanplusai/jarvis).

Powered by [Anthropic Claude](https://anthropic.com), [Fish Audio](https://fish.audio), and the open-source AI community.

Inspired by the AI that started it all -- Tony Stark's JARVIS.

> **Disclaimer:** This is an independent fan project and is not affiliated with, endorsed by, or connected to Marvel Entertainment, The Walt Disney Company, or any related entities. The JARVIS name and character are property of Marvel Entertainment.
