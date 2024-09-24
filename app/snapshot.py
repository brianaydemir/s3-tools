"""
Take a snapshot of a user's buckets.
"""

import datetime
import json
import logging
import os
import pathlib
import sys
from typing import Any

import minio
import radosgw  # type: ignore[import-untyped]

SNAPSHOT_DIR = pathlib.Path(os.environ.get("SNAPSHOT_DIR", "/snapshots"))
S3_HOST = os.environ.get("S3_HOST", "S3_HOST not defined")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "S3_ACCESS_KEY not defined")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "S3_SECRET_KEY not defined")
USE_RGW_ADMIN_OPS = os.environ.get("USE_RGW_ADMIN_OPS", "no")

Snapshot = dict[str, dict[str, Any]]


def get_current_time() -> str:
    """
    Returns the current UTC time in ISO 8601 format.
    """
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def get_client(
    access_key: str = S3_ACCESS_KEY,
    secret_key: str = S3_SECRET_KEY,
) -> minio.Minio:
    """
    Returns a client object for interacting with S3.
    """
    return minio.Minio(
        S3_HOST,
        access_key=access_key,
        secret_key=secret_key,
    )


def get_admin_client(
    access_key: str = S3_ACCESS_KEY,
    secret_key: str = S3_SECRET_KEY,
) -> radosgw.connection.RadosGWAdminConnection:
    """
    Returns a client object for a Ceph Object Gateway.
    """
    return radosgw.connection.RadosGWAdminConnection(
        host=S3_HOST,
        access_key=access_key,
        secret_key=secret_key,
    )


def get_buckets() -> list[tuple[str, str, str]]:
    """
    Returns a list of (bucket name, access key, secret key) tuples.
    """
    buckets = []

    if USE_RGW_ADMIN_OPS != "yes":
        s3 = get_client(access_key=S3_ACCESS_KEY, secret_key=S3_SECRET_KEY)

        for bucket in s3.list_buckets():
            access_key = S3_ACCESS_KEY
            secret_key = S3_SECRET_KEY
            buckets.append((bucket.name, access_key, secret_key))

    else:
        rgw = get_admin_client(access_key=S3_ACCESS_KEY, secret_key=S3_SECRET_KEY)

        for bucket in rgw.get_buckets():
            user = rgw.get_user(bucket.owner)
            access_key = user.keys[0].access_key
            secret_key = user.keys[0].secret_key
            buckets.append((bucket.name, access_key, secret_key))

    return buckets


def scan_bucket(name: str, access_key: str, secret_key: str) -> tuple[int, int]:
    """
    Returns the total number of files and bytes in the given S3 bucket.
    """
    logging.info("Scanning bucket: %s", name)

    s3 = get_client(access_key=access_key, secret_key=secret_key)

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
    snapshot_file = SNAPSHOT_DIR / f'{data["metadata"]["start"]}.json'

    for name, access_key, secret_key in get_buckets():
        num_files, num_bytes = scan_bucket(name, access_key, secret_key)
        data["buckets"][name] = {"files": num_files, "bytes": num_bytes}
    data["metadata"]["end"] = get_current_time()

    with open(snapshot_file, mode="w", encoding="utf-8") as fp:
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
