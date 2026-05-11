#!/usr/bin/env python3
"""
Initialize the Karma database.
Creates all tables and MinIO buckets.

Usage:
    python scripts/init_db.py
    python scripts/init_db.py --drop   # drop and recreate (dev only)
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def init(drop: bool = False) -> None:
    from db.session import engine, init_db, drop_db
    from config.settings import settings

    print(f"[db] Connecting to: {settings.database_url.split('@')[-1]}")

    if drop:
        print("[db] Dropping all tables...")
        await drop_db()
        print("[db] Dropped.")

    print("[db] Creating tables...")
    await init_db()
    print("[db] Tables created.")

    await engine.dispose()


def init_minio() -> None:
    from config.settings import settings
    try:
        from minio import Minio
        client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        for bucket in [settings.minio_bucket_evidence, settings.minio_bucket_receipts]:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
                print(f"[minio] Created bucket: {bucket}")
            else:
                print(f"[minio] Bucket exists: {bucket}")
    except Exception as e:
        print(f"[minio] Warning: {e} (MinIO may not be running)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize Karma database")
    parser.add_argument("--drop", action="store_true", help="Drop and recreate all tables")
    parser.add_argument("--no-minio", action="store_true", help="Skip MinIO bucket creation")
    args = parser.parse_args()

    if args.drop:
        confirm = input("Drop ALL tables? This is destructive. Type 'yes' to confirm: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(0)

    asyncio.run(init(drop=args.drop))

    if not args.no_minio:
        init_minio()

    print("[done] Database ready.")


if __name__ == "__main__":
    main()
