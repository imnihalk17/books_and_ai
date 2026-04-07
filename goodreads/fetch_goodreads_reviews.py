from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import time
import json
import argparse
import os
import math

def parse_reviews(soup):
    """Helper to extract metadata from the current page source."""
    results = []
    review_cards = soup.find_all('article', class_='ReviewCard')
    
    for card in review_cards:
        # 1. Reviewer Name & Profile
        name_tag = card.find(attrs={"data-testid": "name"})
        user = name_tag.get_text(strip=True) if name_tag else "Unknown"
        profile = name_tag.find('a').get('href', '') if name_tag and name_tag.find('a') else ""

        # 2. Metadata (Reviewer stats)
        meta_stats = card.find('div', class_='ReviewerProfile__meta')
        stats = meta_stats.get_text(" | ", strip=True) if meta_stats else ""

        # 3. Rating (from aria-label)
        rating_tag = card.find('span', class_='RatingStars')
        rating = rating_tag.get('aria-label', 'No rating') if rating_tag else "No rating"

        # 4. Date & Permalink
        row = card.find('section', class_='ReviewCard__row')
        date_link = row.find('a') if row else None
        date = date_link.get_text(strip=True) if date_link else ""
        permalink = date_link.get('href', '') if date_link else ""

        # 5. Review Text (Full content)
        content_tag = card.find(attrs={"data-testid": "contentContainer"})
        text = content_tag.get_text(separator="\n", strip=True) if content_tag else ""

        results.append({
            "user": user,
            "stats": stats,
            "rating": rating,
            "date": date,
            "text": text,
            "profile": profile,
            "link": permalink
        })
    return results

def close_popup(driver):
    """Checks for and closes any overlay popup that might block clicks."""
    try:
        # Using a very short timeout so we don't slow down the script
        close_btn = WebDriverWait(driver, 2).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[aria-label="Close"]'))
        )
        driver.execute_script("arguments[0].click();", close_btn)
        print("Popup dismissed.")
        time.sleep(1)
    except Exception:
        # No popup found, move on
        return

def make_fallback_key(r):
    return f"{r.get('user','')}_{r.get('date','')}_{(r.get('text') or '')[:60]}"


