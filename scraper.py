"""Fetch a web page and export its title, description, and links."""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.exceptions import RequestException
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_DIR = Path(__file__).resolve().parent
CSV_PATH = PROJECT_DIR / "output.csv"
JSON_PATH = PROJECT_DIR / "output.json"
REPORT_PATH = PROJECT_DIR / "report.txt"
URL = "https://example.com"


def create_session() -> requests.Session:
    """Create a session that retries transient GET failures."""
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; JobListingResearchBot/1.0)"
    })
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def fetch_page(
    url: str, session: requests.Session, timeout: float = 15
) -> tuple[str, int, str] | None:
    """Fetch page HTML, returning None when the request fails."""
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        return response.text, response.status_code, response.url
    except RequestException as error:
        print(f"Request failed: {error}", file=sys.stderr)
        return None


def parse_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def extract_jobs(soup: BeautifulSoup) -> list[dict]:
    """Extract job cards matching the site's job/title/company/location classes."""
    jobs = []
    for card in soup.select(".job"):
        title = card.select_one(".title")
        company = card.select_one(".company")
        location = card.select_one(".location")
        link = card.select_one("a")
        href = link.get("href", "").strip() if link else ""
        jobs.append({
            "title": title.get_text(" ", strip=True) if title else "",
            "company": company.get_text(" ", strip=True) if company else "",
            "location": location.get_text(" ", strip=True) if location else "",
            "url": href,
        })
    return jobs


def clean_jobs(jobs: list[dict]) -> list[dict]:
    """Trim whitespace from extracted job fields."""
    cleaned = []
    for job in jobs:
        cleaned.append({
            "title": job["title"].strip(),
            "company": job["company"].strip(),
            "location": job["location"].strip(),
            "url": job["url"].strip(),
        })
    return cleaned


def scrape_page(
    url: str, timeout: float, session: requests.Session
) -> dict | None:
    """Fetch a page and return its metadata and extracted links."""
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("URL must start with http:// or https://")

    started = time.perf_counter()
    page = fetch_page(url, session, timeout)
    if page is None:
        return None
    page_html, status_code, final_url = page
    soup = parse_html(page_html)
    jobs = clean_jobs(extract_jobs(soup))
    for job in jobs:
        if job["url"]:
            job["url"] = urljoin(final_url, job["url"])

    title_tag = soup.find("title")
    description_tag = soup.find("meta", attrs={"name": "description"})
    links = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if href:
            links.append({
                "text": anchor.get_text(" ", strip=True),
                "url": urljoin(final_url, href),
            })

    return {
        "url": final_url,
        "status_code": status_code,
        "page_title": title_tag.get_text(strip=True) if title_tag else "",
        "meta_description": (
            description_tag.get("content", "").strip() if description_tag else ""
        ),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "jobs": jobs,
        "links": links,
    }


def rate_limit(seconds: float = 2) -> None:
    """Wait before making the next page request."""
    time.sleep(seconds)


def scrape_pages(urls: list[str], timeout: float, delay: float) -> list[dict]:
    """Scrape URLs in order, waiting between requests."""
    results = []
    with create_session() as session:
        for index, url in enumerate(urls):
            if index:
                rate_limit(delay)
            result = scrape_page(url, timeout, session)
            if result is not None:
                results.append(result)
    return results


def create_dataframe(jobs: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(jobs)


def save_csv(df: pd.DataFrame, filename: str | Path = CSV_PATH) -> None:
    df.to_csv(filename, index=False, encoding="utf-8")


def save_json(df: pd.DataFrame, filename: str | Path = JSON_PATH) -> None:
    df.to_json(
        filename,
        orient="records",
        indent=4,
        force_ascii=False,
    )


def generate_report(
    df: pd.DataFrame, filename: str | Path = REPORT_PATH
) -> None:
    total_records = len(df)
    missing_values = df.isnull().sum().sum()
    report = f"""
Web Scraping Report
===================

Total records: {total_records}
Total missing values: {missing_values}

Columns:
{", ".join(df.columns)}
"""
    Path(filename).write_text(report, encoding="utf-8")


def write_outputs(results: list[dict]) -> None:
    """Write job records to CSV and JSON, plus a report."""
    job_rows = [
        {"page_url": result["url"], **job}
        for result in results
        for job in result["jobs"]
    ]
    dataframe = create_dataframe(job_rows).reindex(
        columns=("page_url", "title", "company", "location", "url")
    )
    print(dataframe)
    save_csv(dataframe)
    save_json(dataframe)
    generate_report(dataframe)

    report_lines = ["Page summaries", "=============="]
    for result in results:
        report_lines.extend([
            f"URL: {result['url']}",
            f"HTTP status: {result['status_code']}",
            f"Page title: {result['page_title']}",
            f"Jobs found: {len(result['jobs'])}",
            f"Links found: {len(result['links'])}",
            f"Elapsed seconds: {result['elapsed_seconds']}",
            f"Scraped at: {result['scraped_at']}",
            "",
        ])
    with REPORT_PATH.open("a", encoding="utf-8") as report_file:
        report_file.write("\n" + "\n".join(report_lines))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape job listings from one or more web pages."
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="HTTP or HTTPS URLs to scrape (defaults to https://example.com)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15,
        help="request timeout in seconds (default: 15)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2,
        help="seconds to wait between URLs (default: 2)",
    )
    args = parser.parse_args()

    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.delay < 0:
        parser.error("--delay cannot be negative")

    urls = args.urls or [URL]
    print("Starting scraper...")
    try:
        results = scrape_pages(urls, args.timeout, args.delay)
    except (RequestException, ValueError) as error:
        print(f"Scrape failed: {error}", file=sys.stderr)
        return 1

    if not results:
        print("Could not fetch webpage.", file=sys.stderr)
        return 1

    print("Page downloaded successfully.")
    total_jobs = sum(len(result["jobs"]) for result in results)
    print(f"Extracted {total_jobs} records.")
    write_outputs(results)
    print("Scraping completed.")
    print("Files created:")
    print(f"- {CSV_PATH.name}")
    print(f"- {JSON_PATH.name}")
    print(f"- {REPORT_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
