"""
One-time OAuth setup script.
Run this once to get your GMAIL_REFRESH_TOKEN, then store it in .env.

Usage:
    python scripts/setup_oauth.py

Requirements:
    - GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET must be set in .env
    - A browser will open for Google sign-in
"""

import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]


def main():
    client_id = os.environ.get("GMAIL_CLIENT_ID")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("ERROR: Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in your .env file first.")
        return

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n--- OAuth successful ---")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print("\nAdd the above line to your .env file.")


if __name__ == "__main__":
    main()
