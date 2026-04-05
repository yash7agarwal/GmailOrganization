import os
import base64
from email import message_from_bytes
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]

_service = None


def get_client():
    global _service
    if _service:
        return _service

    creds = Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    creds.refresh(Request())
    _service = build("gmail", "v1", credentials=creds)
    return _service


def search_messages(query, max_results=100):
    """Search Gmail and return a list of message dicts with id and threadId."""
    service = get_client()
    results = []
    page_token = None

    while len(results) < max_results:
        batch = max_results - len(results)
        resp = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=min(batch, 500),
            pageToken=page_token,
        ).execute()

        results.extend(resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return results[:max_results]


def get_message(message_id, fmt="metadata"):
    """
    Fetch a single message.
    fmt: 'metadata' for headers only, 'full' for full payload.
    Returns a dict with keys: id, subject, sender, snippet, body (if full).
    """
    service = get_client()
    msg = service.users().messages().get(
        userId="me",
        id=message_id,
        format=fmt,
        metadataHeaders=["Subject", "From", "Date"],
    ).execute()

    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    result = {
        "id": msg["id"],
        "thread_id": msg.get("threadId"),
        "subject": headers.get("Subject", ""),
        "sender": headers.get("From", ""),
        "date": headers.get("Date", ""),
        "snippet": msg.get("snippet", ""),
        "label_ids": msg.get("labelIds", []),
    }

    if fmt == "full":
        result["body"] = _extract_body(msg.get("payload", {}))

    return result


def _extract_body(payload):
    """Recursively extract plain text body from a message payload."""
    mime_type = payload.get("mimeType", "")
    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = _extract_body(part)
        if result:
            return result
    return ""


def list_labels():
    """Return all Gmail labels as a dict: {name: id}."""
    service = get_client()
    resp = service.users().labels().list(userId="me").execute()
    return {label["name"]: label["id"] for label in resp.get("labels", [])}


def get_or_create_label(name):
    """Return label id for name, creating it if it doesn't exist."""
    labels = list_labels()
    if name in labels:
        return labels[name]
    return create_label(name)


def create_label(name):
    """Create a new Gmail label and return its id."""
    service = get_client()
    body = {
        "name": name,
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
    }
    label = service.users().labels().create(userId="me", body=body).execute()
    return label["id"]


def apply_label(message_id, label_id):
    """Apply a label to a message."""
    service = get_client()
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"addLabelIds": [label_id]},
    ).execute()


def remove_label(message_id, label_id):
    """Remove a label from a message."""
    service = get_client()
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"removeLabelIds": [label_id]},
    ).execute()


def archive_message(message_id):
    """Archive a message by removing INBOX label."""
    remove_label(message_id, "INBOX")
