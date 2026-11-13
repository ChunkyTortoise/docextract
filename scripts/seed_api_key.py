"""Seed a development API key into the database.

Usage:
    python -m scripts.seed_api_key
    python -m scripts.seed_api_key --name "my-dev-key" --rate-limit 120

Remote seeding (e.g. a one-off ECS task, whose stdout lands in CloudWatch):
generate the key and its HMAC hash on your own machine, then pass only the
hash through SEED_KEY_HASH so the raw key never reaches the remote logs:
    SEED_KEY_HASH=<hex> python -m scripts.seed_api_key --name bench-key
"""
from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import uuid

from app.models.database import AsyncSessionLocal
from app.utils.hashing import hash_api_key


async def seed_api_key(name: str, rate_limit: int, key_hash: str | None = None) -> None:
    """Insert an API key into the DB.

    With ``key_hash`` the caller already holds the raw key; only the hash is
    stored and nothing secret is printed. Otherwise a new key is generated.
    """
    from app.models.api_key import APIKey

    raw_key = None
    if key_hash is None:
        raw_key = f"dex_dev_{secrets.token_hex(24)}"
        key_hash = hash_api_key(raw_key)
    key_id = uuid.uuid4()

    async with AsyncSessionLocal() as db:
        api_key = APIKey(
            id=key_id,
            name=name,
            key_hash=key_hash,
            is_active=True,
            rate_limit_per_minute=rate_limit,
        )
        db.add(api_key)
        await db.commit()

    if raw_key is None:
        print(f"API key hash inserted: id={key_id} name={name} rate_limit={rate_limit}/min")
        return

    print("=" * 60)
    print("  API Key Created Successfully")
    print("=" * 60)
    print(f"  ID:             {key_id}")
    print(f"  Name:           {name}")
    print(f"  Rate Limit:     {rate_limit}/min")
    print(f"  Raw Key:        {raw_key}")
    print("=" * 60)
    print("  SAVE THIS KEY — it will never be shown again.")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a development API key")
    parser.add_argument("--name", default="dev-key", help="Key name (default: dev-key)")
    parser.add_argument(
        "--rate-limit", type=int, default=60,
        help="Requests per minute (default: 60)",
    )
    args = parser.parse_args()

    key_hash = os.environ.get("SEED_KEY_HASH") or None
    asyncio.run(seed_api_key(args.name, args.rate_limit, key_hash))


if __name__ == "__main__":
    main()
