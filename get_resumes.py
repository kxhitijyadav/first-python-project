#!/usr/bin/env python3
"""Download every candidate resume from the LXR markdown export.

Just put this file in the same folder as the exported .md and run it:

    python3 get_resumes.py

It creates one folder per heading in the export and fills it with the
resumes.  Nothing to install, no arguments, and you can re-run it safely:
anything already downloaded is skipped and only the gaps are retried.
"""

from __future__ import annotations

import concurrent.futures
import gzip
import io
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

LINK_RE = re.compile(r"^\[(?P<label>.+?)\]\((?P<url>https?://[^)\s]+)\)\s*$")
SAFELINKS_HOST = "safelinks.protection.outlook.com"
ILLEGAL_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
SIGNATURES = {b"%PDF": ".pdf", b"PK\x03\x04": ".docx", b"\xd0\xcf\x11\xe0": ".doc"}
MIN_BYTES = 1024
WORKERS = 4
TIMEOUT = 90
PASSES = 3  # whole-list retry rounds, so nothing is quietly left behind
ATTEMPTS = 3  # per-file attempts inside one pass
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

print_lock = threading.Lock()


# --------------------------------------------------------------- parsing


def clean_name(label: str) -> str:
    name = label.replace("\\_", "_").replace("\\", "").strip()
    name = ILLEGAL_CHARS_RE.sub("_", name)
    return name.strip(". ") or "resume"


def unwrap(url: str) -> str:
    """Outlook wraps every link in a safelinks redirect; unwrap it."""
    if SAFELINKS_HOST not in urllib.parse.urlparse(url).netloc:
        return url
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return query.get("url", [url])[0]


def parse(markdown: Path) -> list[dict]:
    links, group, seen = [], "Resumes", set()
    for line in markdown.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("## "):
            group = clean_name(line[3:])
            continue
        match = LINK_RE.match(line)
        if not match:
            continue
        url = unwrap(match.group("url"))
        if url in seen:
            continue
        seen.add(url)
        links.append(
            {"group": group, "filename": clean_name(match.group("label")), "url": url}
        )
    return links


def find_markdown() -> Path | None:
    """Locate the export next to this script, or in the current folder.

    Whichever .md holds the most resume links wins, so an unrelated README
    sitting in the same folder cannot be picked by mistake.
    """
    best, best_count = None, 0
    for folder in (Path(__file__).resolve().parent, Path.cwd()):
        for path in sorted(folder.glob("*.md")):
            try:
                count = len(parse(path))
            except OSError:
                continue
            if count > best_count:
                best, best_count = path, count
    return best


# ------------------------------------------------------------ downloading


def build_opener() -> urllib.request.OpenerDirector:
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )
    opener.addheaders = [
        ("User-Agent", USER_AGENT),
        ("Accept", "*/*"),
        ("Accept-Encoding", "gzip"),
    ]
    return opener


def read_body(response) -> bytes:
    data = response.read()
    if response.headers.get("Content-Encoding") == "gzip":
        try:
            data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
        except OSError:
            pass
    return data


def correct_extension(filename: str, data: bytes) -> str:
    """Trust the file's own magic bytes over the name in the export."""
    for magic, extension in SIGNATURES.items():
        if data.startswith(magic):
            stem, _, current = filename.rpartition(".")
            if stem and f".{current.lower()}" != extension:
                return stem + extension
            return filename
    return filename


def download_one(link: dict, out_root: Path, opener) -> dict:
    folder = out_root / link["group"]
    folder.mkdir(parents=True, exist_ok=True)
    existing = folder / link["filename"]

    # already have it (under this name or a corrected extension)?
    stem = existing.stem
    for done in folder.glob(stem + ".*"):
        if done.suffix != ".part" and done.stat().st_size >= MIN_BYTES:
            return {**link, "status": "have", "detail": "", "path": str(done)}

    error = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with opener.open(link["url"], timeout=TIMEOUT) as response:
                data = read_body(response)

            head = data.lstrip()[:200].lower()
            if head.startswith((b"<!doctype html", b"<html")):
                return {
                    **link,
                    "status": "failed",
                    "detail": "got a web page, not a file - the link has expired "
                    "or needs you to be signed in to iCIMS",
                    "path": "",
                }
            if len(data) < MIN_BYTES or not any(
                data.startswith(m) for m in SIGNATURES
            ):
                return {
                    **link,
                    "status": "failed",
                    "detail": f"unrecognised content ({len(data)} bytes)",
                    "path": "",
                }

            dest = folder / correct_extension(link["filename"], data)
            partial = dest.with_name(dest.name + ".part")
            partial.write_bytes(data)
            os.replace(partial, dest)
            return {**link, "status": "downloaded", "detail": "", "path": str(dest)}

        except urllib.error.HTTPError as exc:
            error = f"HTTP {exc.code}"
            if exc.code not in (408, 425, 429, 500, 502, 503, 504):
                break  # a real refusal, retrying will not help
        except Exception as exc:  # network hiccups, timeouts, resets
            error = f"{type(exc).__name__}: {exc}"

        if attempt < ATTEMPTS:
            time.sleep(min(2**attempt, 20) + random.uniform(0, 1))

    return {**link, "status": "failed", "detail": error or "unknown", "path": ""}


