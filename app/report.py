"""
Compare two recent snapshots and send an email.
"""

import datetime
import email.mime.multipart
import email.mime.text
import json
import logging
import os
import os.path
import pathlib
import smtplib
import ssl
import sys
from typing import Any, Dict

import humanize

SMTP_HOST = os.environ.get("SMTP_HOST", "SMTP_HOST not defined")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "25"))
SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "yes")
TO = os.environ.get("TO", "TO not defined")
FROM = os.environ.get("FROM", "FROM not defined")
SUBJECT = os.environ.get("SUBJECT", "S3 storage report")
SNAPSHOT_DIR = pathlib.Path(os.environ.get("SNAPSHOT_DIR", "/snapshots"))

Snapshot = Dict[str, Dict[str, Any]]


def format_count(n: int, delta: bool = False) -> str:
    """
    Formats an integer with commas.
    """
    return ("+" if delta and n > 0 else "") + humanize.intcomma(n)


def format_bytes(n: int, delta: bool = False) -> str:
    """
    Formats an integer with a 2**10 suffix.
    """
    return humanize.naturalsize(
        n,
        binary=True,
        format="%+.1f" if delta else "%.1f",
    )


def load_snapshot(path: os.PathLike) -> Snapshot:
    """
    Returns a snapshot that was previously created by `app.snapshot`.
    """
    with open(path, encoding="utf-8", mode="r") as fp:
        return json.load(fp)  # type: ignore[no-any-return]


def compare_snapshots(current: Snapshot, previous: Snapshot) -> Snapshot:
    """
    Returns a new snapshot that is `current` and how it changed from `previous`.
    """
    data: Snapshot = {
        "buckets": {},
        "metadata": {
            "now": current["metadata"]["start"],
            "total_files": 0,
            "total_bytes": 0,
            "total_d_files": 0,
            "total_d_bytes": 0,
        },
    }

    now = current["metadata"]["start"]
    earlier = previous.get("metadata", {}).get("start", now)
    dt_now = datetime.datetime.fromisoformat(now)
    dt_earlier = datetime.datetime.fromisoformat(earlier)
    data["metadata"]["delta"] = dt_now - dt_earlier

    for name in set(current["buckets"]) | set(previous.get("buckets", {})):
        c_files = current.get("buckets", {}).get(name, {}).get("files", 0)
        c_bytes = current.get("buckets", {}).get(name, {}).get("bytes", 0)
        p_files = previous.get("buckets", {}).get(name, {}).get("files", 0)
        p_bytes = previous.get("buckets", {}).get(name, {}).get("bytes", 0)

        data["buckets"][name] = {
            "files": c_files,
            "bytes": c_bytes,
            "d_files": c_files - p_files,
            "d_bytes": c_bytes - p_bytes,
        }

        data["metadata"]["total_files"] += c_files
        data["metadata"]["total_bytes"] += c_bytes
        data["metadata"]["total_d_files"] += c_files - p_files
        data["metadata"]["total_d_bytes"] += c_bytes - p_bytes

    return data


def get_row_html(
    label: str, files: int, d_files: int, bytes: int, d_bytes: int, row_num: int
) -> str:
    html = ""
    numeric = "font-family: monospace; text-align: right;"
    padding = "padding-left: 0.5em; padding-right: 0.5em;"

    if (row_num % 2) == 0:
        html += "<tr>\n"
    else:
        html += '<tr style="background-color: #def">\n'

    html += f"""
        <td style="{padding}">{label}</td>
        <td style="{padding}{numeric}">{format_count(files)}</td>
        <td style="{padding}{numeric}">{format_count(d_files, delta=True)}</td>
        <td style="{padding}{numeric}">{format_bytes(bytes)}</td>
        <td style="{padding}{numeric}">{format_bytes(d_bytes, delta=True)}</td>
        </tr>
    """
    return html


def get_html(data: Snapshot) -> str:
    html = ""

    if data["metadata"]["delta"]:
        delta = humanize.precisedelta(data["metadata"]["delta"])
        now = data["metadata"]["now"]
        html += f"<p>In the {delta} leading up to {now}:</p>"

    html += """
        <table>
        <thead>
        <tr style="background-color: #eee">
            <th>Bucket</th>
            <th colspan="2">Files</th>
            <th colspan="2">Size</th>
        </tr>
        </thead>
        <tbody>
    """

    row_num = 0
    for name in sorted(data["buckets"]):
        html += get_row_html(
            name,
            data["buckets"][name]["files"],
            data["buckets"][name]["d_files"],
            data["buckets"][name]["bytes"],
            data["buckets"][name]["d_bytes"],
            row_num,
        )
        row_num += 1

    html += get_row_html(
        "<b>Total</b>",
        data["metadata"]["total_files"],
        data["metadata"]["total_d_files"],
        data["metadata"]["total_bytes"],
        data["metadata"]["total_d_bytes"],
        row_num,
    )
    return html + "</tbody></table>"


def send_email(data: Snapshot) -> None:
    html = get_html(data)
    s_files = format_count(data["metadata"]["total_d_files"], delta=True)
    s_bytes = format_bytes(data["metadata"]["total_d_bytes"], delta=True)

    logging.debug(html)

    message = email.mime.multipart.MIMEMultipart("alternative")
    message["To"] = TO
    message["Sender"] = FROM
    message["Subject"] = f"{SUBJECT} ({s_files} files, {s_bytes})"
    message.attach(email.mime.text.MIMEText(html, "html"))

    server = smtplib.SMTP(SMTP_HOST, port=SMTP_PORT)
    if SMTP_USE_SSL != "no":
        server.starttls(context=ssl.create_default_context())
    server.send_message(message)
    server.quit()


def main() -> None:
    logging.info("Starting")

    listing = sorted(os.listdir(SNAPSHOT_DIR), reverse=True)
    files = [path for path in listing if os.path.isfile(SNAPSHOT_DIR / path)]
    if not files:
        logging.error("No snapshots found in: %s", SNAPSHOT_DIR)
        sys.exit(1)

    current = load_snapshot(SNAPSHOT_DIR / files[0])
    previous = load_snapshot(SNAPSHOT_DIR / files[1]) if len(files) >= 2 else {}
    data = compare_snapshots(current, previous)

    send_email(data)
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
