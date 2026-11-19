"""Wait for the MongoDB replica-set primary, then create collections' indexes. Idempotent.
Run as: python -m scripts.initialize_database"""
import asyncio

from app import database


async def main() -> None:
    db = database.init_db()
    await database.wait_for_primary()
    await database.ensure_indexes(db)
    print("database ready: replica-set primary reachable, indexes ensured")
    await database.close_db()


if __name__ == "__main__":
    asyncio.run(main())
