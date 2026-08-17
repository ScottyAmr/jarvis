"""
JARVIS Write Integrations — send email, create calendar events, reply to messages.

Uses AppleScript so nothing leaves the Mac. All operations return a status dict
so the voice layer can confirm success or explain failure.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta

log = logging.getLogger("jarvis.write")


def _escape_applescript(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


async def _run_applescript(script: str, timeout: float = 15) -> tuple[bool, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0:
            return True, stdout.decode().strip()
        return False, stderr.decode().strip() or "AppleScript failed"
    except asyncio.TimeoutError:
        return False, "AppleScript timed out"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Mail
# ---------------------------------------------------------------------------

async def send_email(to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> dict:
    """Compose and SEND a new email via Mail.app. Returns {ok, message}."""
    to = _escape_applescript(to)
    subject = _escape_applescript(subject)
    body = _escape_applescript(body)
    cc = _escape_applescript(cc)
    bcc = _escape_applescript(bcc)

    cc_block = f'make new cc recipient at end of cc recipients with properties {{address:"{cc}"}}' if cc else ""
    bcc_block = f'make new bcc recipient at end of bcc recipients with properties {{address:"{bcc}"}}' if bcc else ""

    script = f'''
    tell application "Mail"
        set newMessage to make new outgoing message with properties {{visible:false, subject:"{subject}", content:"{body}"}}
        tell newMessage
            make new to recipient at end of to recipients with properties {{address:"{to}"}}
            {cc_block}
            {bcc_block}
        end tell
        send newMessage
    end tell
    return "sent"
    '''
    ok, out = await _run_applescript(script, timeout=20)
    if ok:
        log.info(f"Sent email to {to}: {subject[:40]}")
        return {"ok": True, "message": f"Sent to {to}"}
    log.warning(f"Send email failed: {out}")
    return {"ok": False, "message": out}


async def create_draft(to: str, subject: str, body: str) -> dict:
    """Create a Mail.app draft without sending it. Safer default."""
    to = _escape_applescript(to)
    subject = _escape_applescript(subject)
    body = _escape_applescript(body)
    script = f'''
    tell application "Mail"
        set newMessage to make new outgoing message with properties {{visible:true, subject:"{subject}", content:"{body}"}}
        tell newMessage
            make new to recipient at end of to recipients with properties {{address:"{to}"}}
        end tell
        activate
    end tell
    return "drafted"
    '''
    ok, out = await _run_applescript(script, timeout=15)
    if ok:
        return {"ok": True, "message": f"Draft opened for {to}"}
    return {"ok": False, "message": out}


async def reply_to_message(subject_search: str, reply_body: str) -> dict:
    """Reply to the most recent inbox message matching subject_search. Saves as draft."""
    subject_search = _escape_applescript(subject_search)
    reply_body = _escape_applescript(reply_body)
    script = f'''
    tell application "Mail"
        set found to missing value
        repeat with acct in accounts
            repeat with mbx in mailboxes of acct
                try
                    set msgs to (messages of mbx whose subject contains "{subject_search}")
                    if (count of msgs) > 0 then
                        set found to item 1 of msgs
                        exit repeat
                    end if
                end try
            end repeat
            if found is not missing value then exit repeat
        end repeat
        if found is missing value then
            return "not_found"
        end if
        set replyMsg to reply found with opening window without reply to all
        delay 0.5
        tell replyMsg
            set content to "{reply_body}" & return & return & (content as string)
        end tell
        activate
        return "drafted"
    end tell
    '''
    ok, out = await _run_applescript(script, timeout=20)
    if ok and out == "drafted":
        return {"ok": True, "message": "Reply drafted"}
    if ok and out == "not_found":
        return {"ok": False, "message": "No matching message found"}
    return {"ok": False, "message": out or "Reply failed"}


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def _parse_datetime(when: str) -> tuple[str, str]:
    """Best-effort natural language date parsing → (YYYY-MM-DD, HH:MM).
    Handles: 'tomorrow 3pm', '2026-08-20 14:00', 'friday 10am', 'in 2 hours'."""
    now = datetime.now()
    t = (when or "").lower().strip()

    # Explicit ISO date
    m = re.search(r"(\d{4}-\d{2}-\d{2})(?:\s+(\d{1,2}):?(\d{2})?)?", t)
    if m:
        date = m.group(1)
        hh = int(m.group(2) or 9)
        mm = int(m.group(3) or 0)
        return date, f"{hh:02d}:{mm:02d}"

    # "in N hours" / "in N minutes"
    m = re.search(r"in (\d+)\s*(hour|minute|day)", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = {"hour": timedelta(hours=n), "minute": timedelta(minutes=n),
                 "day": timedelta(days=n)}[unit]
        dt = now + delta
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")

    # Base date
    if "tomorrow" in t:
        base = now + timedelta(days=1)
    elif "today" in t or "tonight" in t:
        base = now
    else:
        # weekday name
        weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        base = now
        for i, wd in enumerate(weekdays):
            if wd in t:
                today_wd = now.weekday()
                days = (i - today_wd) % 7
                if days == 0:
                    days = 7
                base = now + timedelta(days=days)
                break

    # Time: "3pm", "10:30am", "14:00"
    hh, mm = 9, 0
    tm = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if tm:
        hh = int(tm.group(1))
        mm = int(tm.group(2) or 0)
        ap = tm.group(3)
        if ap == "pm" and hh < 12:
            hh += 12
        elif ap == "am" and hh == 12:
            hh = 0
        # if no am/pm and hh looks like a wall-clock time
    if "tonight" in t and hh < 18:
        hh += 12

    return base.strftime("%Y-%m-%d"), f"{hh:02d}:{mm:02d}"


async def create_calendar_event(title: str, when: str, duration_minutes: int = 60,
                          location: str = "", notes: str = "",
                          calendar: str = "Home") -> dict:
    """Create an event via Calendar.app."""
    date_str, time_str = _parse_datetime(when)
    try:
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except Exception:
        return {"ok": False, "message": f"Couldn't parse when: {when}"}
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    title_e = _escape_applescript(title)
    location_e = _escape_applescript(location)
    notes_e = _escape_applescript(notes)
    calendar_e = _escape_applescript(calendar)

    start_apple = start_dt.strftime("%m/%d/%Y %H:%M")
    end_apple = end_dt.strftime("%m/%d/%Y %H:%M")

    script = f'''
    tell application "Calendar"
        set targetCal to missing value
        repeat with c in calendars
            if name of c is "{calendar_e}" then
                set targetCal to c
                exit repeat
            end if
        end repeat
        if targetCal is missing value then
            set targetCal to first calendar
        end if
        tell targetCal
            set newEvent to make new event with properties {{summary:"{title_e}", start date:date "{start_apple}", end date:date "{end_apple}", location:"{location_e}", description:"{notes_e}"}}
        end tell
    end tell
    return "created"
    '''
    ok, out = await _run_applescript(script, timeout=20)
    if ok:
        return {"ok": True, "message": f"Event '{title}' created for {date_str} at {time_str}",
                "date": date_str, "time": time_str}
    return {"ok": False, "message": out}


# ---------------------------------------------------------------------------
# Messages (iMessage)
# ---------------------------------------------------------------------------

async def send_imessage(to: str, body: str) -> dict:
    """Send an iMessage (or SMS) via Messages.app. `to` should be phone or email."""
    to_e = _escape_applescript(to)
    body_e = _escape_applescript(body)
    script = f'''
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant "{to_e}" of targetService
        send "{body_e}" to targetBuddy
    end tell
    return "sent"
    '''
    ok, out = await _run_applescript(script, timeout=15)
    if ok:
        return {"ok": True, "message": f"Sent to {to}"}
    return {"ok": False, "message": out}
