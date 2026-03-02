"""Delete orphaned storage files not referenced by any document record.

Called by ARQ cron at 02:00 UTC, or manually via:
    python -m scripts.cleanup_storage
    python -m scripts.cleanup_storage --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select

logger = logging.getLogger(__name__)


async def run_cleanup(dry_run: bool = False) -> dict[str, int]:
    """Scan storage and delete files not referenced by any document.

    Returns dict with counts: checked, referenced, orphaned, deleted.
    """
    from app.dependencies import get_storage
    from app.models.database import AsyncSessionLocal
    from app.models.document import Document

    storage = await get_storage()

    # Get all stored paths from the database
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document.stored_path))
        referenced_paths = {row[0] for row in result.all()}

    # List all keys in storage
    all_keys = await storage.list_keys()

    orphaned = [k for k in all_keys if k not in referenced_paths]

    deleted = 0
    for key in orphaned:
        if dry_run:
            logger.info("[DRY RUN] Would delete: %s", key)
        else:
            try:
                success = await storage.delete(key)
                if success:
                    deleted += 1
                    logger.info("Deleted orphaned file: %s", key)
            except Exception as e:
                logger.error("Failed to delete %s: %s", key, e)

    summary = {
        "checked": len(all_keys),
        "referenced": len(referenced_paths),
        "orphaned": len(orphaned),
        "deleted": deleted,
    }
    logger.info("Cleanup summary: %s", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean up orphaned storage files")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List orphaned files without deleting",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    result = asyncio.run(run_cleanup(dry_run=args.dry_run))
    print(f"Checked:    {result['checked']}")
    print(f"Referenced: {result['referenced']}")
    print(f"Orphaned:   {result['orphaned']}")
    print(f"Deleted:    {result['deleted']}")


if __name__ == "__main__":
    main()
