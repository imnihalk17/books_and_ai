# books_and_ai

Two local scraping folders:

- amazon/
- goodreads/

## Requirements

- Python 3.10+
- Google Chrome installed
- Git
- Selenium-based scripts use ChromeDriver via webdriver-manager

Recommended Python packages:

- requests
- beautifulsoup4
- lxml
- selenium
- webdriver-manager
- playwright

If needed, install Playwright browsers:

- python -m playwright install

## Important note

Replace any hardcoded test credentials before running the scripts.

## Simple file names used by the scripts

### amazon/

- metadata.json
- amazon_urls.json
- amazon_validation.json
- amazon_mismatches.json
- amazon_reviews.json
- amazon_ratings.json

### goodreads/

- metadata.json
- goodreads_urls.json
- goodreads_not_found.json
- goodreads_ratings.json
- goodreads_reviews.json

## amazon/

### 1) Find Amazon URLs

Script: amazon/find_amazon_urls.py

Input:

- metadata.json

Outputs:

- amazon_urls.json
- amazon_mismatches.json
- amazon_validation.json

Run from inside amazon/:

- python find_amazon_urls.py

### 2) Fetch Amazon reviews

Script: amazon/fetch_amazon_reviews.py

Input:

- amazon_urls.json

Output:

- amazon_reviews.json

Run from inside amazon/:

- python fetch_amazon_reviews.py

This script requires an Amazon login. Enter your own Amazon email and password in the script before running.

### 3) Fetch Amazon ratings

Script: amazon/fetch_amazon_ratings.py

Input:

- amazon_urls.json

Output:

- amazon_ratings.json

Run from inside amazon/:

- python fetch_amazon_ratings.py

This script requires an Amazon login. Enter your own Amazon email and password in the script before running.

## goodreads/

### 1) Find Goodreads URLs

Script: goodreads/find_goodreads_urls.py

Input:

- metadata.json

Outputs:

- goodreads_urls.json
- goodreads_not_found.json

Run from inside goodreads/:

- python find_goodreads_urls.py

### 2) Fetch Goodreads ratings and review counts

Script: goodreads/fetch_goodreads_ratings.py

Input:

- goodreads_urls.json

Output:

- goodreads_ratings.json

Run from inside goodreads/:

- python fetch_goodreads_ratings.py

### 3) Fetch Goodreads reviews

Script: goodreads/fetch_goodreads_reviews.py

Input:

- goodreads_urls.json

Output:

- goodreads_reviews.json

Run from inside goodreads/:

- python fetch_goodreads_reviews.py

## Notes

- The scripts resume from existing output files when possible.
- Keep each script’s inputs and outputs inside its own folder for simplicity.

