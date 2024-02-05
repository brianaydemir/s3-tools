"""
Take a snapshot of a user's buckets.
"""

import datetime
import json
import logging
import os
import pathlib
import sys
from typing import Any, Dict, Tuple

import minio

SNAPSHOT_DIR = pathlib.Path(os.environ.get("SNAPSHOT_DIR", "/snapshots"))
S3_HOST = os.environ.get("S3_HOST", "S3_HOST not defined")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "S3_ACCESS_KEY not defined")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "S3_SECRET_KEY not defined")

Snapshot = Dict[str, Dict[str, Any]]


def get_current_time() -> str:
    """
    Returns the current UTC time in ISO 8601 format.
    """
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def get_client() -> minio.Minio:
    """
    Returns a client object for interacting with S3.
    """
    return minio.Minio(S3_HOST, access_key=S3_ACCESS_KEY, secret_key=S3_SECRET_KEY)


def scan_bucket(s3: minio.Minio, name: str) -> Tuple[int, int]:
    """
    Returns the total number of files and bytes in the given S3 bucket.
    """
    logging.info("Scanning bucket: %s", name)

    num_files = 0
    num_bytes = 0

    for obj in s3.list_objects(name, recursive=True):
        if not obj.is_dir:
            num_files += 1
            num_bytes += obj.size

    return (num_files, num_bytes)


def main() -> None:
    logging.info("Starting")

    data: Snapshot = {
        "buckets": {},
        "metadata": {"version": "1", "start": get_current_time()},
    }
    s3 = get_client()
    snapshot_file = SNAPSHOT_DIR / f'{data["metadata"]["start"]}.json'

    for bucket in s3.list_buckets():
        name = bucket.name
        (num_files, num_bytes) = scan_bucket(s3, name)
        data["buckets"][name] = {"files": num_files, "bytes": num_bytes}
    data["metadata"]["end"] = get_current_time()

    with open(snapshot_file, encoding="utf-8", mode="w") as fp:
        json.dump(data, fp, indent=2)
    logging.info("Finished!")


def entrypoint() -> None:
    try:
        logging.basicConfig(
            format="%(asctime)s ~ %(message)s",
            level=logging.DEBUG,
        )
        main()
    except Exception:  # pylint: disable=broad-except
        logging.exception("Uncaught exception")
        sys.exit(1)


if __name__ == "__main__":
    entrypoint()
