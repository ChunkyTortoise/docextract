"""Seed a development API key into the database.

Usage:
    python -m scripts.seed_api_key
    python -m scripts.seed_api_key --name "my-dev-key" --rate-limit 120
"""
from __future__ import annotations

import argparse
import asyncio
import secrets
import uuid

from app.models.database import AsyncSessionLocal
from app.utils.hashing import hash_api_key


async def seed_api_key(name: str, rate_limit: int) -> None:
    """Generate a random API key, hash it, and insert into the DB."""
    from app.models.api_key import APIKey

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

    asyncio.run(seed_api_key(args.name, args.rate_limit))


if __name__ == "__main__":
    main()
