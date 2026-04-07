from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

ROOT = Path(__file__).resolve().parent
METADATA_PATH = ROOT / "metadata.json"
VALID_URLS_PATH = ROOT / "amazon_urls.json"
MISMATCHES_PATH = ROOT / "amazon_mismatches.json"
VALIDATION_PATH = ROOT / "amazon_validation.json"
DEBUG_DIR = ROOT / "amazon_debug_html"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/115.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

THRESHOLD = 0.34
REQUEST_RETRIES = 5
REQUEST_RETRY_BACKOFF = 1.0
PAUSE_SECONDS = 2
PAUSE_JITTER_SECONDS = 0.8
CAPTCHA_BACKOFF_SECONDS = 12


def get_soup(url: str, session: requests.Session) -> BeautifulSoup:
    attempt = 0
    while True:
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except requests.exceptions.Timeout:
            attempt += 1
            if attempt >= REQUEST_RETRIES:
                raise
            time.sleep(REQUEST_RETRY_BACKOFF * attempt)
        except requests.exceptions.RequestException:
            raise


def get_soup_playwright(url: str) -> Optional[BeautifulSoup]:
    if not PLAYWRIGHT_AVAILABLE:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = page.content()
            browser.close()
        return BeautifulSoup(html, "lxml")
    except Exception:
        return None


def is_bot_or_captcha_page(soup: BeautifulSoup) -> bool:
    text = soup.get_text(" ", strip=True).lower()
    markers = [
        "robot check",
        "captcha",
        "opfcaptcha",
        "not a robot",
        "enter the characters you see below",
        "sorry, we just need to make sure",
    ]
    return any(m in text for m in markers)


def normalize_asin(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(value)).upper()
    return cleaned if len(cleaned) == 10 else None


def extract_asin_from_soup(soup: BeautifulSoup) -> Optional[str]:
    try:
        n = soup.select_one('[data-asin]')
        if n and n.get('data-asin'):
            asin = normalize_asin(n.get('data-asin'))
            if asin:
                return asin
    except Exception:
        pass
    for a in soup.find_all('a', href=True):
        href = a.get('href') or ""
        m = re.search(r'/dp/([A-Z0-9]{10})', href)
        if m:
            return m.group(1)
    return None


def is_book_product_page(soup: BeautifulSoup) -> bool:
    title = (
        soup.select_one("#productTitle")
        or soup.select_one("span#productTitle")
        or soup.select_one("#ebooksProductTitle")
        or soup.select_one("h1 span")
    )
    if title:
        t = title.get_text(strip=True).lower()
        # Only reject obvious multi-book bundle pages.
        bundle_markers = [
            "box set",
            "books included",
            "complete series",
            "omnibus",
            "book bundle",
        ]
        if any(marker in t for marker in bundle_markers):
            return False
        if t:
            return True

    # If byline exists, this is very likely a valid product page.
    if soup.select_one("#bylineInfo"):
        return True

    asin = extract_asin_from_soup(soup)
    if asin:
        # ASIN present on page usually indicates a real product page.
        return True
    return False


