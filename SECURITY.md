# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in JARVIS, please report it responsibly.

**Email:** scott.kanowski@gmail.com

**Please include:**
- Description of the vulnerability
- Steps to reproduce
- Potential impact

Please do **not** open a public GitHub issue for security vulnerabilities.

## Important Security Notes

JARVIS handles sensitive system integrations (email, calendar, messages). Key things to know:

- **Email sending is immediate** -- `[ACTION:SEND_EMAIL]` sends without a confirmation step. This is by design for voice UX, but contributors should be aware.
- **iMessage sending is immediate** -- same as email.
- **AppleScript injection** -- all user input passed to AppleScript is escaped via `applescript_escape()` in `actions.py`. A prior injection vulnerability was fixed and is regression-tested. Always use this function.
- **No data leaves your Mac** beyond configured LLM and TTS API calls.
- **API keys** are stored in `.env` (gitignored) and never logged or transmitted.

## Scope

This policy covers the JARVIS codebase. Third-party dependencies (Anthropic SDK, Fish Audio, etc.) have their own security policies.
