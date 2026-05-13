"""
InboxIQ — Flask MVP: structured inbox intelligence from email text.

Run: python3 app.py

Modes:
- Demo (/): curated sample emails — works without Gmail or OpenAI keys (heuristic fallback).
- Live (/live-inbox): optional Gmail OAuth + recent inbox fetch (readonly scope).

Secrets: use `.env` for OPENAI_API_KEY; use credentials.json + token.json for Gmail OAuth
(never commit those files — see `.gitignore` and README).
"""

import base64
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from openai import APIError, OpenAI

# Load variables from `.env` in the project root (including OPENAI_API_KEY).
load_dotenv()

# OpenAI key: edit the `.env` file in this same folder (copy from `.env.example`).
# Replace the placeholder value on the OPENAI_API_KEY line — e.g.
#   OPENAI_API_KEY=sk-proj-your-real-secret-here
# Do not paste keys into app.py or commit `.env` to git.

app = Flask(__name__)

# Paths resolved from this file so the app works no matter the cwd.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Gmail OAuth: readonly access is enough to fetch messages for analysis demos.
# Recruiters: tokens live in token.json after /connect-gmail; never commit that file.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS_PATH = os.path.join(PROJECT_ROOT, "credentials.json")
TOKEN_PATH = os.path.join(PROJECT_ROOT, "token.json")

# Pre-demo splash: Gmail compose URL for OAuth test-user requests (demo route only).
SPLASH_TEST_ACCESS_GMAIL_COMPOSE_URL = (
    "https://mail.google.com/mail/?view=cm&fs=1&to=christiandhopoku8@gmail.com"
    "&su=InboxIQ%20Test%20Access%20Request"
    "&body=Hi%20Christian,%0A%0AI%20would%20like%20to%20test%20InboxIQ%20with%20my%20Gmail%20account.%20Please%20add%20this%20email%20as%20an%20approved%20OAuth%20test%20user.%0A%0AEmail:%0AName/Organization:%0A%0AThank%20you."
)

# -----------------------------------------------------------------------------
# Six messy sample threads for recruiter-ready demos (no Gmail connection).
# Archetypes: urgent exec deadline, calendar update, colleague follow-up,
# FYI newsletter, internship/recruiter outreach, professor/course deadline.
# -----------------------------------------------------------------------------
SAMPLE_EMAILS = [
    # 1) Urgent executive / same-day deadline
    {
        "sender": "Rachel Ortiz <rachel.ortiz@northpeaklabs.com>",
        "subject": "URGENT — board appendix / redlines needed tonight",
        "body": """hey — sorry for late ping

GC wants the revised risk appendix + signature packet bundled for tomorrow's partner breakfast. Legal says we MUST have clean PDFs **by 6pm ET tonight** (non negotiable)

can youincorporate yesterday's comments + export final PDFs and drop in the #board-prep folder?? if blocked call my cell

thx,
rachel

Sent from iPhone""",
    },
    # 2) Scheduling / calendar logistics
    {
        "sender": "noreply@calendar.acme.team",
        "subject": "Updated: Product sync → Google Meet (was conference room)",
        "body": """Hello,

Your event 'Product sync w/ Design' has changed.

When: Thursday 4:30pm–5:15pm ET (moved 30 min later)
Where: Google Meet (link in invite)

Please RSVP yes/no — PM wants decisions on Q3 scope before Friday.

– Calendar""",
    },
    # 3) Follow-up request (colleague chasing a deliverable)
    {
        "sender": "Leo Park <leo.park@acme.team>",
        "subject": "Re: cleaned CSV for funnel dashboard???",
        "body": """bumping this — still waiting on the cleaned export from Snowflake

finance needs it for tomorrow's review and i'm kinda blocked until i have v2

can you send today?? even partial columns ok if thats faster

lp""",
    },
    # 4) FYI newsletter
    {
        "sender": "The Weekly Stack <newsletter@weeklystack.dev>",
        "subject": "Issue 402 — wasm + edge trends (no reply needed)",
        "body": """Hey,

Quick FYI digest for builders.

No action required — skim if useful.

Highlights:
- WASM adoption notes
- Edge caching cheat sheet

Unsubscribe any time (link below).

— WS team""",
    },
    # 5) Internship / recruiter outreach
    {
        "sender": "Jordan Miles <universitytalent@globalcircuit.io>",
        "subject": "HackHarvard internship — next step / phone screen?",
        "body": """Hi — loved your submission during the career fair!

We're moving fast on our summer SWE internship pipeline. Could you reply with **3 times you're free this week** for a 20min phone screen?

Also attach PDF resume if you havent already (ATS friendly pls).

Best,
Jordan | University Recruiting
GlobalCircuit""",
    },
    # 6) Professor / class deadline
    {
        "sender": 'Prof. A. Kim <akim@cs.harvard.edu>',
        "subject": "CS 161 — PS3 reminder + extension policy",
        "body": """Hi everyone,

Friendly reminder: Problem Set 3 is due **Sunday 11:59pm ET** on Gradescope.

If you need an extension, email me **before** the deadline with a concrete plan — blanket extensions won't be granted after Sunday night.

Office hours Fri 3–5pm Science Center rm 209.

— AK""",
    },
]


