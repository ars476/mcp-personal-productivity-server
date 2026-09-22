"""
MCP Personal Productivity Server
Domain: Personal Productivity (Calendar + Tasks)
Tools: create_calendar_event, add_task
Prompt: daily_briefing

Portions of the OAuth flow adapted from Google's official quickstart:
https://developers.google.com/calendar/api/quickstart/python
(cited per assignment requirement)
"""

import os
import re
import pathlib
from datetime import datetime

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
]

CREDENTIALS_PATH = pathlib.Path(os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json"))
TOKEN_PATH = pathlib.Path(os.environ.get("GOOGLE_TOKEN_PATH", "token.json"))

mcp = FastMCP("personal-productivity")


def get_google_credentials():
    """Handles OAuth login and token refresh/storage."""
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())
    return creds


# ---------- Best Practice 1: Input Sanitization ----------
# Blocks control characters and obvious script/command injection patterns
# before any string is used in an API call or logged/echoed back.
_UNSAFE_PATTERN = re.compile(r"[\x00-\x1f\x7f]|<script|;--|`|\$\(")

def sanitize_text(value: str, field_name: str, max_len: int = 500) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    if len(value) > max_len:
        raise ValueError(f"{field_name} exceeds {max_len} characters")
    if _UNSAFE_PATTERN.search(value):
        raise ValueError(f"{field_name} contains disallowed characters")
    return value.strip()


def sanitize_iso_datetime(value: str, field_name: str) -> str:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field_name} must be a valid ISO 8601 datetime, e.g. 2026-10-01T14:00:00")
    return value


# ---------- Best Practice 2: Error Disclosure ----------
# Wraps any Google API exception into a generic, safe message. Full details
# are printed server-side (for the developer) but never returned to the caller.

def safe_error(context: str, exc: Exception) -> dict:
    print(f"[SERVER LOG] {context}: {repr(exc)}")  # full detail stays server-side only
    return {
        "success": False,
        "error": f"{context} failed. Please check your input and try again.",
    }


@mcp.tool()
def create_calendar_event(title: str, start_time: str, end_time: str, description: str = "") -> dict:
    """
    Create an event on the user's primary Google Calendar.

    Args:
        title: Event title (max 200 chars)
        start_time: ISO 8601 datetime, e.g. 2026-10-01T14:00:00
        end_time: ISO 8601 datetime, e.g. 2026-10-01T15:00:00
        description: Optional event description (max 500 chars)
    """
    try:
        title = sanitize_text(title, "title", max_len=200)
        description = sanitize_text(description, "description", max_len=500) if description else ""
        start_time = sanitize_iso_datetime(start_time, "start_time")
        end_time = sanitize_iso_datetime(end_time, "end_time")

        creds = get_google_credentials()
        service = build("calendar", "v3", credentials=creds)

        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_time},
            "end": {"dateTime": end_time},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()
        return {"success": True, "event_id": created.get("id"), "link": created.get("htmlLink")}

    except ValueError as ve:
        return {"success": False, "error": str(ve)}  # safe: our own validation message
    except HttpError as he:
        return safe_error("Calendar event creation", he)
    except Exception as e:
        return safe_error("Calendar event creation", e)


@mcp.tool()
def add_task(title: str, notes: str = "", due_date: str = "") -> dict:
    """
    Add a task to the user's default Google Tasks list.

    Args:
        title: Task title (max 200 chars)
        notes: Optional notes (max 500 chars)
        due_date: Optional ISO 8601 date, e.g. 2026-10-01
    """
    try:
        title = sanitize_text(title, "title", max_len=200)
        notes = sanitize_text(notes, "notes", max_len=500) if notes else ""
        if due_date:
            sanitize_iso_datetime(due_date + "T00:00:00", "due_date")

        creds = get_google_credentials()
        service = build("tasks", "v1", credentials=creds)

        body = {"title": title, "notes": notes}
        if due_date:
            body["due"] = due_date + "T00:00:00.000Z"

        created = service.tasks().insert(tasklist="@default", body=body).execute()
        return {"success": True, "task_id": created.get("id")}

    except ValueError as ve:
        return {"success": False, "error": str(ve)}
    except HttpError as he:
        return safe_error("Task creation", he)
    except Exception as e:
        return safe_error("Task creation", e)


@mcp.prompt()
def daily_briefing() -> str:
    """Prompt template that asks Claude to summarize today's calendar and tasks."""
    return (
        "Please give me a concise daily briefing. "
        "First, check my calendar for today's events using available tools/context, "
        "then list my open tasks, and finally suggest a realistic order to tackle them in, "
        "flagging anything that looks like a time conflict."
    )


if __name__ == "__main__":
    mcp.run()