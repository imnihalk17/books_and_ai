import json
import os
import time
import random
import argparse
from typing import List, Tuple, Dict, Any
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- Configuration ---
INPUT_FILE = 'amazon_urls.json'
OUTPUT_FILE = 'amazon_reviews.json'
AMAZON_EMAIL = "PUT_YOUR_AMAZON_EMAIL_HERE"
AMAZON_PASSWORD = "PUT_YOUR_AMAZON_PASSWORD_HERE"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0

def get_review_url(product_url):
    if "/dp/" in product_url:
        return product_url.replace("/dp/", "/product-reviews/")
    return product_url


def backoff_sleep(attempt: int, base: float = RETRY_BASE_DELAY):
    time.sleep(base * attempt + random.uniform(0.5, 1.5))


def deduplicate_reviews(reviews: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only unique reviews while preserving original order."""
    unique_reviews: List[Dict[str, Any]] = []
    seen = set()

    for review in reviews:
        key = (
            str(review.get("author", "")).strip(),
            str(review.get("title", "")).strip(),
            str(review.get("body", "")).strip(),
            str(review.get("rating", "")).strip(),
            str(review.get("date", "")).strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_reviews.append(review)

    return unique_reviews


def load_book_urls(path: str) -> List[Tuple[str, str]]:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    items: List[Tuple[str, str]] = []

    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, str):
                url = v
            elif isinstance(v, dict):
                url = v.get('amazon_url') or v.get('url') or v.get('review_url')
            else:
                continue
            if url:
                items.append((k, url))
    elif isinstance(data, list):
        for entry in data:
            if not isinstance(entry, dict):
                continue
            fname = entry.get('epub_filename') or entry.get('filename') or entry.get('name')
            url = entry.get('amazon_url') or entry.get('url') or entry.get('review_url')
            if fname and url:
                items.append((fname, url))

    return items


def perform_amazon_login(driver, email, password):
    """
    Executes the specific login flow:
    1. Clicks 'Continue Shopping' (if present)
    2. Enters Email
    3. Clicks 'Continue'
    4. Enters Password
    5. Clicks 'Sign In'
    """
    wait = WebDriverWait(driver, 10)

    print("  > Starting login flow...")

    # --- Step 1: Click 'Continue shopping' ---
    try:
        continue_shopping_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[@alt='Continue shopping']")
        ))
        continue_shopping_btn.click()
        print("  > Clicked 'Continue shopping'")
    except:
        print("  > 'Continue shopping' button not found, skipping step.")

    # --- Step 2: Input Email ---
    try:
        email_field = wait.until(EC.visibility_of_element_located((By.ID, "ap_email_login")))
    except:
        email_field = wait.until(EC.visibility_of_element_located((By.NAME, "email")))
    
    try:
        email_field.clear()
        email_field.send_keys(email)
        print("  > Entered email")
    except Exception as e:
        print(f"  > Error entering email: {e}")

    # --- Step 3: Click 'Continue' button ---
    try:
        continue_btn = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "input[aria-labelledby='continue-announce']")
        ))
        continue_btn.click()
        print("  > Clicked 'Continue'")
    except Exception as e:
        print(f"  > Error clicking Continue: {e}")

    # --- Step 4: Input Password ---
    try:
        password_field = wait.until(EC.visibility_of_element_located((By.ID, "ap_password")))
        password_field.clear()
        password_field.send_keys(password)
        print("  > Entered password")
    except Exception as e:
        print(f"  > Error entering password: {e}")

    # --- Step 5: Click 'Sign In' ---
    try:
        signin_btn = wait.until(EC.element_to_be_clickable((By.ID, "signInSubmit")))
        signin_btn.click()
        print("  > Clicked 'Sign In'")
        time.sleep(5)
    except Exception as e:
        print(f"  > Error clicking Sign In: {e}")
    return True


def scrape_reviews_recursive(driver, url, email, password, is_first_book: bool = True, skip_login: bool = False, max_retries: int = MAX_RETRIES):
    driver.get(url)

    # Only login on the first book; subsequent books should stay logged in
    if is_first_book and not skip_login:
        for attempt in range(1, max_retries + 1):
            try:
                perform_amazon_login(driver, email, password)
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "li[data-hook='review']")))
                print("    - Login successful, session established.")
                break
            except Exception:
                if attempt == max_retries:
                    print("    - Failed to login after retries.")
                    return []
                backoff_sleep(attempt)
    else:
        # For subsequent books, just wait for page to load
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "li[data-hook='review']")))
        except Exception:
            print("    - Page load timeout.")

    all_reviews = []
    page_count = 1

    while True:
        print(f"    - Processing Page {page_count}...")
        time.sleep(random.uniform(10, 18))
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        review_elements = soup.find_all('li', {'data-hook': 'review'})

        for item in review_elements:
            try:
                author_tag = item.find('span', class_='a-profile-name')
                author = author_tag.get_text(strip=True) if author_tag else "Anonymous"
                title_tag = item.find(attrs={'data-hook': 'review-title'})
                title = "No Title"
                if title_tag:
                    spans = title_tag.find_all('span')
                    title = (spans[-1].get_text(strip=True) if spans else title_tag.get_text(strip=True))
                body_tag = item.find('span', {'data-hook': 'review-body'})
                body = ""
                if body_tag:
                    div = body_tag.find('div', {'data-hook': 'review-collapsed'})
                    body = div.get_text(separator='\n', strip=True) if div else body_tag.get_text(strip=True)
                
                # Extract rating (stars) - Debug version
                rating = None
                # Strategy 1: data-hook='review-star-rating'
                rating_tag = item.find('span', {'data-hook': 'review-star-rating'})
                if rating_tag:
                    rating_text = rating_tag.get_text(strip=True)
                    try:
                        rating = float(rating_text.split()[0])
                    except (ValueError, IndexError):
                        pass
                
                # Strategy 2: Look for aria-label with star pattern
                if not rating_tag:
                    for span in item.find_all('span'):
                        aria_label = span.get('aria-label', '')
                        if 'out of 5 stars' in aria_label:
                            try:
                                rating = float(aria_label.split()[0])
                                break
                            except (ValueError, IndexError):
                                pass
                
                # Strategy 3: Find i tag with star icon
                if not rating:
                    star_icon = item.find('i', class_=lambda x: x and 'a-icon' in x and 'star' in x)
                    if star_icon:
                        parent = star_icon.find_parent(['span', 'div'])
                        if parent:
                            rating_text = parent.get_text(strip=True)
                            try:
                                rating = float(rating_text.split()[0])
                            except (ValueError, IndexError):
                                pass
                
                # Extract date
                date = None
                date_tag = item.find('span', {'data-hook': 'review-date'})
                if date_tag:
                    date = date_tag.get_text(strip=True)
                
                all_reviews.append({
                    "author": author,
                    "title": title,
                    "body": body,
                    "rating": rating,
                    "date": date
                })
            except Exception:
                continue

        print(f"      > Collected {len(review_elements)} reviews on page {page_count}.")

        try:
            next_clicked = False
            for attempt in range(1, max_retries + 1):
                try:
                    # Look for "Show 10 more reviews" button by text content
                    # Use XPath to find the link with this text
                    next_button = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, "//a[contains(text(), 'Show') and contains(text(), 'more') and contains(text(), 'reviews')]"))
                    )
                    
                    # Scroll it into view
                    driver.execute_script("arguments[0].scrollIntoView();", next_button)
                    time.sleep(2)
                    
                    # Wait for it to be clickable
                    WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Show') and contains(text(), 'more') and contains(text(), 'reviews')]")))
                    
                    next_button.click()
                    next_clicked = True
                    time.sleep(3)  # Wait for new reviews to load via AJAX
                    break
                except Exception:
                    if attempt == max_retries:
                        print("      > Could not find 'Show more reviews' button.")
                        break
                    print(f"      > Attempt {attempt} failed, retrying...")
                    backoff_sleep(attempt)

            if not next_clicked:
                print("      > No next page found or click failed. Ending book.")
                break
            page_count += 1
        except Exception:
            print("      > Exception in pagination loop.")
            break

    return all_reviews

def main():
    # CLI args
    parser = argparse.ArgumentParser(description="Amazon reviews scraper")
    parser.add_argument("--skip-login", action="store_true", help="Skip login flow on script start")
    args = parser.parse_args()
    # 1. Setup Chrome
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled") 
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    # Load existing output file to skip already-processed books
    final_data = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                final_data = json.load(f)
            print(f"Loaded {len(final_data)} existing books from {OUTPUT_FILE}")
        except Exception as e:
            print(f"Warning: Could not load existing output file: {e}")

    try:
        books = load_book_urls(INPUT_FILE)
        print(f"Loaded {len(books)} books from input file.")
        
        skipped_count = 0
        processed_count = 0

        for idx, (filename, original_url) in enumerate(books):
            # Skip if already processed
            if filename in final_data and final_data.get(filename, {}).get("reviews"):
                print(f"Skipping: {filename} (already processed)")
                skipped_count += 1
                continue
            
            print(f"Processing: {filename}")
            target_url = get_review_url(original_url)
            is_first = (processed_count == 0)  # First new book to process in this run
            
            reviews = scrape_reviews_recursive(
                driver,
                target_url,
                AMAZON_EMAIL,
                AMAZON_PASSWORD,
                is_first,
                args.skip_login,
                MAX_RETRIES,
            )

            unique_reviews = deduplicate_reviews(reviews)
            duplicates_removed = len(reviews) - len(unique_reviews)
            if duplicates_removed > 0:
                print(f"Removed {duplicates_removed} duplicate reviews for {filename}.")
            
            final_data[filename] = {
                "original_url": original_url,
                "total_reviews": len(unique_reviews),
                "reviews": unique_reviews
            }
            processed_count += 1
            
            # Save progressively (optional but safe)
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(final_data, f, indent=4, ensure_ascii=False)

            time.sleep(random.uniform(12, 20))
        
        print(f"\nSummary: Processed {processed_count} new books, Skipped {skipped_count} existing books.")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        driver.quit()

    print("Done.")


if __name__ == "__main__":
    main()
