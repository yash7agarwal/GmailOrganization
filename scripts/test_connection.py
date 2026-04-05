"""
Quick smoke test for the Gmail connection.
Run after setting up .env to verify everything works.

Usage:
    python scripts/test_connection.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.gmail_client import get_client, list_labels, search_messages, get_message


def main():
    print("Connecting to Gmail...")
    get_client()
    print("Connected.\n")

    print("Fetching labels...")
    labels = list_labels()
    print(f"Found {len(labels)} labels:")
    for name in sorted(labels.keys()):
        print(f"  - {name}")

    print("\nFetching 3 recent emails...")
    messages = search_messages("in:inbox", max_results=3)
    for m in messages:
        email = get_message(m["id"])
        print(f"\n  Subject : {email['subject']}")
        print(f"  From    : {email['sender']}")
        print(f"  Snippet : {email['snippet'][:80]}...")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
