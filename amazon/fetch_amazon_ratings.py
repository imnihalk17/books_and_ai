import argparse
import json
import os
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


INPUT_FILE = "amazon_urls.json"
OUTPUT_FILE = "amazon_ratings.json"
AMAZON_EMAIL = "tc2896@columbia.edu"
AMAZON_PASSWORD = "romeitalyA123@"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0


def backoff_sleep(attempt: int, base: float = RETRY_BASE_DELAY) -> None:
    time.sleep(base * attempt + random.uniform(0.5, 1.5))


def load_book_urls(path: str) -> List[Tuple[str, str]]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    items: List[Tuple[str, str]] = []

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str):
                url = value
            elif isinstance(value, dict):
                url = value.get("amazon_url") or value.get("url")
            else:
                continue
            if url:
                items.append((key, url))
    elif isinstance(data, list):
        for entry in data:
            if not isinstance(entry, dict):
                continue
            key = entry.get("epub_filename") or entry.get("filename") or entry.get("name")
            url = entry.get("amazon_url") or entry.get("url")
            if key and url:
                items.append((key, url))

    return items


def parse_int_from_text(text: str) -> Optional[int]:
    if not text:
        return None
    match = re.search(r"([\d,]+)", text)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_percent(text: str) -> Optional[float]:
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def parse_rating_value(text: str) -> Optional[float]:
    if not text:
        return None
    match = re.search(r"([0-5](?:[\.,]\d+)?)\s*out\s*of\s*5", text, re.I)
    if not match:
        return None
    number = match.group(1).replace(",", ".")
    try:
        return float(number)
    except ValueError:
        return None


def is_captcha_or_block_page(html: str) -> bool:
    markers = (
        "validateCaptcha",
        "Type the characters you see",
        "Enter the characters you see below",
        "Sorry, we just need to make sure you're not a robot",
    )
    return any(marker in html for marker in markers)


