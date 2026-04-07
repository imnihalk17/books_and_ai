import json
import argparse
import os
import time
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

# Session with user agent
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
})


def load_metadata(path):
    """Load metadata JSON."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_book_name(key):
    """Extract book name from filename key (remove .epub or .txt extension)."""
    name = key
    if name.endswith('.epub'):
        name = name[:-5]
    elif name.endswith('.txt'):
        name = name[:-4]
    return name


def get_star_ratings_breakdown(soup):
    """
    Extract rating distribution by star (1-5 stars).
    Returns dict like {"5_star": 100, "4_star": 50, ...} or all None if not found.
    """
    breakdown = {"5_star": None, "4_star": None, "3_star": None, "2_star": None, "1_star": None}
    
    try:
        # Try to find rating distribution bars/elements with data-testid
        for i in range(5, 0, -1):
            elem = soup.find(attrs={'data-testid': f'{i}Star'})
            if elem:
                text = elem.get_text(strip=True)
                match = re.search(r'([\d,]+)', text)
                if match:
                    breakdown[f'{i}_star'] = int(match.group(1).replace(',', ''))
        
        # Fallback: search page text for patterns like "5 stars (1,234)" or "5 stars 1,234"
        page_text = soup.get_text()
        
        for star_num in range(5, 0, -1):
            if breakdown[f'{star_num}_star'] is None:
                # Try patterns: "X stars (###)", "X stars ###", "X star (###)"
                patterns = [
                    rf'{star_num}\s*stars?\s*\(?([\d,]+)\)?',
                    rf'{star_num}\s*\(([\d,]+)\s*ratings?\)',
                ]
                for pattern in patterns:
                    match = re.search(pattern, page_text, re.I)
                    if match:
                        breakdown[f'{star_num}_star'] = int(match.group(1).replace(',', ''))
                        break
    except Exception:
        pass
    
    return breakdown


def get_ratings_and_reviews(url, retries=3, backoff=2):
    """
    Visit a Goodreads URL and extract:
    - Overall rating (average, e.g., 4.25)
    - Total ratings count
    - Total reviews count
    - Star ratings breakdown (1-5 stars)
    
    Returns dict with overall_rating, ratings, reviews, and star_breakdown keys.
    """
    result = {"overall_rating": None, "ratings": None, "reviews": None, "star_breakdown": {}}
    
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=10)
            resp.raise_for_status()
            break
        except Exception as e:
            if attempt == retries:
                print(f"    ✗ Failed to fetch after {retries} attempts: {e}")
                return result
            print(f"    ⟳ Retry {attempt}/{retries} in {backoff}s...")
            time.sleep(backoff)
    
    try:
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Extract star breakdown first
        result['star_breakdown'] = get_star_ratings_breakdown(soup)
        
        # Extract overall rating (average score like 4.25)
        # Try multiple patterns in order of reliability
        
        # Pattern 1: data-testid="ratingValue"
        rating_elem = soup.find(attrs={'data-testid': 'ratingValue'})
        if rating_elem:
            rating_text = rating_elem.get_text(strip=True)
            match = re.search(r'([\d.]+)', rating_text)
            if match:
                result['overall_rating'] = float(match.group(1))
        
        # Pattern 2: RatingStatistics class or similar
        if result['overall_rating'] is None:
            rating_elem = soup.find(class_=re.compile(r'RatingStatistics', re.I))
            if rating_elem:
                rating_text = rating_elem.get_text(strip=True)
                match = re.search(r'([\d.]+)', rating_text)
                if match:
                    result['overall_rating'] = float(match.group(1))
        
        # Pattern 3: Look in meta tags (structured data)
        if result['overall_rating'] is None:
            meta_rating = soup.find('meta', attrs={'property': 'books:rating:value'})
            if not meta_rating:
                meta_rating = soup.find('meta', attrs={'itemprop': 'ratingValue'})
            if meta_rating and meta_rating.get('content'):
                try:
                    result['overall_rating'] = float(meta_rating['content'])
                except:
                    pass
        
        # Pattern 4: aria-label with rating
        if result['overall_rating'] is None:
            for elem in soup.find_all(attrs={'aria-label': True}):
                aria_text = elem.get('aria-label', '').lower()
                if 'rating' in aria_text or 'stars' in aria_text:
                    match = re.search(r'([\d.]+)\s*(?:out of|stars)', aria_text, re.I)
                    if match:
                        result['overall_rating'] = float(match.group(1))
                        break
        
        # Pattern 5: Search page text for "X out of 5" patterns
        if result['overall_rating'] is None:
            page_text = soup.get_text()
            match = re.search(r'([\d.]+)\s*out of\s*5', page_text, re.I)
            if match:
                result['overall_rating'] = float(match.group(1))
        
        # Pattern 6: Look for standalone decimal number near "rating" or "average"
        if result['overall_rating'] is None:
            for elem in soup.find_all(['div', 'span']):
                text = elem.get_text(strip=True)
                # Match patterns like "4.25" or "Rating: 4.25" or "Average rating 4.25"
                match = re.search(r'(?:rating|average)?\s*:?\s*([1-5]\.[\d]+)', text, re.I)
                if match:
                    result['overall_rating'] = float(match.group(1))
                    break
        
        # Extract total ratings count
        ratings_elem = soup.find('span', {'data-testid': 'ratingsCount'})
        if ratings_elem:
            text = ratings_elem.get_text(strip=True)
            match = re.search(r'([\d,]+)', text)
            if match:
                result['ratings'] = int(match.group(1).replace(',', ''))
        
        # Extract total reviews count
        reviews_elem = soup.find('span', {'data-testid': 'reviewsCount'})
        if reviews_elem:
            text = reviews_elem.get_text(strip=True)
            match = re.search(r'([\d,]+)', text)
            if match:
                result['reviews'] = int(match.group(1).replace(',', ''))
        
        # Fallback patterns for ratings and reviews
        page_text = soup.get_text()
        
        if result['ratings'] is None:
            # Look for "X ratings" pattern (ensure not part of star breakdown)
            match = re.search(r'([\d,]+)\s+ratings?(?!.*stars?)', page_text, re.I)
            if match:
                result['ratings'] = int(match.group(1).replace(',', ''))
        
        if result['reviews'] is None:
            # Look for "X reviews" pattern
            match = re.search(r'([\d,]+)\s+reviews?', page_text, re.I)
            if match:
                result['reviews'] = int(match.group(1).replace(',', ''))
        
        return result
    
    except Exception as e:
        print(f"    ✗ Error parsing page: {e}")
        return result


def fetch_ratings_and_reviews(metadata_path, output_path, delay_seconds=2):
    """
    Load metadata, visit each URL, extract ratings/reviews, and save output.
    
    metadata_path: path to mdata.json (dict mapping book_name -> URL)
    output_path: path to write output JSON
    """
    metadata = load_metadata(metadata_path)
    
    # Load existing results if output file exists (to support resuming)
    results = {}
    if os.path.isfile(output_path):
        try:
            with open(output_path, 'r', encoding='utf-8') as f:
                results = json.load(f)
            print(f"Loaded {len(results)} existing results from {output_path}")
        except Exception:
            print(f"Could not load existing results from {output_path}, starting fresh")
    
    print(f"Loaded {len(metadata)} books from {metadata_path}\n")
    
    for idx, (book_key, url) in enumerate(metadata.items(), 1):
        book_name = extract_book_name(book_key)
        
        # Skip if already processed
        if book_name in results:
            print(f"[{idx}/{len(metadata)}] {book_name} - already processed, skipping")
            continue
        
        print(f"[{idx}/{len(metadata)}] {book_name}")
        print(f"   URL: {url}")
        
        stats = get_ratings_and_reviews(url)
        results[book_name] = {
            "url": url,
            "overall_rating": stats['overall_rating'],
            "total_ratings": stats['ratings'],
            "total_reviews": stats['reviews'],
            "rating_breakdown": stats.get('star_breakdown', {})
        }
        
        print(f"   ✓ Overall: {stats['overall_rating']}, Ratings: {stats['ratings']}, Reviews: {stats['reviews']}")
        if stats.get('star_breakdown'):
            bd = stats['star_breakdown']
            print(f"     5★: {bd['5_star']}, 4★: {bd['4_star']}, 3★: {bd['3_star']}, 2★: {bd['2_star']}, 1★: {bd['1_star']}")
        print()
        
        # Write results incrementally after each book
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=4)
            print(f"   → Saved to {output_path} ({len(results)} books total)\n")
        except Exception as e:
            print(f"   ✗ Failed to save results: {e}\n")
        
        # Delay between requests to be polite
        if idx < len(metadata):
            time.sleep(delay_seconds)
    
    # Final save (in case the loop was interrupted)
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=4)
        print(f"\nFinal results saved to: {output_path}")
    except Exception as e:
        print(f"\nFailed to save final results: {e}")
    
    # Summary
    found_overall = sum(1 for v in results.values() if v['overall_rating'] is not None)
    found_ratings = sum(1 for v in results.values() if v['total_ratings'] is not None)
    found_reviews = sum(1 for v in results.values() if v['total_reviews'] is not None)
    print(f"Summary: {found_overall}/{len(results)} with overall rating, {found_ratings}/{len(results)} with total ratings, {found_reviews}/{len(results)} with reviews")


def main():
    parser = argparse.ArgumentParser(
        description='Fetch ratings and reviews count from Goodreads URLs in metadata file'
    )
    parser.add_argument(
        '--input', '-i',
        default='goodreads_urls.json',
        help='Path to metadata JSON file (mapping of book names to URLs)'
    )
    parser.add_argument(
        '--output', '-o',
        default='goodreads_ratings.json',
        help='Path to output JSON file with results'
    )
    parser.add_argument(
        '--delay', '-d',
        type=float,
        default=2,
        help='Delay in seconds between URL requests (default: 2)'
    )
    
    args = parser.parse_args()
    
    try:
        fetch_ratings_and_reviews(args.input, args.output, args.delay)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        raise SystemExit(1)
    except Exception as e:
        print(f"Error: {e}")
        raise SystemExit(1)


if __name__ == '__main__':
    main()