def run_pass(links: list[dict], out_root: Path, label: str) -> list[dict]:
    results: list[dict] = []
    local = threading.local()
    total = len(links)
    done = 0

    def job(link):
        opener = getattr(local, "opener", None)
        if opener is None:
            opener = local.opener = build_opener()
        time.sleep(random.uniform(0, 0.5))  # be gentle with the tracking server
        return download_one(link, out_root, opener)

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for result in pool.map(job, links):
            done += 1
            results.append(result)
            mark = {"downloaded": "ok  ", "have": "--  ", "failed": "FAIL"}[
                result["status"]
            ]
            with print_lock:
                note = f"   {result['detail']}" if result["detail"] else ""
                print(f"{label}[{done:>4}/{total}] {mark} {result['filename']}{note}")
    return results


# ------------------------------------------------------------------ main


def main() -> int:
    markdown = Path(sys.argv[1]) if len(sys.argv) > 1 else find_markdown()
    if not markdown or not markdown.exists():
        print(
            "Could not find the export.\n\n"
            "Put this script in the same folder as the .md file from the email\n"
            "and run it again, or run:  python3 get_resumes.py path/to/file.md"
        )
        return 2

    links = parse(markdown)
    if not links:
        print(f"No resume links found in {markdown.name}.")
        return 2

    out_root = markdown.resolve().parent / "Resumes"
    groups: dict[str, int] = {}
    for link in links:
        groups[link["group"]] = groups.get(link["group"], 0) + 1

    print(f"Reading {markdown.name}")
    for group, count in groups.items():
        print(f"  {count:>4} resumes -> Resumes/{group}/")
    print(f"  {len(links):>4} total\n")

    results = {link["url"]: dict(link, status="pending") for link in links}
    pending = links
    for round_number in range(1, PASSES + 1):
        label = "" if round_number == 1 else f"retry {round_number - 1} "
        if round_number > 1:
            print(f"\nRetrying {len(pending)} that did not come through...\n")
            time.sleep(5 * round_number)
        for result in run_pass(pending, out_root, label):
            results[result["url"]] = result
        pending = [r for r in results.values() if r["status"] == "failed"]
        if not pending:
            break

    # ------------------------------------------------------- final report
    got = [r for r in results.values() if r["status"] in ("downloaded", "have")]
    missing = [r for r in results.values() if r["status"] != "downloaded" and r["status"] != "have"]

    print("\n" + "=" * 60)
    for group in groups:
        have = sum(1 for r in got if r["group"] == group)
        print(f"Resumes/{group}/   {have} of {groups[group]}")
    print(f"\n{len(got)} of {len(links)} resumes saved under {out_root}")

    (out_root / "manifest.json").write_text(
        json.dumps(list(results.values()), indent=2), encoding="utf-8"
    )

    if missing:
        report = out_root / "MISSING.txt"
        with report.open("w", encoding="utf-8") as handle:
            handle.write(
                f"{len(missing)} resume(s) could not be downloaded.\n"
                "Open these links yourself in the browser you read the email in -\n"
                "iCIMS tracking links can expire or require a signed-in session.\n\n"
            )
            for item in missing:
                handle.write(
                    f"{item['group']} / {item['filename']}\n"
                    f"  why: {item['detail']}\n  url: {item['url']}\n\n"
                )
        print(f"\n{len(missing)} could NOT be downloaded - see {report}")
        print("Re-run this script later to try them again.")
    else:
        print("\nAll resumes downloaded. Nothing missing.")
    print("=" * 60)

    if sys.platform == "win32" and sys.stdin and sys.stdin.isatty():
        input("\nPress Enter to close...")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