def extract_total_and_star_wise_ratings(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")

    result: Dict[str, Any] = {
        "overall_rating": None,
        "total_ratings": None,
        "star_wise_ratings": {
            "5_star": None,
            "4_star": None,
            "3_star": None,
            "2_star": None,
            "1_star": None,
        },
    }

    total_sources: List[str] = []

    review_text = soup.select_one("#acrCustomerReviewText")
    if review_text is not None:
        total_sources.append(review_text.get_text(" ", strip=True))

    ratings_count = soup.find("span", attrs={"data-hook": "total-review-count"})
    if ratings_count is not None:
        total_sources.append(ratings_count.get_text(" ", strip=True))

    meta_count = soup.find("meta", attrs={"itemprop": "ratingCount"})
    if meta_count is not None and meta_count.get("content"):
        total_sources.append(meta_count.get("content", ""))

    for source in total_sources:
        parsed = parse_int_from_text(source)
        if parsed is not None:
            result["total_ratings"] = parsed
            break

    overall_sources: List[str] = []
    acr = soup.select_one("#acrPopover")
    if acr is not None:
        overall_sources.append(acr.get("title", ""))
        overall_sources.append(acr.get_text(" ", strip=True))

    rating_out_of_text = soup.select_one("span[data-hook='rating-out-of-text']")
    if rating_out_of_text is not None:
        overall_sources.append(rating_out_of_text.get_text(" ", strip=True))

    icon_alt = soup.select_one("span.a-icon-alt")
    if icon_alt is not None:
        overall_sources.append(icon_alt.get_text(" ", strip=True))

    meta_rating = soup.find("meta", attrs={"itemprop": "ratingValue"})
    if meta_rating is not None and meta_rating.get("content"):
        overall_sources.append(f"{meta_rating.get('content', '')} out of 5")

    for source in overall_sources:
        parsed_rating = parse_rating_value(source)
        if parsed_rating is not None:
            result["overall_rating"] = parsed_rating
            break

    histogram_container = soup.select_one("#histogramTable")
    if histogram_container is not None:
        for item in histogram_container.find_all("li"):
            labelled = item.find(["a", "span"], attrs={"aria-label": True})
            if labelled is None:
                continue
            aria_text = labelled.get("aria-label", "")
            match = re.search(
                r"(\d+(?:\.\d+)?)\s*percent\s+of\s+reviews\s+have\s+([1-5])\s*stars?",
                aria_text,
                re.I,
            )
            if match:
                pct = float(match.group(1))
                star = int(match.group(2))
                result["star_wise_ratings"][f"{star}_star"] = pct

    if all(v is None for v in result["star_wise_ratings"].values()):
        page_text = soup.get_text(" ", strip=True)
        seen_stars = set()
        for match in re.finditer(r"\b([1-5])\s*star[s]?\b.*?(\d+(?:\.\d+)?)\s*%", page_text, re.I):
            star = int(match.group(1))
            if star in seen_stars:
                continue
            result["star_wise_ratings"][f"{star}_star"] = float(match.group(2))
            seen_stars.add(star)

    return result


def perform_amazon_login(driver: webdriver.Chrome, email: str, password: str) -> bool:
    wait = WebDriverWait(driver, 10)

    print("  > Starting login flow...")

    try:
        continue_shopping_btn = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[@alt='Continue shopping']"))
        )
        continue_shopping_btn.click()
        print("  > Clicked 'Continue shopping'")
    except Exception:
        print("  > 'Continue shopping' button not found, skipping step.")

    try:
        email_field = wait.until(EC.visibility_of_element_located((By.ID, "ap_email_login")))
    except Exception:
        email_field = wait.until(EC.visibility_of_element_located((By.NAME, "email")))

    try:
        email_field.clear()
        email_field.send_keys(email)
        print("  > Entered email")
    except Exception as error:
        print(f"  > Error entering email: {error}")

    try:
        continue_btn = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input[aria-labelledby='continue-announce']"))
        )
        continue_btn.click()
        print("  > Clicked 'Continue'")
    except Exception as error:
        print(f"  > Error clicking Continue: {error}")

    try:
        password_field = wait.until(EC.visibility_of_element_located((By.ID, "ap_password")))
        password_field.clear()
        password_field.send_keys(password)
        print("  > Entered password")
    except Exception as error:
        print(f"  > Error entering password: {error}")

    try:
        signin_btn = wait.until(EC.element_to_be_clickable((By.ID, "signInSubmit")))
        signin_btn.click()
        print("  > Clicked 'Sign In'")
        time.sleep(5)
    except Exception as error:
        print(f"  > Error clicking Sign In: {error}")

    return True


def wait_for_product_markers(driver: webdriver.Chrome, timeout: int = 10) -> bool:
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
    except Exception:
        return False

    html = driver.page_source
    if is_captcha_or_block_page(html):
        return False

    marker_candidates = (
        "acrPopover",
        "acrCustomerReviewText",
        "averageCustomerReviews",
        "histogramTable",
        "rating-out-of-text",
    )
    return any(marker in html for marker in marker_candidates)


