# books_and_ai

Book metadata and review scraping workflows for two sites:

- Amazon
- Goodreads

The repo is organized into two folders:

- amazon/ — Amazon URL discovery, validation, and review scraping
- goodreads/ — Goodreads URL discovery, ratings, and review scraping

## Requirements

- Python 3.10+
- Google Chrome installed
- Git
- For Amazon review scraping: a valid Amazon account
- For Goodreads review scraping: Selenium and ChromeDriver will be installed automatically by the scripts if needed

Recommended Python packages:

- requests
- beautifulsoup4
- lxml
- selenium
- webdriver-manager
- playwright

If you use the Amazon original flow script, install Playwright browsers too:

- python -m playwright install

## Important note

Some scripts contain hardcoded login credentials for testing. Replace them with your own credentials before running, and do not commit real secrets to GitHub.

## Folder layout

### amazon/

- find_amazon_urls.py
- fetch_amazon_reviews.py

### goodreads/

- find_goodreads_urls.py
- fetch_goodreads_ratings.py
- fetch_goodreads_reviews.py

## Amazon workflow

Run these from inside the amazon folder, or make sure the input files are present in that folder.

### 1) Find Amazon URLs

Script: find_amazon_urls.py

Input:

- metadata_new.json

Outputs:

- valid_amazon_urls_metadata_new.json
- amazon_mismatches_metadata_new.json
- metadata_amazon_validation_metadata_new.json

Typical command:

- python find_amazon_urls.py

If you want the original ASIN-first flow instead, use:

- find_amazon_urls_metadata_new_original_flow.py

### 2) Fetch Amazon reviews

Script: fetch_amazon_reviews.py

Input:

- valid_amazon_urls_metadata_new.json

Output:

- output.json

Typical command:

- python fetch_amazon_reviews.py --skip-login

This script can resume from an existing output file and skips books already processed.

## Goodreads workflow

Run these from inside the goodreads folder, or make sure the input files are present in that folder.

### 1) Find Goodreads URLs

Script: find_goodreads_urls.py

Input:

- metadata_new.json

Outputs:

- valid_urls_metadata_new1.json
- not_found_urls_metadata_new1.json

Typical command:

- python find_goodreads_urls.py

### 2) Fetch Goodreads ratings and review counts

Script: fetch_goodreads_ratings.py

Input:

- mdata.json or another JSON mapping book keys to Goodreads URLs

Output:

- ratings_and_reviews.json

Typical command:

- python fetch_goodreads_ratings.py -i mdata.json -o ratings_and_reviews.json

### 3) Fetch Goodreads reviews

Script: fetch_goodreads_reviews.py

Input:

- A JSON file containing Goodreads URLs or a mapping of filename to URL

Output:

- reviews.json

Typical command:

- python fetch_goodreads_reviews.py -i valid_urls_metadata_new1.json -o reviews.json

## Resume behavior

Several scripts support resuming from existing output files and will skip already processed items automatically.

## Suggested run order

1. Run the URL finder for the site you want.
2. Validate or filter the URL output if needed.
3. Run the ratings/reviews scraper using the valid URL file.

## GitHub repo

This project is available at:

- https://github.com/imnihalk17/books_and_ai

