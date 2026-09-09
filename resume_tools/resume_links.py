"""Parse the recruiter markdown export into a list of resume download links.

The markdown looks like::

    ## Software Engineer Candidates

    [72734\\_Chenxu\\_Zhang\\_73102\\_202608282302\\_Resume.pdf](https://nam02.safelinks...)

Each ``##`` heading starts a new group (one group == one destination project),
and every following link line is one candidate resume.  Outlook "safelinks"
wrappers are unwrapped back to the real tracking URL.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from dataclasses import dataclass, asdict
from pathlib import Path

LINK_RE = re.compile(r"^\[(?P<label>.+?)\]\((?P<url>https?://[^)\s]+)\)\s*$")
SAFELINKS_HOST = "safelinks.protection.outlook.com"
UNSAFE_CHARS_RE = re.compile(r"[^\w.\-() ]+")


@dataclass
class ResumeLink:
    group: str
    filename: str
    url: str

    @property
    def slug(self) -> str:
        """Filesystem-safe directory name for this link's group."""
        return slugify(self.group)


def slugify(text: str) -> str:
    return re.sub(r"[^\w]+", "_", text).strip("_")


def safe_filename(label: str) -> str:
    """Turn a markdown link label into a safe file name."""
    # markdown escapes underscores as \_
    name = label.replace("\\_", "_").replace("\\", "").strip()
    name = name.replace("/", "-")
    name = UNSAFE_CHARS_RE.sub("_", name)
    return name or "resume"


def unwrap_safelink(url: str) -> str:
    """Return the real target behind an Outlook safelinks redirect."""
    if SAFELINKS_HOST not in urllib.parse.urlparse(url).netloc:
        return url
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    target = query.get("url", [None])[0]
    return target or url


def parse_markdown(text: str) -> list[ResumeLink]:
    """Extract every resume link, grouped by the ``##`` heading above it."""
    links: list[ResumeLink] = []
    group = "Ungrouped"
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("## "):
            group = line[3:].strip()
            continue
        match = LINK_RE.match(line)
        if match:
            links.append(
                ResumeLink(
                    group=group,
                    filename=safe_filename(match.group("label")),
                    url=unwrap_safelink(match.group("url")),
                )
            )
    return links


def deduplicate(links: list[ResumeLink]) -> list[ResumeLink]:
    """Drop repeated URLs, keeping the first occurrence."""
    seen: set[str] = set()
    unique: list[ResumeLink] = []
    for link in links:
        if link.url in seen:
            continue
        seen.add(link.url)
        unique.append(link)
    return unique


def load(path: Path) -> list[ResumeLink]:
    return deduplicate(parse_markdown(path.read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("markdown", type=Path, help="the exported .md file")
    parser.add_argument(
        "-o", "--out", type=Path, help="write the parsed links to this JSON file"
    )
    args = parser.parse_args(argv)

    links = load(args.markdown)
    groups: dict[str, int] = {}
    for link in links:
        groups[link.group] = groups.get(link.group, 0) + 1

    for group, count in groups.items():
        print(f"{count:4d}  {group}")
    print(f"{len(links):4d}  TOTAL")

    if args.out:
        args.out.write_text(
            json.dumps([asdict(link) for link in links], indent=2), encoding="utf-8"
        )
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
