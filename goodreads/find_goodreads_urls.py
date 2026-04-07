from __future__ import annotations

import json
import re
import time
import urllib.parse
from pathlib import Path
from typing import Dict, Optional, List

import requests
from bs4 import BeautifulSoup

INPUT_METADATA = "metadata.json"
OUTPUT_VALID = "goodreads_urls.json"
OUTPUT_NOT_FOUND = "goodreads_not_found.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    )
}


def clean_metadata_title(raw: str) -> str:
    if not raw:
        return ""
    s = raw
    s = re.sub(r"^\s*(\[[^\]]+\]\s*)+", "", s)
    s = re.sub(r"\s*Download\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalise_title_from_filename(fn: str) -> str:
    if fn.lower().endswith(".epub"):
        fn = fn[:-5]
    t = fn.replace("_", " ")
    t = re.sub(r"\s*-\s*", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def get_soup(url: str, session: requests.Session) -> BeautifulSoup:
    last_exc = None
    for attempt in range(1, 4):
        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as exc:
            last_exc = exc
            time.sleep(0.5 * attempt)
    raise last_exc


def search_goodreads(query: str, session: requests.Session) -> Optional[str]:
    q = urllib.parse.quote_plus(query)
    url = f"https://www.goodreads.com/search?q={q}"
    soup = get_soup(url, session)

    # Current Goodreads layout (and old fallback)
    a = soup.select_one("a.bookTitle")
    if a and a.get("href"):
        return urllib.parse.urljoin("https://www.goodreads.com", a["href"].split("?")[0])

    a2 = soup.select_one("a[href^='/book/show/']")
    if a2 and a2.get("href"):
        return urllib.parse.urljoin("https://www.goodreads.com", a2["href"].split("?")[0])

    return None


def build_queries(entry: dict) -> List[str]:
    raw_title = entry.get("title") or ""
    author = entry.get("author") or ""
    epub = entry.get("epub_filename") or ""

    cleaned_title = clean_metadata_title(raw_title)
    queries: List[str] = []

    if cleaned_title and author:
        queries.append(f"{cleaned_title} {author}")
    if cleaned_title:
        queries.append(cleaned_title)
    if epub:
        queries.append(normalise_title_from_filename(epub))

    # de-dup while preserving order
    seen = set()
    ordered = []
    for q in queries:
        key = q.strip().lower()
        if key and key not in seen:
            seen.add(key)
            ordered.append(q.strip())
    return ordered


def main() -> None:
    in_path = Path(INPUT_METADATA)
    if not in_path.exists():
        raise FileNotFoundError(INPUT_METADATA)

    with in_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("metadata_new.json must be a list of metadata entries")

    session = requests.Session()
    session.headers.update(HEADERS)

    found: Dict[str, str] = {}
    not_found: Dict[str, dict] = {}

    total = len(data)
    for idx, entry in enumerate(data, start=1):
        epub = entry.get("epub_filename")
        if not epub:
            continue

        url = None
        used_query = None

        for query in build_queries(entry):
            try:
                candidate = search_goodreads(query, session)
            except Exception:
                candidate = None
            if candidate:
                url = candidate
                used_query = query
                break

        if url:
            found[epub] = url
        else:
            not_found[epub] = {
                "title": entry.get("title", ""),
                "author": entry.get("author", ""),
                "queries": build_queries(entry),
                "error": "search_not_found",
            }

        if idx % 25 == 0 or idx == total:
            print(f"Processed {idx}/{total} | found={len(found)} | not_found={len(not_found)}", flush=True)

        time.sleep(0.35)

    with Path(OUTPUT_VALID).open("w", encoding="utf-8") as f:
        json.dump(found, f, ensure_ascii=False, indent=2)

    with Path(OUTPUT_NOT_FOUND).open("w", encoding="utf-8") as f:
        json.dump(not_found, f, ensure_ascii=False, indent=2)

    print("Done")
    print(f"Valid URLs: {OUTPUT_VALID} ({len(found)})")
    print(f"Not found: {OUTPUT_NOT_FOUND} ({len(not_found)})")


if __name__ == "__main__":
    main()
