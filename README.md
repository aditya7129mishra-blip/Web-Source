# Web Scraper

A command-line scraper that fetches HTTP or HTTPS pages, extracts job cards, page metadata, and links, and writes the results to CSV, JSON, and a text report.

## Setup

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

## Run

```powershell
py scraper.py
```

Without arguments, the scraper targets `https://example.com`. You can also pass one or more URLs; it waits two seconds between URLs by default:

```powershell
py scraper.py https://example.com https://www.iana.org --delay 2
```

Job cards are recognized using `.job` containers with `.title`, `.company`, and `.location` descendants; the first linked URL in each card is exported as `url`. CSV and JSON contain job records; the JSON preserves Unicode text. The text report includes record and missing-value counts, column names, and page summaries.

Use `--timeout` to change the per-request timeout. The scraper retries transient failures up to three times with exponential backoff. It creates or replaces `output.csv`, `output.json`, and `report.txt` in this folder.

Only scrape pages you are permitted to access. Follow the site's terms, robots.txt guidance, and applicable rate limits.
