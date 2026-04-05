from __future__ import annotations

import json
import os
import time
from dotenv import load_dotenv
import anthropic

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"  # Fast + cheap for classification; override per-call for reports
_client = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _call_with_retry(prompt: str, max_tokens: int = 512, retries: int = 3, model: str = None) -> str:
    """Call Claude with exponential backoff on rate limit or server errors."""
    for attempt in range(retries):
        try:
            response = get_client().messages.create(
                model=model or MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except anthropic.RateLimitError:
            wait = 2 ** attempt * 5
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if e.status_code >= 500 and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
            else:
                raise
    raise RuntimeError(f"Claude API call failed after {retries} retries")


def _load_classifier_context() -> str:
    """Load prior knowledge context written by the monthly retrainer, if it exists."""
    context_path = "learning/db/classifier_context.txt"
    if os.path.exists(context_path):
        with open(context_path) as f:
            return f.read().strip()
    return ""


def classify_email(
    subject: str,
    sender: str,
    snippet: str,
    available_labels: list[str],
) -> dict:
    """
    Classify a single email. Returns:
    {"label": str, "confidence": float, "reasoning": str, "is_new_cluster": bool, "new_cluster_name": str}
    """
    context = _load_classifier_context()
    context_block = f"\nPrior knowledge about this inbox:\n{context}\n" if context else ""

    labels_json = json.dumps(available_labels)
    prompt = f"""You are classifying an email for inbox organization.
{context_block}
Available categories: {labels_json}

Email:
  Subject: {subject}
  From: {sender}
  Preview: {snippet}

Respond ONLY in valid JSON with no extra text:
{{"label": "<one of the available categories or NEW_CLUSTER>", "confidence": 0.0, "reasoning": "<one sentence>", "is_new_cluster": false, "new_cluster_name": "<only if label is NEW_CLUSTER, else empty string>"}}"""

    raw = _call_with_retry(prompt, max_tokens=200)
    try:
        result = json.loads(raw.strip())
        result.setdefault("is_new_cluster", result.get("label") == "NEW_CLUSTER")
        result.setdefault("new_cluster_name", "")
        return result
    except json.JSONDecodeError:
        return {
            "label": available_labels[0] if available_labels else "Uncategorized",
            "confidence": 0.0,
            "reasoning": "JSON parse failed",
            "is_new_cluster": False,
            "new_cluster_name": "",
        }


def classify_email_batch(
    emails: list[dict],
    available_labels: list[str],
) -> list[dict]:
    """
    Classify up to 10 emails in a single Claude call.
    Each dict must have keys: id, subject, sender, snippet.
    Returns list of classification dicts with email id added.
    """
    context = _load_classifier_context()
    context_block = f"\nPrior knowledge about this inbox:\n{context}\n" if context else ""
    labels_json = json.dumps(available_labels)

    emails_block = "\n".join(
        f'{i+1}. id={e["id"]} | Subject: {e["subject"]} | From: {e["sender"]} | Preview: {e["snippet"][:120]}'
        for i, e in enumerate(emails)
    )

    prompt = f"""You are classifying emails for inbox organization.
{context_block}
Available categories: {labels_json}

Emails to classify:
{emails_block}

Respond ONLY with a valid JSON array — one object per email, in the same order:
[{{"id": "<email_id>", "label": "<category or NEW_CLUSTER>", "confidence": 0.0, "reasoning": "<one sentence>", "is_new_cluster": false, "new_cluster_name": ""}}]"""

    raw = _call_with_retry(prompt, max_tokens=800)
    try:
        results = json.loads(raw.strip())
        if isinstance(results, list) and len(results) == len(emails):
            return results
    except json.JSONDecodeError:
        pass

    # Fallback: classify individually
    return [classify_email(e["subject"], e["sender"], e["snippet"], available_labels) | {"id": e["id"]}
            for e in emails]


def generate_text(prompt: str, max_tokens: int = 1024) -> str:
    """General-purpose text generation for reports and digests. Uses Sonnet for quality."""
    return _call_with_retry(prompt, max_tokens=max_tokens, model="claude-sonnet-4-6")


def extract_ai_tools(text_batch: str) -> list[dict]:
    """
    Given a batch of AI/Tech email subjects and snippets, extract structured tool info.
    Returns: [{"tool_name": str, "category": str, "description": str, "claude_rating": str}]
    """
    prompt = f"""You are analyzing emails to identify AI tools, models, frameworks, and products mentioned.

Email content batch:
{text_batch[:6000]}

Extract every distinct AI tool, model, or product mentioned. For each one return:
- tool_name: the product/tool name
- category: one of [LLM, Agent Framework, Dev Tool, Research, Platform, Other]
- description: one sentence about what it does
- claude_rating: one of [Worth Exploring, Monitor, Low Priority]

Respond ONLY with a valid JSON array:
[{{"tool_name": "", "category": "", "description": "", "claude_rating": ""}}]"""

    raw = _call_with_retry(prompt, max_tokens=1500)
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return []


def extract_purchase_data(
    subject: str,
    sender: str,
    snippet: str,
    email_id: str = "",
) -> dict | None:
    """
    Parse a purchase/billing email and return structured financial data.
    Returns None if no financial event is detected.

    Return shape:
    {
      "type": "purchase" | "renewal" | "expiry_reminder" | "trial_ending",
      "merchant": str,
      "amount": float | null,
      "currency": str,
      "date": "YYYY-MM-DD",
      "renewal_date": "YYYY-MM-DD | null",
      "expiry_date": "YYYY-MM-DD | null",
      "billing_cycle": "monthly" | "annual" | "one-time" | null,
      "description": str
    }
    """
    today = __import__("datetime").date.today().isoformat()
    prompt = f"""You extract financial data from email notifications. Today is {today}.

Email:
  Subject: {subject}
  From: {sender}
  Preview: {snippet[:300]}

If this email contains a purchase, charge, renewal, subscription, or expiry event, return a JSON object.
If it does NOT contain any financial event (e.g. it's a newsletter, marketing email, or unrelated), return the JSON: {{"type": "none"}}

For financial emails, return ONLY valid JSON:
{{"type": "purchase|renewal|expiry_reminder|trial_ending", "merchant": "string", "amount": 0.00, "currency": "USD", "date": "YYYY-MM-DD", "renewal_date": "YYYY-MM-DD or null", "expiry_date": "YYYY-MM-DD or null", "billing_cycle": "monthly|annual|one-time|null", "description": "one line description"}}

Rules:
- amount must be a number (not a string), null if unknown
- date is the transaction/event date; use today ({today}) if not stated
- currency: infer from symbols ($ = USD, ₹ = INR, € = EUR) or default to USD
- billing_cycle: null for one-off purchases"""

    raw = _call_with_retry(prompt, max_tokens=250)
    try:
        result = json.loads(raw.strip())
        if result.get("type") == "none":
            return None
        return result
    except (json.JSONDecodeError, KeyError):
        return None


def suggest_reply_draft(subject: str, sender: str, body: str) -> str:
    """
    Generate a 2-sentence reply opener for a personal must-read email.
    Returns plain text (no JSON).
    """
    prompt = f"""Write a brief, natural reply opener (2 sentences max) for this email.
Match the tone of the original email. Do not include a greeting or sign-off.

Subject: {subject}
From: {sender}
Body excerpt: {body[:500]}

Reply opener:"""

    return _call_with_retry(prompt, max_tokens=100).strip()