def fetch_reviews_after_click(url, page_wait=15):
    """Fetch reviews for a single book URL. Attempts a single 'Show more' click per loop iteration.

    Returns a list of review dicts.
    """
    driver = webdriver.Chrome()
    wait = WebDriverWait(driver, page_wait)

    # Use a dictionary keyed by 'link' to handle batch extraction and deduplication
    all_reviews_dict = {}

    try:
        # STEP 1: Fetch initial reviews from landing page
        print(f"Landing on page: {url}")
        driver.get(url)
        close_popup(driver)  # Check for initial popups

        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'article.ReviewCard')))
        soup_landing = BeautifulSoup(driver.page_source, 'html.parser')
        for r in parse_reviews(soup_landing):
            key = r.get('link') or make_fallback_key(r)
            all_reviews_dict[key] = r
        print(f"Stored {len(all_reviews_dict)} reviews from landing page.")

        # STEP 2: Navigate to the dedicated reviews page
        print("Navigating to the dedicated reviews page...")
        close_popup(driver)
        try:
            more_link_element = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, 'a[aria-label="Tap to show more reviews and ratings"]')
            ))
            full_reviews_url = more_link_element.get_attribute('href')
            if full_reviews_url:
                driver.get(full_reviews_url)
        except Exception:
            # If no dedicated reviews page link exists, continue on the current page
            print("No dedicated reviews page link found; continuing on landing page.")

        # STEP 3: Iteratively parse and click batches
        print("Iterating through batches...")
        while True:
            # Check for popups before each action
            close_popup(driver)

            # Wait for content to load
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'article.ReviewCard')))
            time.sleep(2)

            # EXTRACT BATCH
            current_soup = BeautifulSoup(driver.page_source, 'html.parser')
            batch = parse_reviews(current_soup)

            new_count = 0
            for r in batch:
                key = r.get('link') or make_fallback_key(r)
                if key not in all_reviews_dict:
                    all_reviews_dict[key] = r
                    new_count += 1

            print(f"Added {new_count} new reviews. Total collected: {len(all_reviews_dict)}")

            # Try to find and click 'Show more' once
            try:
                load_more_button = wait.until(EC.presence_of_element_located(
                    (By.XPATH, "//button[descendant::span[@data-testid='loadMore']]")
                ))

                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", load_more_button)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", load_more_button)
                print("Clicked 'Show more'.")

                # Immediate popup check and short buffer for new content
                time.sleep(1)
                close_popup(driver)
                time.sleep(3)
                # continue looping to extract newly loaded reviews
                continue
            except Exception:
                print("No more 'Show more' buttons found.")
                break

        return list(all_reviews_dict.values())

    finally:
        driver.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Fetch Goodreads reviews for URLs listed in a JSON file.')
    parser.add_argument('--input', '-i', default='goodreads_urls.json', help='Input JSON file containing list of URLs or objects with URL fields')
    parser.add_argument('--output', '-o', default='goodreads_reviews.json', help='Output JSON file to write aggregated reviews')
    parser.add_argument('--retries', '-r', type=int, default=3, help='Number of attempts per URL on failure')
    parser.add_argument('--pause', '-p', type=float, default=2.0, help='Seconds to pause between successful URL fetches')
    # removed click-retries: single click attempt will be used for 'Show more'
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"Input file not found: {args.input}")
        raise SystemExit(1)

    with open(args.input, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Normalize to list of (url, source) tuples. If input is a mapping of filename->url,
    # preserve the filename as the source so we can annotate results.
    url_items = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                url_items.append((item, None))
            elif isinstance(item, dict):
                found = False
                for key in ('url', 'goodreads_url', 'link', 'goodreadsLink'):
                    if key in item and isinstance(item[key], str) and item[key].strip():
                        source = item.get('filename') or item.get('epub') or item.get('id')
                        url_items.append((item[key].strip(), source))
                        found = True
                        break
                if not found:
                    # try any string value in the dict
                    for v in item.values():
                        if isinstance(v, str) and v.startswith('http'):
                            url_items.append((v, None))
                            break
    elif isinstance(data, dict):
        # Two possibilities: mapping filename->url OR an object with 'urls' list
        is_map = all(isinstance(k, str) and isinstance(v, str) and v.startswith('http') for k, v in data.items())
        if is_map:
            for fname, url in data.items():
                url_items.append((url, fname))
        else:
            possible = data.get('urls') or data.get('links')
            if isinstance(possible, list):
                for it in possible:
                    if isinstance(it, str):
                        url_items.append((it, None))

    if not url_items:
        print('No URLs found in input JSON. Ensure it contains a list or a filename->url mapping.')
        raise SystemExit(1)

    # Map source_key (filename or URL) -> dict(key->review) for per-book deduplication
    results_by_source = {}

    def add_batch(batch, source=None, url=None):
        source_key = source if source else url
        per_source = results_by_source.setdefault(source_key, {})
        for r in batch:
            # DO NOT add 'source' field to output (per request)
            key = r.get('link') or make_fallback_key(r)
            if key not in per_source:
                per_source[key] = r

    output_file = args.output

    # If an output file already exists, load it so we can skip already-processed sources
    if os.path.isfile(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                existing = json.load(f)
            # existing is expected to be a mapping source->list(reviews)
            if isinstance(existing, dict):
                for src, reviews_list in existing.items():
                    if isinstance(reviews_list, list):
                        per = results_by_source.setdefault(src, {})
                        for r in reviews_list:
                            key = r.get('link') or make_fallback_key(r)
                            if key not in per:
                                per[key] = r
        except Exception:
            # If loading fails, ignore and continue with empty results_by_source
            print(f"Warning: failed to read existing output file {output_file}; proceeding fresh.")

    for idx, (url, source) in enumerate(url_items, 1):
        display_source = source if source else url
        source_key = source if source else url
        # Skip if this source already has reviews loaded from existing output
        if source_key in results_by_source and len(results_by_source[source_key]) > 0:
            print(f"Skipping {idx}/{len(url_items)}: {display_source} (already present in output)")
            # Still write current aggregated results to ensure output file remains updated
            try:
                out_map = {src: list(per.values()) for src, per in results_by_source.items()}
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(out_map, f, ensure_ascii=False, indent=4)
            except Exception:
                pass
            continue
        print(f"Processing {idx}/{len(url_items)}: {display_source}")
        success = False

        for attempt in range(1, args.retries + 1):
            try:
                batch = fetch_reviews_after_click(url)
                add_batch(batch, source=source, url=url)
                print(f"Collected {len(batch)} reviews from this URL.")
                success = True
                break
            except Exception as e:
                backoff = math.pow(2, attempt)
                print(f"Attempt {attempt} for URL failed: {e}; retrying in {backoff}s...")
                time.sleep(backoff)

        if not success:
            print(f"Failed to fetch reviews for URL after {args.retries} attempts: {display_source}")

        # Write current aggregated results to output after each file processed
        try:
            # Prepare per-source lists for output
            out_map = {src: list(per.values()) for src, per in results_by_source.items()}
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(out_map, f, ensure_ascii=False, indent=4)
            total = sum(len(per) for per in results_by_source.values())
            print(f"Wrote {total} total reviews to {output_file} (after processing {display_source}).")
        except Exception as e:
            print(f"Failed to write progressive output to {output_file}: {e}")

        # Pause between URLs to be polite and avoid rate-limiting
        if idx < len(url_items):
            time.sleep(args.pause)