def build_search_blob(sender: str, subject: str, analysis: dict[str, Any]) -> str:
    """Lowercased concatenation for client-side search (no secrets)."""
    parts = [
        sender,
        subject,
        analysis.get("task_summary", ""),
        analysis.get("deadline", ""),
        analysis.get("suggested_reply", ""),
    ]
    return " ".join(parts).lower()


def get_gmail_service():
    """
    Build an authenticated Gmail API service using token.json on disk.
    Refreshes expired access tokens when a refresh_token is present.
    Returns None if the user has not completed OAuth yet or refresh fails.
    """
    if not os.path.isfile(TOKEN_PATH):
        return None
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_PATH, "w", encoding="utf-8") as token_file:
                token_file.write(creds.to_json())
        else:
            return None
    return build("gmail", "v1", credentials=creds)


def _gmail_header(headers: list[dict[str, str]], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value") or ""
    return ""


def _extract_plain_body(payload: dict[str, Any]) -> str:
    """Depth-first collect text/plain parts from a Gmail message payload."""
    mime = payload.get("mimeType") or ""
    body = payload.get("body") or {}
    data = body.get("data")
    if data and mime == "text/plain":
        try:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError):
            return ""
    texts: list[str] = []
    for part in payload.get("parts") or []:
        chunk = _extract_plain_body(part)
        if chunk.strip():
            texts.append(chunk)
    return "\n".join(texts).strip()


def _parse_gmail_api_message(msg: dict[str, Any]) -> dict[str, str]:
    """Map a Gmail API message resource to the same dict shape as SAMPLE_EMAILS."""
    payload = msg.get("payload") or {}
    headers = payload.get("headers") or []
    sender = _gmail_header(headers, "From") or "(unknown sender)"
    subject = _gmail_header(headers, "Subject") or "(no subject)"
    snippet = (msg.get("snippet") or "").strip()
    body_text = _extract_plain_body(payload)
    if not body_text:
        body_text = snippet
    # Cap body size for model + UI stability (full thread bodies can be huge).
    body_text = body_text.strip()[:15000]
    return {"sender": sender, "subject": subject, "body": body_text}


def fetch_recent_gmail_messages(max_results: int = 10) -> list[dict[str, str]]:
    """
    Fetch recent inbox message IDs, pull full messages, and normalize fields.
    Returns [] if Gmail is not authenticated or the API raises an error.
    """
    service = get_gmail_service()
    if service is None:
        return []
    try:
        listed = (
            service.users()
            .messages()
            .list(userId="me", labelIds=["INBOX"], maxResults=max_results)
            .execute()
        )
        ids = [m["id"] for m in listed.get("messages", [])]
        out: list[dict[str, str]] = []
        for mid in ids:
            full = (
                service.users()
                .messages()
                .get(userId="me", id=mid, format="full")
                .execute()
            )
            out.append(_parse_gmail_api_message(full))
        return out
    except HttpError:
        return []


def _analyzed_record_from_raw(email: dict[str, Any]) -> dict[str, Any]:
    """Single-email analyze pipeline used by analyze_email_records (safe for parallel calls)."""
    structured = analyze_email(
        email["sender"],
        email["subject"],
        email["body"],
    )
    preview = email["body"].replace("\n", " ").strip()
    if len(preview) > 220:
        preview = preview[:217] + "..."
    return {
        "sender": email["sender"],
        "subject": email["subject"],
        "body_preview": preview,
        "analysis": structured,
        "search_blob": build_search_blob(
            email["sender"], email["subject"], structured
        ),
    }


