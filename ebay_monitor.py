#!/usr/bin/env python3
"""
eBay listing monitor -> ntfy alert.

Searches eBay's Browse API for listings matching a keyword from a specific
seller, and sends a push notification via ntfy.sh the moment a NEW matching
listing is found. Keeps track of already-seen items in seen_items.json so
you don't get repeat alerts for the same listing.

Required environment variables (set as GitHub Actions secrets):
  EBAY_CLIENT_ID      - your eBay App ID (Client ID)
  EBAY_CLIENT_SECRET  - your eBay Cert ID (Client Secret)
  NTFY_TOPIC          - your unique ntfy.sh topic name

Configurable search terms below.
"""

import json
import os
import sys
from pathlib import Path

import requests

# ---- Configuration ----------------------------------------------------
SEARCH_KEYWORDS = "Pokémon Starter Pullover"
SELLER_USERNAME = "bullseyedeal"
MARKETPLACE_ID = "EBAY_US"
SEEN_ITEMS_FILE = Path(__file__).parent / "seen_items.json"
# ------------------------------------------------------------------------

EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"


def get_access_token(client_id: str, client_secret: str) -> str:
    """Client-credentials OAuth flow for public Browse API access."""
    resp = requests.post(
        EBAY_OAUTH_URL,
        auth=(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def search_listings(token: str) -> list[dict]:
    resp = requests.get(
        EBAY_SEARCH_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE_ID,
        },
        params={
            "q": SEARCH_KEYWORDS,
            "filter": f"sellers:{{{SELLER_USERNAME}}}",
            "limit": 50,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("itemSummaries", [])


def load_seen_ids() -> set[str]:
    if SEEN_ITEMS_FILE.exists():
        return set(json.loads(SEEN_ITEMS_FILE.read_text()))
    return set()


def save_seen_ids(ids: set[str]) -> None:
    SEEN_ITEMS_FILE.write_text(json.dumps(sorted(ids), indent=2))


def send_ntfy_alert(topic: str, item: dict) -> None:
    title = item.get("title", "Unknown item")
    price_obj = item.get("price", {})
    price = f"{price_obj.get('value', '?')} {price_obj.get('currency', '')}".strip()
    url = item.get("itemWebUrl", "")

    resp = requests.post(
        f"https://ntfy.sh/{topic}",
        data=title.encode("utf-8"),
        headers={
            "Title": "eBay listing found!".encode("utf-8"),
            "Priority": "urgent",
            "Tags": "rotating_light",
            "Click": url,
            "Actions": f"view, Open listing, {url}",
        },
    )
    # Also send price as a follow-up line for clarity
    requests.post(
        f"https://ntfy.sh/{topic}",
        data=f"Price: {price}\n{url}".encode("utf-8"),
        headers={"Title": title.encode("utf-8")},
    )
    resp.raise_for_status()


def main() -> None:
    client_id = os.environ.get("EBAY_CLIENT_ID")
    client_secret = os.environ.get("EBAY_CLIENT_SECRET")
    ntfy_topic = os.environ.get("NTFY_TOPIC")

    missing = [
        name
        for name, val in [
            ("EBAY_CLIENT_ID", client_id),
            ("EBAY_CLIENT_SECRET", client_secret),
            ("NTFY_TOPIC", ntfy_topic),
        ]
        if not val
    ]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    token = get_access_token(client_id, client_secret)
    listings = search_listings(token)
    print(f"Found {len(listings)} listing(s) matching search.")

    seen_ids = load_seen_ids()
    new_ids = set()

    for item in listings:
        item_id = item.get("itemId")
        if not item_id:
            continue
        if item_id not in seen_ids:
            print(f"NEW listing: {item.get('title')} ({item_id})")
            send_ntfy_alert(ntfy_topic, item)
            new_ids.add(item_id)
        else:
            print(f"Already seen: {item_id}")

    if new_ids:
        save_seen_ids(seen_ids | new_ids)
        print(f"Sent {len(new_ids)} new alert(s).")
    else:
        print("No new listings.")


if __name__ == "__main__":
    main()