def scrape_ratings_first_page(
    driver: webdriver.Chrome,
    url: str,
    email: str,
    password: str,
    is_first_book: bool = True,
    skip_login: bool = False,
    max_retries: int = MAX_RETRIES,
) -> Dict[str, Any]:
    empty_result = {
        "overall_rating": None,
        "total_ratings": None,
        "star_wise_ratings": {
            "5_star": None,
            "4_star": None,
            "3_star": None,
            "2_star": None,
            "1_star": None,
        },
    }

    driver.get(url)

    if is_first_book and not skip_login:
        login_succeeded = False
        for attempt in range(1, max_retries + 1):
            try:
                perform_amazon_login(driver, email, password)
                if wait_for_product_markers(driver, timeout=12):
                    print("    - Login successful, session established.")
                    login_succeeded = True
                    break
            except Exception:
                pass

            if attempt < max_retries:
                backoff_sleep(attempt)

        if not login_succeeded:
            print("    - Login failed after retries; continuing without login for this book.")
    else:
        if not wait_for_product_markers(driver, timeout=12):
            print("    - Page load timeout or blocked page.")

    for attempt in range(1, max_retries + 1):
        print(f"    - Extract attempt {attempt}/{max_retries}...")
        time.sleep(random.uniform(10, 18))

        html = driver.page_source
        if is_captcha_or_block_page(html):
            if attempt == max_retries:
                print("      > CAPTCHA/block page detected.")
                return empty_result
            backoff_sleep(attempt)
            driver.get(url)
            continue

        extracted = extract_total_and_star_wise_ratings(html)
        has_star_data = any(v is not None for v in extracted["star_wise_ratings"].values())
        if extracted["overall_rating"] is not None or extracted["total_ratings"] is not None or has_star_data:
            return extracted

        if attempt < max_retries:
            backoff_sleep(attempt)
            driver.get(url)

    print("      > No rating markers found on page.")
    return empty_result


def fetch_valid_amazon_ratings(
    input_path: str,
    output_path: str,
    skip_login: bool,
    book_key: Optional[str] = None,
) -> None:
    books = load_book_urls(input_path)
    if book_key is not None:
        books = [(k, u) for (k, u) in books if k == book_key]
        if not books:
            raise KeyError(f"Book key not found in input: {book_key}")

    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    results: Dict[str, Any] = {}
    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as handle:
                existing = json.load(handle)
            if isinstance(existing, dict):
                results = existing
                print(f"Loaded {len(results)} existing books from {output_path}")
        except Exception as error:
            print(f"Warning: Could not load existing output file: {error}")

    print(f"Loaded {len(books)} books from input file.")

    skipped_count = 0
    processed_count = 0

    try:
        for index, (filename, original_url) in enumerate(books):
            if filename in results and isinstance(results.get(filename), dict):
                if (
                    results[filename].get("overall_rating") is not None
                    or results[filename].get("total_ratings") is not None
                    or any((results[filename].get("star_wise_ratings") or {}).values())
                ):
                    print(f"Skipping: {filename} (already processed)")
                    skipped_count += 1
                    continue

            print(f"Processing: {filename}")
            is_first = processed_count == 0

            ratings_data = scrape_ratings_first_page(
                driver,
                original_url,
                AMAZON_EMAIL,
                AMAZON_PASSWORD,
                is_first,
                skip_login,
                MAX_RETRIES,
            )

            results[filename] = ratings_data
            processed_count += 1

            with open(output_path, "w", encoding="utf-8") as handle:
                json.dump(results, handle, indent=2, ensure_ascii=False)

            if index < len(books) - 1:
                time.sleep(random.uniform(12, 20))

        print(f"\nSummary: Processed {processed_count} new books, Skipped {skipped_count} existing books.")
    finally:
        driver.quit()

    found_total = sum(1 for item in results.values() if item.get("total_ratings") is not None)
    found_overall = sum(1 for item in results.values() if item.get("overall_rating") is not None)
    print(f"Done. rows={len(results)} overall_found={found_overall} total_found={found_total}")
    print(f"Saved: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Amazon first-page ratings using Selenium flow matching main.py"
    )
    parser.add_argument(
        "--input",
        "-i",
        default=INPUT_FILE,
        help="Input JSON mapping book key to Amazon URL",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=OUTPUT_FILE,
        help="Output JSON file",
    )
    parser.add_argument(
        "--book-key",
        default=None,
        help="Run only for a single book key from input JSON",
    )
    parser.add_argument(
        "--skip-login",
        action="store_true",
        help="Skip login flow on script start",
    )
    args = parser.parse_args()

    fetch_valid_amazon_ratings(
        input_path=args.input,
        output_path=args.output,
        skip_login=args.skip_login,
        book_key=args.book_key,
    )


if __name__ == "__main__":
    main()