def extract_title_author_from_amazon(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
    title = None
    tsel = soup.select_one("#productTitle") or soup.select_one("span#productTitle") or soup.select_one("h1 span")
    if tsel:
        title = tsel.get_text(" ", strip=True)
    if not title:
        for sel, attr in [
            ("meta[property='og:title']", "content"),
            ("meta[name='twitter:title']", "content"),
        ]:
            m = soup.select_one(sel)
            if m and m.get(attr):
                title = m.get(attr).strip()
                break

    author = None
    for sel in ["a.contributorNameID", "span.author a.a-link-normal", "#bylineInfo a", "a[href*='/author/']"]:
        a = soup.select_one(sel)
        if a and a.get_text(strip=True):
            author = a.get_text(" ", strip=True)
            break

    if not author:
        byline = soup.select_one("#bylineInfo")
        if byline:
            txt = byline.get_text(" ", strip=True)
            if txt:
                author = re.sub(r"^by\s+", "", txt, flags=re.IGNORECASE)
                author = author.split(";")[0].strip()
    if not author:
        for sel, attr in [
            ("meta[name='author']", "content"),
            ("meta[property='book:author']", "content"),
        ]:
            m = soup.select_one(sel)
            if m and m.get(attr):
                author = m.get(attr).strip()
                break

    if title:
        title = re.sub(r"\s+", " ", title).strip()
        title = re.sub(r"\s*\([^)]*(?:Book|Series|Vol\.|#)[^)]*\)\s*", " ", title).strip()
    if author:
        author = re.sub(r"\s+", " ", author).strip()
    return title, author


def tokenize(text: str) -> set:
    text = re.sub(r"[^\w\s]", " ", text or "")
    return {p.lower() for p in text.split() if p.strip()}


def similarity_score(a: Optional[str], b: Optional[str]) -> float:
    if not a or not b:
        return 0.0
    sa = tokenize(a)
    sb = tokenize(b)
    if not sa and not sb:
        return 0.0
    inter = sa.intersection(sb)
    return (2 * len(inter)) / (len(sa) + len(sb))


def author_name_score(meta_author: Optional[str], found_author: Optional[str]) -> float:
    if not meta_author or not found_author:
        return 0.0
    score = similarity_score(meta_author, found_author)

    def last(name: str) -> str:
        parts = [p for p in name.split() if p.strip()]
        return parts[-1].lower() if parts else ""

    try:
        if last(meta_author) and last(meta_author) == last(found_author):
            score = max(score, 0.9)
    except Exception:
        pass
    return score


def load_metadata() -> Dict[str, dict]:
    with open(METADATA_PATH, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    out: Dict[str, dict] = {}
    for e in data:
        if not isinstance(e, dict):
            continue
        epub = e.get("epub_filename")
        if not epub:
            continue
        out[epub] = e
    return out


def load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def clean_metadata_title(raw: str) -> str:
    if not raw:
        return ""
    s = re.sub(r"^\s*(\[[^\]]+\]\s*)+", "", raw)
    s = re.sub(r"\s*Download\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def pause_after_book() -> None:
    time.sleep(PAUSE_SECONDS + random.uniform(0, PAUSE_JITTER_SECONDS))


def has_product_signals(soup: BeautifulSoup) -> bool:
    if is_book_product_page(soup):
        return True
    found_title, found_author = extract_title_author_from_amazon(soup)
    if found_title or found_author:
        return True
    page_title = (soup.title.get_text(" ", strip=True).lower() if soup.title else "")
    if page_title and page_title != "amazon.com":
        return True
    return False


def main() -> None:
    metadata_map = load_metadata()

    valid_urls: Dict[str, str] = load_json(VALID_URLS_PATH, {})
    mismatches: Dict[str, dict] = load_json(MISMATCHES_PATH, {})
    validation_data: Dict[str, dict] = load_json(VALIDATION_PATH, {})

    processed_keys = set(valid_urls.keys()) | set(mismatches.keys()) | set(validation_data.keys())
    to_process = [(k, v) for k, v in metadata_map.items() if k not in processed_keys]

    print(f"Loaded metadata entries: {len(metadata_map)}")
    print(f"Already processed: {len(processed_keys)}")
    print(f"To process now: {len(to_process)}")

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    added_count = 0
    processed_count = 0

    for epub_fn, entry in to_process:
        metadata_title = clean_metadata_title(entry.get("title") or "")
        metadata_author = entry.get("author") or ""
        asin = normalize_asin(entry.get("asin"))

        print(f"\n{'='*80}")
        print(f"[{processed_count + 1}/{len(to_process)}] Processing {epub_fn}")
        print(f"  Expected: {metadata_title} by {metadata_author}")

        if not asin:
            print("  - Missing valid ASIN in metadata, skipping")
            mismatches[epub_fn] = {
                "url": None,
                "metadata_title": metadata_title,
                "metadata_author": metadata_author,
                "found_title": None,
                "found_author": None,
                "title_score": 0.0,
                "author_score": 0.0,
                "metadata_combined": f"{metadata_title} {metadata_author}".strip(),
                "found_combined": None,
                "combined_score": 0.0,
                "error": "missing_or_invalid_asin",
            }
            save_json(MISMATCHES_PATH, mismatches)
            processed_count += 1
            pause_after_book()
            continue

        url = f"https://www.amazon.com/dp/{asin}"
        print(f"  URL from ASIN: {url}")

        try:
            soup = get_soup(url, session)
        except Exception as e:
            print(f"  ERROR fetching page: {e}")
            mismatches[epub_fn] = {
                "url": url,
                "metadata_title": metadata_title,
                "metadata_author": metadata_author,
                "found_title": None,
                "found_author": None,
                "title_score": 0.0,
                "author_score": 0.0,
                "metadata_combined": f"{metadata_title} {metadata_author}".strip(),
                "found_combined": None,
                "combined_score": 0.0,
                "error": str(e),
            }
            save_json(MISMATCHES_PATH, mismatches)
            processed_count += 1
            pause_after_book()
            continue

        # Some ASIN pages return a generic Amazon shell over requests.
        # Try alternate product URL forms before classifying/scoring.
        if not has_product_signals(soup):
            alt_urls = [
                f"https://www.amazon.com/gp/aw/d/{asin}",
                f"https://www.amazon.com/-/dp/{asin}",
            ]
            for alt_url in alt_urls:
                try:
                    alt_soup = get_soup(alt_url, session)
                except Exception:
                    continue
                if has_product_signals(alt_soup):
                    print(f"  - Using alternate URL form for better page content: {alt_url}")
                    soup = alt_soup
                    break

        if is_bot_or_captcha_page(soup):
            print("  - Detected bot/captcha page (requests)")
            time.sleep(CAPTCHA_BACKOFF_SECONDS)
            fallback = get_soup_playwright(url)
            if fallback:
                soup = fallback

        if not is_book_product_page(soup):
            print("  - Page did not look like a book product page, retrying with Playwright...")
            fallback = get_soup_playwright(url)
            if fallback:
                soup = fallback

        if not is_book_product_page(soup):
            # Do not hard-fail on this check; some valid Amazon book pages render
            # minimal or variant layouts that miss title/byline selectors.
            print("  - Product-page check still inconclusive; continuing with title/author scoring.")

        found_title, found_author = extract_title_author_from_amazon(soup)
        print(f"  Found on page: {found_title} by {found_author}")

        page_asin = extract_asin_from_soup(soup)

        if not found_title and not found_author:
            if is_bot_or_captcha_page(soup):
                print("  - Could not extract title/author due to bot/captcha page. Deferring this book for retry in a later run.")
                processed_count += 1
                pause_after_book()
                continue

            if page_asin and page_asin == asin:
                print("  - Title/author selectors missing, but page ASIN matches metadata ASIN. Accepting via ASIN fallback.")
                found_title = metadata_title
                found_author = metadata_author
            else:
                print("  - Could not extract title/author and could not verify ASIN match. Deferring this book for retry in a later run.")
                processed_count += 1
                pause_after_book()
                continue

        title_score = similarity_score(metadata_title, found_title)
        author_score = author_name_score(metadata_author, found_author)

        metadata_combined = f"{metadata_title} {metadata_author}".strip() if metadata_author else metadata_title
        found_combined = f"{found_title} {found_author}".strip() if found_title and found_author else found_title
        combined_score = similarity_score(metadata_combined, found_combined)

        print(f"  Scores - Title: {title_score:.3f}, Author: {author_score:.3f}, Combined: {combined_score:.3f}")

        validation_entry = {
            "url": url,
            "metadata_title": metadata_title,
            "metadata_author": metadata_author,
            "found_title": found_title,
            "found_author": found_author,
            "page_asin": page_asin,
            "title_score": title_score,
            "author_score": author_score,
            "metadata_combined": metadata_combined,
            "found_combined": found_combined,
            "combined_score": combined_score,
        }

        validation_data[epub_fn] = validation_entry

        if combined_score >= THRESHOLD:
            print(f"  ✓ PASSED! (score {combined_score:.3f} >= {THRESHOLD})")
            valid_urls[epub_fn] = url
            if epub_fn in mismatches:
                del mismatches[epub_fn]
            added_count += 1
        else:
            print(f"  ✗ Failed (score {combined_score:.3f} < {THRESHOLD})")
            mismatches[epub_fn] = validation_entry

        save_json(VALIDATION_PATH, validation_data)
        save_json(VALID_URLS_PATH, valid_urls)
        save_json(MISMATCHES_PATH, mismatches)

        processed_count += 1
        pause_after_book()

    print(f"\n{'='*80}")
    print("Processing complete!")
    print(f"  Processed this run: {processed_count}")
    print(f"  Passed this run: {added_count}")
    print(f"  Failed this run: {processed_count - added_count}")
    print(f"  Total valid URLs: {len(valid_urls)}")
    print(f"  Total validation entries: {len(validation_data)}")
    print(f"  Remaining mismatches: {len(mismatches)}")

if __name__ == "__main__":
    main()
