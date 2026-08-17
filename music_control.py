"""
JARVIS Music Control — Apple Music (Music.app) and Spotify via AppleScript.
"""

import asyncio
import logging

log = logging.getLogger("jarvis.music")


def _escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


async def _run(script: str, timeout: float = 8) -> tuple[bool, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0:
            return True, stdout.decode().strip()
        return False, stderr.decode().strip()
    except asyncio.TimeoutError:
        return False, "timed out"
    except Exception as e:
        return False, str(e)


async def _app_running(name: str) -> bool:
    ok, out = await _run(f'tell application "System Events" to (name of processes) contains "{name}"')
    return ok and out == "true"


async def _preferred_app() -> str:
    """Return 'Spotify' if Spotify is open, else 'Music'."""
    return "Spotify" if await _app_running("Spotify") else "Music"


async def play(query: str = "") -> dict:
    app = await _preferred_app()
    if query:
        q = _escape(query)
        if app == "Spotify":
            # Spotify AppleScript: search then play — best-effort via URI
            script = f'''
            tell application "Spotify"
                activate
                play track "spotify:search:{q}"
            end tell'''
        else:
            # Apple Music: search library, play first result
            script = f'''
            tell application "Music"
                activate
                set results to (every track of library playlist 1 whose name contains "{q}" or artist contains "{q}")
                if (count of results) > 0 then
                    play item 1 of results
                    return "playing"
                end if
                return "not_found"
            end tell'''
        ok, out = await _run(script)
        if ok and out in ("playing", ""):
            return {"ok": True, "message": f"Playing {query} on {app}"}
        if ok and out == "not_found":
            return {"ok": False, "message": f"No {query} in your library"}
        return {"ok": False, "message": out}
    ok, out = await _run(f'tell application "{app}" to play')
    return {"ok": ok, "message": f"Playing on {app}" if ok else out}


async def pause() -> dict:
    app = await _preferred_app()
    ok, out = await _run(f'tell application "{app}" to pause')
    return {"ok": ok, "message": "Paused" if ok else out}


async def next_track() -> dict:
    app = await _preferred_app()
    ok, out = await _run(f'tell application "{app}" to next track')
    return {"ok": ok, "message": "Skipped" if ok else out}


async def previous_track() -> dict:
    app = await _preferred_app()
    ok, out = await _run(f'tell application "{app}" to previous track')
    return {"ok": ok, "message": "Previous track" if ok else out}


async def set_volume(level: int) -> dict:
    """Set system output volume 0-100."""
    level = max(0, min(100, int(level)))
    ok, out = await _run(f'set volume output volume {level}')
    return {"ok": ok, "message": f"Volume {level}%" if ok else out}


async def now_playing() -> dict:
    app = await _preferred_app()
    if not await _app_running(app):
        return {"ok": False, "message": f"{app} not running"}
    script = f'''
    tell application "{app}"
        if player state is playing then
            set trackName to name of current track
            set artistName to artist of current track
            return trackName & " — " & artistName
        end if
        return "not_playing"
    end tell'''
    ok, out = await _run(script)
    if ok and out != "not_playing":
        return {"ok": True, "message": out, "app": app}
    return {"ok": True, "message": "Nothing playing", "app": app}
