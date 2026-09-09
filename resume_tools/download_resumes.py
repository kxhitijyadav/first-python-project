"""Bulk-download the resumes listed in the recruiter markdown export.

Files land in one folder per markdown heading, e.g.::

    resumes/Software_Engineer_Candidates/72734_Chenxu_Zhang_..._Resume.pdf
    resumes/Machine_Learning_Engineer/72847_Srinivas_..._Resume.docx

The run is restartable: files that already downloaded are skipped, and every
attempt is recorded in ``manifest.json`` next to the downloads.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from resume_links import ResumeLink, load

try:
    import requests
except ImportError:  # pragma: no cover - depends on the machine running this
    sys.exit("requests is required: pip install -r resume_tools/requirements.txt")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}
# Magic bytes for the formats the export contains.
SIGNATURES = {
    b"%PDF": "pdf",
    b"PK\x03\x04": "docx",
    b"\xd0\xcf\x11\xe0": "doc",
}
MIN_BYTES = 1024


@dataclass
class Result:
    filename: str
    group: str
    url: str
    status: str  # downloaded | skipped | failed
    detail: str = ""
    bytes: int = 0
    path: str = ""


def detect_format(head: bytes) -> str | None:
    for magic, kind in SIGNATURES.items():
        if head.startswith(magic):
            return kind
    return None


def looks_like_html(head: bytes) -> bool:
    return head.lstrip()[:200].lower().startswith((b"<!doctype html", b"<html"))


def fetch(
    session: requests.Session, link: ResumeLink, dest: Path, timeout: int, retries: int
) -> Result:
    """Download one resume, retrying transient failures with backoff."""
    partial = dest.with_suffix(dest.suffix + ".part")
    last_error = ""

    for attempt in range(1, retries + 1):
        try:
            with session.get(link.url, timeout=timeout, stream=True) as response:
                if response.status_code in RETRY_STATUSES:
                    last_error = f"HTTP {response.status_code}"
                    raise TransientError(last_error)
                if response.status_code != 200:
                    return Result(
                        link.filename,
                        link.group,
                        link.url,
                        "failed",
                        f"HTTP {response.status_code}",
                    )

                size = 0
                head = b""
                with partial.open("wb") as handle:
                    for chunk in response.iter_content(64 * 1024):
                        if not chunk:
                            continue
                        if len(head) < 512:
                            head += chunk[: 512 - len(head)]
                        handle.write(chunk)
                        size += len(chunk)

            if looks_like_html(head):
                partial.unlink(missing_ok=True)
                return Result(
                    link.filename,
                    link.group,
                    link.url,
                    "failed",
                    "server returned a web page, not a file "
                    "(link expired, or it needs a signed-in session)",
                )
            if size < MIN_BYTES or detect_format(head) is None:
                partial.unlink(missing_ok=True)
                return Result(
                    link.filename,
                    link.group,
                    link.url,
                    "failed",
                    f"unrecognised content ({size} bytes)",
                )

            partial.replace(dest)
            return Result(
                link.filename, link.group, link.url, "downloaded", "", size, str(dest)
            )

        except (TransientError, requests.RequestException) as error:
            last_error = last_error or f"{type(error).__name__}: {error}"
            partial.unlink(missing_ok=True)
            if attempt == retries:
                break
            # exponential backoff with jitter, so a rate limit is not hammered
            time.sleep(min(2**attempt, 30) + random.uniform(0, 1))
            last_error = ""

    return Result(link.filename, link.group, link.url, "failed", last_error or "unknown")


class TransientError(Exception):
    pass


def download_all(
    links: list[ResumeLink],
    out_dir: Path,
    workers: int,
    timeout: int,
    retries: int,
    delay: float,
) -> list[Result]:
    results: list[Result] = []
    lock = threading.Lock()
    local = threading.local()
    done = 0
    total = len(links)

    def job(link: ResumeLink) -> Result:
        folder = out_dir / link.slug
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / link.filename
        if dest.exists() and dest.stat().st_size >= MIN_BYTES:
            return Result(
                link.filename,
                link.group,
                link.url,
                "skipped",
                "already downloaded",
                dest.stat().st_size,
                str(dest),
            )
        if delay:
            time.sleep(random.uniform(0, delay))
        session = getattr(local, "session", None)
        if session is None:
            session = local.session = requests.Session()
            session.headers["User-Agent"] = USER_AGENT
        return fetch(session, link, dest, timeout, retries)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(job, link): link for link in links}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            with lock:
                done += 1
                results.append(result)
                mark = {"downloaded": "ok", "skipped": "--", "failed": "FAIL"}[
                    result.status
                ]
                print(
                    f"[{done:>4}/{total}] {mark:<4} {result.filename}"
                    + (f"  ({result.detail})" if result.detail else "")
                )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("markdown", type=Path, help="the exported .md file")
    parser.add_argument(
        "-o", "--out", type=Path, default=Path("resumes"), help="download folder"
    )
    parser.add_argument("-j", "--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="max random pause before each request, in seconds",
    )
    parser.add_argument(
        "--group", action="append", help="only this heading (repeatable)"
    )
    parser.add_argument("--limit", type=int, help="stop after N links (for a dry run)")
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="only retry the links that failed in the previous run",
    )
    args = parser.parse_args(argv)

    links = load(args.markdown)
    if args.group:
        wanted = {g.lower() for g in args.group}
        links = [l for l in links if l.group.lower() in wanted]
    manifest_path = args.out / "manifest.json"
    if args.retry_failed and manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        failed = {r["url"] for r in previous["results"] if r["status"] == "failed"}
        links = [l for l in links if l.url in failed]
        print(f"retrying {len(links)} previously failed link(s)")
    if args.limit:
        links = links[: args.limit]

    if not links:
        print("nothing to download")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    results = download_all(
        links, args.out, args.workers, args.timeout, args.retries, args.delay
    )

    counts = {"downloaded": 0, "skipped": 0, "failed": 0}
    for result in results:
        counts[result.status] += 1

    # keep what earlier runs recorded for links this run did not touch
    merged: dict[str, dict] = {}
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        merged = {r["url"]: r for r in previous.get("results", [])}
    merged.update({r.url: vars(r) for r in results})
    manifest_path.write_text(
        json.dumps(
            {
                "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "source": str(args.markdown),
                "counts_this_run": counts,
                "results": list(merged.values()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"\n{counts['downloaded']} downloaded, {counts['skipped']} already there, "
        f"{counts['failed']} failed in {time.time() - started:.0f}s"
    )
    print(f"manifest: {manifest_path}")
    if counts["failed"]:
        print("retry them with the same command plus --retry-failed")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
