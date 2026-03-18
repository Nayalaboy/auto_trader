"""
auth.py — Schwab OAuth2 Authentication Handler
-----------------------------------------------
Manages token creation, storage, and auto-refresh via schwab-py.
Run this file directly to complete the initial OAuth flow.

Usage:
    python auth.py          # First-time login (opens browser)
    from auth import get_client  # Import in other modules
"""

import os
import pathlib
import schwab
from dotenv import load_dotenv

load_dotenv()

APP_KEY        = os.getenv("SCHWAB_APP_KEY")
APP_SECRET     = os.getenv("SCHWAB_APP_SECRET")
CALLBACK_URL   = os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")
TOKEN_PATH     = os.getenv("SCHWAB_TOKEN_PATH", "./tokens/schwab_token.json")


def get_client() -> schwab.client.Client:
    """
    Returns an authenticated Schwab client.

    - If a valid token file exists, loads and auto-refreshes it.
    - If no token file exists, launches the OAuth browser flow to
      generate one (first-time setup only).
    """
    token_file = pathlib.Path(TOKEN_PATH)
    token_file.parent.mkdir(parents=True, exist_ok=True)

    if token_file.exists():
        # Token exists — load and auto-refresh as needed
        client = schwab.auth.client_from_token_file(
            token_path=str(token_file),
            api_key=APP_KEY,
            app_secret=APP_SECRET,
        )
        print("✅ Loaded existing token from", TOKEN_PATH)
    else:
        # First-time setup: opens browser for Schwab login
        # After login, Schwab redirects to your callback URL.
        # schwab-py intercepts it automatically at the local port.
        print("🔐 No token found. Starting OAuth browser flow...")
        print(f"   Callback URL: {CALLBACK_URL}")
        print("   Log in with your SCHWAB BROKERAGE credentials (not dev portal).\n")

        client = schwab.auth.client_from_login_flow(
            api_key=APP_KEY,
            app_secret=APP_SECRET,
            callback_url=CALLBACK_URL,
            token_path=str(token_file),
        )
        print("✅ Authentication successful. Token saved to", TOKEN_PATH)

    return client


if __name__ == "__main__":
    # Run this file directly to test your auth setup
    client = get_client()

    print("\n--- Verifying connection: fetching account list ---")
    resp = client.get_account_numbers()

    if resp.status_code == 200:
        accounts = resp.json()
        print(f"✅ Connected! Found {len(accounts)} linked account(s).")
        for acct in accounts:
            # accountNumber is masked by default; hashValue is used for API calls
            print(f"   Account hash: {acct['hashValue']}")
    else:
        print(f"❌ Failed to fetch accounts: {resp.status_code} — {resp.text}")