def analyze_email_records(raw_emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run analyze_email over each raw row; order matches raw_emails. Uses modest parallelism when len > 1."""
    if not raw_emails:
        return []
    if len(raw_emails) == 1:
        return [_analyzed_record_from_raw(raw_emails[0])]
    # Bounded parallelism speeds Live/Demo when OpenAI is enabled without changing card semantics/order.
    workers = min(len(raw_emails), 5)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(_analyzed_record_from_raw, row) for row in raw_emails
        ]
        return [f.result() for f in futures]


def compute_stats_from_emails(emails: list[dict[str, Any]]) -> dict[str, int]:
    """Aggregate dashboard counts from analyzed email records."""
    analyses = [e["analysis"] for e in emails]
    return {
        "total": len(emails),
        "action_needed": sum(1 for a in analyses if a["category"] == "Action Needed"),
        "scheduling": sum(1 for a in analyses if a["category"] == "Schedule"),
        "follow_ups": sum(1 for a in analyses if a["category"] == "Follow-up"),
        "urgent": sum(1 for a in analyses if a["category"] == "Urgent"),
    }


def get_openai_client() -> Optional[OpenAI]:
    """Return OpenAI client if API key is configured; otherwise None."""
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or key == "your_openai_api_key_here":
        return None
    return OpenAI(api_key=key)


def _extract_json_object(text: str) -> Optional[str]:
    """Try to pull a JSON object from model output (handles markdown fences)."""
    if not text:
        return None
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    match = re.search(r"\{[\s\S]*\}", cleaned)
    return match.group(0) if match else None


# Categories and priorities must match the dashboard and product rules exactly.
VALID_CATEGORIES = frozenset(
    {
        "Action Needed",
        "Schedule",
        "Follow-up",
        "FYI",
        "Urgent",
    }
)

# Exact keys the model and UI expect (JSON-only contract).
ANALYSIS_KEYS = (
    "category",
    "priority",
    "task_summary",
    "deadline",
    "scheduling_need",
    "suggested_reply",
    "reason",
)


def _rb_has_job_intent(combined: str, sender: str) -> bool:
    """True when message looks like recruiting / roles / applications (live Gmail)."""
    if re.search(r"\bjob\b", combined) or re.search(r"\bintern\b", combined):
        return True
    terms = (
        "internship",
        "summer intern",
        "recruiter",
        "application",
        "interview",
        "opportunity",
        "careers@",
        "jobs@",
        "talent@",
        "hiring",
        "new role",
        "your application",
    )
    return any(t in combined for t in terms) or "recruiting" in sender.lower()


def _rb_promotional_fyi(combined: str, sender: str) -> bool:
    """Marketing, newsletters, digests — FYI once higher-intent rules did not match."""
    sl = sender.lower()
    strong = (
        "deal",
        "sale",
        "discount",
        "% off",
        "amazon.com",
        "amazon ",
        "@amazon.",
        "newsletter",
        "digest",
        "quora",
        "subscription",
        "unsubscribe",
        "manage preferences",
        "promotional",
    )
    if any(x in combined for x in strong):
        return True
    if "linkedin" in combined and ("news" in combined or "digest" in combined):
        return True
    if "discover" in combined and (
        "cashback" in combined or "offer" in combined or "save" in combined
    ):
        return True
    if "discover" in sl:
        return True
    # Weak signals: avoid classifying work "status update" threads as promo.
    if "alert" in combined and (
        "deal" in combined
        or "sale" in combined
        or "newsletter" in combined
        or "digest" in combined
        or "subscribe" in combined
        or "unsubscribe" in combined
    ):
        return True
    if "update" in combined and (
        "newsletter" in combined
        or "digest" in combined
        or "subscription" in combined
        or "unsubscribe" in combined
        or "marketing" in combined
    ):
        return True
    return False


def _rb_scheduling_like(combined: str, sender: str) -> bool:
    """Meeting / calendar logistics."""
    if (
        "noreply@" in sender.lower()
        and ("calendar" in sender.lower() or "meeting" in combined or "event" in combined)
    ):
        return True
    keys = (
        "google meet",
        "microsoft teams",
        "teams meeting",
        "zoom",
        "reschedule",
        "calendar invite",
        "ical",
        ".ics",
    )
    if any(k in combined for k in keys):
        return True
    if "meeting" in combined and (
        "invite" in combined
        or "invitation" in combined
        or "calendar" in combined
        or "join" in combined
        or "scheduled" in combined
    ):
        return True
    if "appointment" in combined and ("confirm" in combined or "scheduled" in combined):
        return True
    if "availability" in combined and (
        "meet" in combined or "call" in combined or "time slot" in combined or "schedule" in combined
    ):
        return True
    if ("invite" in combined or "invitation" in combined) and (
        "when" in combined or "time" in combined or "calendar" in combined
    ):
        return True
    return False


def _rb_followup_language(combined: str, scheduling_like: bool) -> bool:
    """Human follow-up / chase threads (not calendar meeting reminders)."""
    phrases = (
        "following up",
        "following-up",
        "check in",
        "checking in",
        "circling back",
        "looping back",
        "any update",
        "any updates",
        "wanted to follow",
        "gentle nudge",
        "bumping this",
        "still waiting",
    )
    if any(p in combined for p in phrases):
        return True
    if "reminder" in combined and not scheduling_like:
        return True
    return False


def _rb_urgent_timeline(combined: str, subject_l: str, promo_today: bool) -> bool:
    """Time-critical asks (guarded from promo 'today only' spam)."""
    if promo_today:
        return False
    head = combined[:400]
    urgent_kw = (
        "urgent",
        "asap",
        "immediately",
        "right away",
        "deadline",
        "due tonight",
        "due today",
        "by eod",
        "by end of day",
        "by 5pm",
        "by 6pm",
        "by 5 pm",
        "by 6 pm",
        "5pm",
        "6pm",
        "5 pm",
        "6 pm",
    )
    if any(k in head or k in subject_l for k in ("urgent", "asap")):
        return True
    if "deadline" in combined or re.search(r"\bdue\b", combined):
        return True
    if "tonight" in combined:
        return True
    if "today" in combined and not _rb_promo_today_scan(combined):
        return True
    return any(k in combined for k in urgent_kw)


def _rb_promo_today_scan(combined: str) -> bool:
    """Heuristic: sale language + today → treat as promo noise, not deadline urgency."""
    if "today" not in combined:
        return False
    return bool(
        re.search(r"\b(sale|deal|discount|% off|offer|flash)\b", combined)
        or "today only" in combined
        or "ends tonight" in combined
    )


def rule_based_analysis(sender: str, subject: str, body: str) -> dict[str, Any]:
    """
    Heuristic analyzer when OpenAI is unavailable or returns unusable JSON.
    Tuned for real Gmail mixed with demo samples: promotional mail → FYI, roles → Action Needed,
    meetings → Schedule, time-critical → Urgent, gentle chasers → Follow-up (ordered rules matter).
    """
    combined = f"{sender}\n{subject}\n{body}".lower()
    subject_l = subject.lower()
    body_one_line = re.sub(r"\s+", " ", body.strip())

    scheduling_like = _rb_scheduling_like(combined, sender)
    promo_today_flag = _rb_promo_today_scan(combined)

    # --- Security / incident → Urgent ---
    if (
        "security incident" in combined
        or "unauthorized api access" in combined
        or ("urgent" in combined and "rotate api keys" in combined)
        or ("immediate review" in combined and "vendor" in sender.lower())
    ):
        return {
            "category": "Urgent",
            "priority": "High",
            "task_summary": (
                "Treat as a security incident: rotate API keys immediately, review audit logs "
                "for suspicious activity, and send the vendor an acknowledgment within their "
                "requested timeframe."
            ),
            "deadline": (
                "Vendor requests acknowledgment within 24 hours; remediation (key rotation, "
                "log review) should start immediately."
            ),
            "scheduling_need": (
                "Consider a short internal bridge with security/engineering after keys are rotated."
            ),
            "suggested_reply": (
                "Hello — we received your security notice and are prioritizing it. We have begun "
                "rotating API keys and reviewing audit logs. We acknowledge receipt and will follow "
                "up with findings or questions shortly."
            ),
            "reason": (
                "Keywords and tone indicate an active security incident with mandatory customer "
                "actions and a defined acknowledgment window — categorized as Urgent with High priority."
            ),
        }

    # --- Jobs, internships, recruiting → Action Needed ---
    if _rb_has_job_intent(combined, sender):
        job_pri = (
            "High"
            if (
                "interview" in combined
                or ("application" in combined and ("deadline" in combined or "closing" in combined))
                or subject_l.startswith("urgent")
                or subject_l.startswith("re: urgent")
            )
            else "Medium"
        )
        return {
            "category": "Action Needed",
            "priority": job_pri,
            "task_summary": (
                "Career or recruiting thread — respond to next-step asks (availability, resume, "
                "application tasks, or interview logistics) so you stay in the pipeline."
            ),
            "deadline": (
                "Treat recruiter timelines as soon as practical—many flows move on within 24–72 hours."
            ),
            "scheduling_need": (
                "If they requested times, reply with a few concrete slots and your time zone."
            ),
            "suggested_reply": (
                "Hi — thank you for reaching out. I'm interested and happy to proceed. "
                "I'm available for a brief conversation at [list 2–3 windows] (timezone). "
                "Let me know if you need anything else from me."
            ),
            "reason": (
                "Detected recruiting/job/internship vocabulary ahead of bulk-mail patterns — "
                "Action Needed with Medium/High priority based on urgency cues."
            ),
        }

    # --- Meetings / calendar / video calls → Schedule ---
    if scheduling_like or (
        "please confirm you can make it" in combined and "time:" in combined
    ):
        return {
            "category": "Schedule",
            "priority": "Medium",
            "task_summary": (
                "Calendar-driven thread — confirm attendance, note time zone, "
                "and capture dial-in or Meet/Zoom details."
            ),
            "deadline": (
                "Respond before the meeting start if your availability changed; join at the scheduled time."
            ),
            "scheduling_need": (
                "Accept/decline the invite or propose alternate slots if none of the proposed times work."
            ),
            "suggested_reply": (
                "Thanks — I've reviewed the invite and can make the proposed time. "
                "I'll accept on the calendar and join via the provided link. "
                "I'll reply right away if a conflict comes up."
            ),
            "reason": (
                "Detected meeting, invite, reschedule, or conferencing cues typical of scheduling mail."
            ),
        }

    # --- Invoice / payment follow-up → Follow-up ---
    if (
        "invoice" in combined
        and ("payment" in combined or "accounting" in combined or "net 15" in combined)
    ) or ("haven't seen payment" in combined or "have not seen payment" in combined):
        return {
            "category": "Follow-up",
            "priority": "Medium",
            "task_summary": (
                "Confirm accounts payable received the referenced invoice and whether payment "
                "is scheduled; close the loop with the vendor or contractor."
            ),
            "deadline": (
                "Counterparty is waiting on confirmation — respond within about one business day if possible."
            ),
            "scheduling_need": (
                "Optional: short internal ping to accounting if you need someone to verify receipt."
            ),
            "suggested_reply": (
                "Hi — thanks for the reminder. I'm checking with accounting on invoice processing "
                "status today and will confirm back once I have a definitive answer."
            ),
            "reason": (
                "Explicit payment/invoice status request — Follow-up with Medium priority."
            ),
        }

    # --- Colleague chasing deliverables → Follow-up ---
    if ("still waiting" in combined or "bumping this" in combined) and "invoice" not in combined:
        return {
            "category": "Follow-up",
            "priority": "High",
            "task_summary": (
                "Send the blocked artifact (e.g., cleaned export / CSV) or explain the ETA so "
                "downstream stakeholders can unblock their review."
            ),
            "deadline": (
                "Peer indicates dependency for an imminent review — prioritize delivery today if feasible."
            ),
            "scheduling_need": (
                "None unless you need a quick pairing session to extract the requested data."
            ),
            "suggested_reply": (
                "Thanks for the bump — you're right, I owe you that export. "
                "I'll send v2 of the cleaned CSV by end of day today and flag you immediately if I hit access issues."
            ),
            "reason": (
                "Thread bump requesting a concrete deliverable blocking another teammate — Follow-up "
                "with elevated priority."
            ),
        }

    # --- Coursework / professor deadlines → Action Needed ---
    if (
        ("problem set" in combined or "gradescope" in combined or "@cs." in sender.lower())
        and "due" in combined
    ) or ("office hours" in combined and "problem set" in combined):
        return {
            "category": "Action Needed",
            "priority": "High",
            "task_summary": (
                "Finish and submit the referenced assignment on Gradescope before the stated cutoff; "
                "email early if you need an extension with a concrete plan."
            ),
            "deadline": (
                "Sunday 11:59pm ET submission deadline per instructor reminder "
                "(extensions require proactive outreach before cutoff)."
            ),
            "scheduling_need": (
                "Optional: attend listed office hours if you're blocked on assignment questions."
            ),
            "suggested_reply": (
                "Hi Professor Kim — thanks for the reminder. I'll aim to submit PS3 before Sunday "
                "11:59pm ET. I'll reach out earlier if I need an extension with a concrete plan."
            ),
            "reason": (
                "Concrete academic deadline plus submission channel — Action Needed with High priority."
            ),
        }

    # --- Follow-up phrasing (checking in, reminders that are not calendar invites) ---
    if _rb_followup_language(combined, scheduling_like):
        return {
            "category": "Follow-up",
            "priority": "Medium",
            "task_summary": (
                "Provide a concise status update or ETA so the sender knows where things stand."
            ),
            "deadline": (
                "Reply within a reasonable window (often same day) to keep trust on the thread."
            ),
            "scheduling_need": "None unless they explicitly asked to book time.",
            "suggested_reply": (
                "Thanks for checking in — quick update: [add status]. "
                "I'll follow up again by [date] or sooner if anything changes."
            ),
            "reason": (
                "Language signals a gentle chase or reminder outside automated calendar invites."
            ),
        }

    # --- Promotional / marketing / newsletters → FYI ---
    if _rb_promotional_fyi(combined, sender):
        return {
            "category": "FYI",
            "priority": "Low",
            "task_summary": (
                "Bulk or promotional message (deals, newsletters, digests) — typically no response required."
            ),
            "deadline": "None.",
            "scheduling_need": "None.",
            "suggested_reply": "No reply needed.",
            "reason": (
                "Matched promotional/newsletter/subscription cues before deadline heuristics "
                "to avoid mis-triaging marketing as Action Needed."
            ),
        }

    # --- Time-sensitive deadlines → Urgent ---
    if _rb_urgent_timeline(combined, subject_l, promo_today_flag):
        return {
            "category": "Urgent",
            "priority": "High",
            "task_summary": (
                "Time-critical thread — execute or respond before the cutoff implied by the message."
            ),
            "deadline": "See email for cutoff language (today/tonight/EOD/deadline/ASAP).",
            "scheduling_need": "Protect calendar focus time if you must deliver the same day.",
            "suggested_reply": (
                "Acknowledged — I'm on this and will prioritize meeting your timeline. "
                "I'll follow up immediately if I'm blocked or need a quick clarification."
            ),
            "reason": (
                "Detected urgent / ASAP / deadline / same-day cues after excluding promo-only spam."
            ),
        }

    # --- Explicit FYI phrasing in body/sender ---
    if (
        "no action required" in combined
        or "no reply needed" in combined
        or "quick fyi" in combined
        or "newsletter" in sender.lower()
        or "newsletter@" in sender.lower()
        or "digest@" in sender.lower()
        or ("unsubscribe" in combined and ("digest" in combined or "issue" in combined or "reading" in combined))
    ):
        return {
            "category": "FYI",
            "priority": "Low",
            "task_summary": (
                "Informational content flagged by the sender — skim or archive unless an ask appears later."
            ),
            "deadline": "None.",
            "scheduling_need": "None.",
            "suggested_reply": "No reply needed.",
            "reason": (
                "Explicit FYI / newsletter framing with no response expectation."
            ),
        }

    # --- Messy deck/budget pattern (extra samples) → Action Needed ---
    if (
        "eod" in combined
        or "q4 deck" in combined
        or ("deck" in combined and "slides" in combined)
        or ("budget" in combined and "spreadsheet" in combined)
        or "leadership sync" in combined
        or "need numbers consolidated" in combined
        or "lmk if ur blocked" in combined
    ):
        return {
            "category": "Action Needed",
            "priority": "High",
            "task_summary": (
                "Ship time-sensitive deck or spreadsheet deliverables noted in the thread and "
                "coordinate dependencies before leadership syncs."
            ),
            "deadline": (
                "Use the closest deadline named in the email (e.g., EOD Friday or Tuesday sync prep)."
            ),
            "scheduling_need": (
                "Block focus time ahead of cited deadlines; schedule prep only if implied."
            ),
            "suggested_reply": (
                "Thanks — I'm aligned on the deadlines you mentioned. I'll consolidate numbers "
                "and circulate draft slides ahead of the sync; I'll ping if I'm blocked."
            ),
            "reason": (
                "Multiple concrete deliverables tied to executive timelines — Action Needed with High priority."
            ),
        }

    # --- Default: avoid vague “review everything” copy; bias automated senders to FYI ---
    snippet = body_one_line[:160] + ("…" if len(body_one_line) > 160 else "")
    subj_short = subject.strip()[:72] + ("…" if len(subject.strip()) > 72 else "")
    sl = sender.lower()
    if "noreply" in sl or "no-reply" in sl or "donotreply" in sl:
        return {
            "category": "FYI",
            "priority": "Low",
            "task_summary": (
                f"Automated message “{subj_short}” — skim for links or receipts; usually no reply."
            ),
            "deadline": "None identified.",
            "scheduling_need": "None unless the body proposes a meeting.",
            "suggested_reply": "No reply needed.",
            "reason": (
                "Automated sender pattern with no stronger template — FYI/Low to reduce inbox noise."
            ),
        }
    return {
        "category": "Action Needed",
        "priority": "Medium",
        "task_summary": (
            f"Thread “{subj_short}” may contain an ask or date — scan preview: {snippet}"
        ),
        "deadline": "Infer from the body or propose a reply-by when you respond.",
        "scheduling_need": "Add a calendar hold only if you confirm a meeting or hard milestone.",
        "suggested_reply": (
            "Thanks for the note — I've read it and will come back with an update or question shortly."
        ),
        "reason": (
            "No template matched; keeping Medium Action Needed for plausible human threads."
        ),
    }


def _canonical_category(value: Any) -> Optional[str]:
    """Map model output to an allowed category; None if unknown."""
    if value is None:
        return None
    cat = str(value).strip()
    if cat == "Deadline":
        return "Action Needed"
    if cat in VALID_CATEGORIES:
        return cat
    lowered = cat.lower().replace("_", " ")
    aliases = {
        "follow up": "Follow-up",
        "followup": "Follow-up",
        "action needed": "Action Needed",
        "actionneeded": "Action Needed",
        "schedule": "Schedule",
        "scheduling": "Schedule",
        "fyi": "FYI",
        "for your information": "FYI",
        "urgent": "Urgent",
    }
    return aliases.get(lowered)


def _canonical_priority(value: Any) -> str:
    """Map model output to High / Medium / Low."""
    if value is None:
        return "Medium"
    p = str(value).strip().lower()
    if p in ("high", "h"):
        return "High"
    if p in ("medium", "med", "m"):
        return "Medium"
    if p in ("low", "l"):
        return "Low"
    return "Medium"


def normalize_analysis(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce API JSON to the exact schema; fix enums; map legacy labels."""
    merged: dict[str, Any] = {}
    for key in ANALYSIS_KEYS:
        val = raw.get(key)
        merged[key] = str(val).strip() if val is not None else ""

    cat = _canonical_category(raw.get("category"))
    if cat is None:
        cat = "FYI"
    merged["category"] = cat

    merged["priority"] = _canonical_priority(raw.get("priority"))

    return merged


def _merge_weak_fields(
    analysis: dict[str, Any], sender: str, subject: str, body: str
) -> dict[str, Any]:
    """Fill empty text fields from rule-based output so the dashboard stays substantive."""
    rb = rule_based_analysis(sender, subject, body)
    out = dict(analysis)
    for key in ("task_summary", "deadline", "scheduling_need", "suggested_reply", "reason"):
        if not out.get(key) or len(out[key].strip()) < 8:
            out[key] = rb[key]
    return out


def analyze_email(sender: str, subject: str, body: str) -> dict[str, Any]:
    """
    Send sender, subject, and body to OpenAI; return structured JSON fields.
    Uses gpt-4o-mini with JSON-only response_format. On any failure, uses rule_based_analysis().
    """
    rb_first = rule_based_analysis(sender, subject, body)
    client = get_openai_client()
    if client is None:
        return rb_first

    # Strict JSON-only instructions; response_format enforces a JSON object from the model.
    system_prompt = """You are InboxIQ. Output must be ONE JSON object only (no markdown, no prose).

Use exactly these keys and string values:
{
  "category": "Action Needed",
  "priority": "High",
  "task_summary": "string",
  "deadline": "string",
  "scheduling_need": "string",
  "suggested_reply": "string",
  "reason": "string"
}

Rules:
- category must be exactly one of: Action Needed, Schedule, Follow-up, FYI, Urgent
- priority must be exactly one of: High, Medium, Low
- Strings must be concrete and grounded in the email (sender, subject, body).
- If no date exists, set deadline to something like "None" or "Not specified" explicitly."""

    user_content = json.dumps(
        {"sender": sender, "subject": subject, "body": body},
        ensure_ascii=False,
    )

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw_text = completion.choices[0].message.content or ""
        blob = _extract_json_object(raw_text) or raw_text
        parsed = json.loads(blob)
        if not isinstance(parsed, dict):
            raise ValueError("Expected JSON object")
        # Unknown category → discard model output so stats and copy stay aligned with rules.
        if _canonical_category(parsed.get("category")) is None:
            return rb_first
        normalized = normalize_analysis(parsed)
        return _merge_weak_fields(normalized, sender, subject, body)
    except (json.JSONDecodeError, ValueError, KeyError, TypeError):
        return rb_first
    except APIError:
        return rb_first
    except Exception:
        return rb_first


def analyze_all() -> list[dict[str, Any]]:
    """Demo dataset: analyze SAMPLE_EMAILS using the same pipeline as live Gmail."""
    return analyze_email_records(SAMPLE_EMAILS)


@app.route("/")
def index():
    """Demo dashboard with curated sample emails analyzed server-side (no Live Gmail on this route)."""
    emails = analyze_all()
    stats_seed = compute_stats_from_emails(emails)
    return render_template(
        "index.html",
        emails=emails,
        stats_seed=stats_seed,
        inbox_mode="demo",
        live_show_setup=False,
        live_setup_variant=None,
        live_fetch_error=None,
        json_route="api_analyze",
        splash_test_access_gmail_url=SPLASH_TEST_ACCESS_GMAIL_COMPOSE_URL,
    )


@app.route("/connect-gmail")
def connect_gmail():
    """
    Kick off OAuth (installed-app flow). Requires credentials.json from Google Cloud.
    Saves authorized credentials to token.json, then sends the user to /live-inbox.
    """
    if not os.path.isfile(CREDENTIALS_PATH):
        # Missing client secrets — send recruiters to Live inbox UI with clear setup instructions.
        return redirect(url_for("live_inbox", gmail_error="missing_credentials"))

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
    # Opens a local browser window to complete consent; blocks until finished.
    creds = flow.run_local_server(port=0)
    with open(TOKEN_PATH, "w", encoding="utf-8") as token_file:
        token_file.write(creds.to_json())
    return redirect(url_for("live_inbox"))


@app.route("/live-inbox")
def live_inbox():
    """
    Live mode: fetch recent Gmail, analyze server-side, and render cards (same pipeline as demo).
    """
    gmail_error = request.args.get("gmail_error")
    credentials_ok = os.path.isfile(CREDENTIALS_PATH)
    service = get_gmail_service()

    if service is None:
        variant = None
        if gmail_error == "missing_credentials" or not credentials_ok:
            variant = "missing_credentials"
        else:
            variant = "needs_oauth"
        return render_template(
            "index.html",
            emails=[],
            stats_seed=None,
            inbox_mode="live",
            live_show_setup=True,
            live_setup_variant=variant,
            live_fetch_error=None,
            json_route="api_live_analyze",
        )

    raw = fetch_recent_gmail_messages(10)
    if not raw:
        empty_stats = compute_stats_from_emails([])
        return render_template(
            "index.html",
            emails=[],
            stats_seed=empty_stats,
            inbox_mode="live",
            live_show_setup=False,
            live_setup_variant=None,
            live_fetch_error=(
                "Connected to Gmail, but no messages were returned (empty inbox or temporary API issue)."
            ),
            json_route="api_live_analyze",
        )

    emails = analyze_email_records(raw)
    stats_seed = compute_stats_from_emails(emails)
    return render_template(
        "index.html",
        emails=emails,
        stats_seed=stats_seed,
        inbox_mode="live",
        live_show_setup=False,
        live_setup_variant=None,
        live_fetch_error=None,
        json_route="api_live_analyze",
    )


@app.route("/api/analyze")
def api_analyze():
    """JSON API: analyzed sample emails (demo dataset)."""
    return jsonify({"emails": analyze_all()})


@app.route("/api/live-analyze")
def api_live_analyze():
    """JSON API: analyzed recent Gmail messages; errors when OAuth has not completed."""
    if get_gmail_service() is None:
        return jsonify(
            {
                "error": "Gmail not connected. Add credentials.json and visit /connect-gmail."
            }
        ), 400
    raw = fetch_recent_gmail_messages(10)
    emails = analyze_email_records(raw)
    payload: dict[str, Any] = {"emails": emails}
    if not emails:
        payload["info"] = (
            "Connected to Gmail, but no messages were returned (empty inbox or temporary API issue)."
        )
    return jsonify(payload)


if __name__ == "__main__":
    # Default Flask dev server — suitable for local MVP demos.
    app.run(debug=True, host="127.0.0.1", port=5000)
