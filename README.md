# books_and_ai

Amazon scraping scripts.

## Folder layout

- amazon/
	- find_amazon_urls.py
	- fetch_amazon_reviews.py
	- fetch_amazon_ratings.py

## Requirements

- Python 3.10+
- Google Chrome installed
- Git
- A valid Amazon account for the login-based scripts

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

- metadata.json
- amazon_urls.json
- amazon_validation.json
- amazon_mismatches.json
- amazon_reviews.json
- amazon_ratings.json

## 1) Find Amazon URLs

Script: amazon/find_amazon_urls.py

Input:

- metadata.json

Outputs:

- amazon_urls.json
- amazon_mismatches.json
- amazon_validation.json

Run:

- python find_amazon_urls.py

## 2) Fetch Amazon reviews

Script: amazon/fetch_amazon_reviews.py

Input:

- amazon_urls.json

Output:

- amazon_reviews.json

Run:

- python fetch_amazon_reviews.py --skip-login

## 3) Fetch Amazon ratings

Script: amazon/fetch_amazon_ratings.py

Input:

- amazon_urls.json

Output:

- amazon_ratings.json

Run:

- python fetch_amazon_ratings.py --skip-login

## Notes

- The scripts resume from existing output files when possible.
- Keep all input/output files inside the amazon folder for simplicity.

