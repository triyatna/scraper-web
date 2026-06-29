# Web Scraper

This is a complete, production-grade CLI web scraper written in Python. It recursively crawls domain-internal pages, downloads all assets (HTML, CSS, JS, images, responsive image srcsets, fonts), translates absolute paths to relative ones for perfect offline usability, and supports advanced modern crawler features.

All scrape results are saved in the `project/` directory inside the working directory by default.

## Advanced Features Implemented

1. **JavaScript Rendering by Default**: Uses Playwright (Chromium) by default to render highly dynamic Single Page Applications (SPAs) like React, Vue, Angular, etc. Can be bypassed/disabled using `--no-js`.
2. **Same-Path Restriction by Default**: Automatically restricts perayapan to the directory of the target URL to keep the crawl in-scope. Can be disabled with `--no-same-path`.
3. **Crawl Resume Session**: Automatically stores current crawl state (`visited` and `to_visit` lists) in a SQLite database (`session.db`) inside the output folder. If interrupted, simply re-running the command with the same output directory will resume scraping from where it stopped.
4. **Duplicate Detection**: Computes cryptographic content hashes of main page text and prevents saving/crawling duplicate pages (such as calendar archive paths, duplicate queries, etc.).
5. **Auto-Throttle**: Automatically increases or decreases delay between requests dynamically based on the target server's response time to prevent getting blocked.
6. **User-Agent Rotation**: Automatically selects from a pool of modern browser user agents for each request.
7. **AI Blog Extraction**: Integrates optional Gemini API (`gemini-2.5-flash`) to structurally extract blog title, author, date, and text summary directly from cleaned HTML context.
8. **Proxy Rotation**: Rotates through a text file pool of HTTP/HTTPS/Socks5 proxies for both requests and Playwright.
9. **Sitemap Crawling**: Can read a site's `sitemap.xml` directly to populate the crawl queue immediately.
10. **Media Download Filters**: Optional filters to exclude media types (images/audio/video) or skip files exceeding a custom size limit in MB (disabled by default).
11. **Custom CSS Selectors**: Allows inputting custom CSS selectors for blog Title, Author, Date, and Content via CLI flags.
12. **Multiple Export Formats**: Save extracted blog data to JSON, CSV, individual Markdown files, or all three.
13. **Custom Folder Name via CLI**: Allows passing `--name` to determine the specific subdirectory inside `project/` where scraped files are saved.
14. **Unlimited Crawling**: By default, maximum crawl depth is set to `-1` (unlimited), allowing crawling of entire websites.

---

## Installation

1. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```
2. Install Playwright browsers (required for the default JavaScript rendering engine used for React, Vue, SPAs):
   ```bash
   python -m playwright install chromium
   ```

---

## Complete CLI Usage Reference

Below is a detailed guide and example for every CLI flag and option available in the scraper.

### 1. Target URL (Required Positional Argument)

The seed URL where the crawl starts. It automatically prepends `https://` if no scheme is provided.

- **Example**:
  ```bash
  python scraper.py https://books.toscrape.com
  ```

### 2. Output Subdirectory Name (`--name`)

Specifies the folder name under the `project/` directory to store the outputs.

- **Example**:
  ```bash
  python scraper.py https://example.com --name my_scraped_site
  # Saved to: project/my_scraped_site/
  ```

### 3. Explicit Output Path (`-o` or `--output`)

Overrides the default `project/` directory mapping to output files to a completely custom, arbitrary path.

- **Example**:
  ```bash
  python scraper.py https://example.com -o C:\CustomScrapedDirectory
  ```

### 4. Maximum Crawl Depth (`-d` or `--depth`)

Determines how deep the crawler follows internal links recursively. Defaults to `-1` (unlimited depth). Depth `0` crawls only the seed page.

- **Example**:
  ```bash
  python scraper.py https://example.com --depth 3 --name depth_three_crawl
  ```

### 5. Crawling Delay (`-w` or `--delay`)

The baseline delay in seconds between HTTP requests to be polite to target servers.

- **Example**:
  ```bash
  python scraper.py https://example.com --delay 2.5 --name slow_crawl
  ```

### 6. Blog Parsing Mode (`--blog`)

Enables the parsing and extraction of blog metadata (Title, Author, Date, Content) into structured files.

- **Example**:
  ```bash
  python scraper.py https://example.com/blog --blog --name blog_extractor
  ```

### 7. Disable JavaScript Rendering (`--no-js`)

JavaScript rendering (Playwright Chromium) is enabled by default to scrape modern client-side apps like React, Vue, Angular, etc. If you want to crawl static HTML sites faster without JS rendering, you can pass the `--no-js` flag to fall back to static Python requests.

- **Example**:
  ```bash
  python scraper.py https://example.com --no-js --name static_site
  ```

### 7b. Adjust JS Wait Time (`--js-wait`)

Allows adjusting the wait time (hydration timeout) in milliseconds after the page load before extracting contents. Defaults to `2000` (2 seconds).

- **Example**:
  ```bash
  python scraper.py https://example.com --js-wait 5000 --name slow_hydration_site
  ```

### 8. Gemini API Key (`--gemini-key`)

Used in combination with `--blog` to use AI for extracting blog details from pages. You can also specify the `GEMINI_API_KEY` environment variable.

- **Example**:
  ```bash
  python scraper.py https://example.com/blog --blog --gemini-key YOUR_API_KEY --name ai_blog
  ```

### 9. Proxy Rotation (`--proxies`)

Passes a path to a text file containing a list of proxies (one per line, e.g., `http://username:password@ip:port` or `ip:port`).

- **Example**:
  ```bash
  python scraper.py https://example.com --proxies proxies.txt --name proxy_crawl
  ```

### 10. Sitemap Parsing (`--sitemap`)

Downloads and parses the target's `sitemap.xml` file first, immediately adding all mapped URLs to the queue.

- **Example**:
  ```bash
  python scraper.py https://example.com --sitemap --name sitemap_crawl
  ```

### 11. Exclude Media Assets (`--exclude-media`)

Filters out and skips downloading image, audio, video, and archive files to save space and bandwidth.

- **Example**:
  ```bash
  python scraper.py https://example.com --exclude-media --name text_only_site
  ```

### 12. Maximum Asset Size Filter (`--max-size`)

Sets a size threshold in MB. Assets larger than this limit will not be downloaded.

- **Example**:
  ```bash
  python scraper.py https://example.com --max-size 1.5 --name small_assets_only
  ```

### 13. Export Format (`--format`)

Determines the output format for extracted blog data. Options are `json`, `csv`, `markdown`, or `all`.

- **Example**:
  ```bash
  python scraper.py https://example.com/blog --blog --format all --name rich_exports
  # Will generate:
  # - project/rich_exports/blog_content.json
  # - project/rich_exports/blog_content.csv
  # - project/rich_exports/articles/*.md (individual markdown files per article)
  ```

### 14. Custom CSS Selectors (`--select-title`, `--select-author`, `--select-date`, `--select-content`)

Manually specifies CSS selectors to target specific HTML elements for article metadata extraction.

- **Example**:
  ```bash
  python scraper.py https://example.com/blog --blog --select-title "h1.entry-title" --select-author "span.author-name" --select-content "div.post-body" --name custom_selectors
  ```

### 15. Disable Duplicate Detection (`--no-dedup`)

Disables skipping duplicate pages, forcing the crawler to download pages even if they have identical text content to a previously visited page.

- **Example**:
  ```bash
  python scraper.py https://example.com --no-dedup --name crawl_duplicates
  ```

### 16. Disable Same-Path Restriction (`--no-same-path`)

By default, the crawler restricts perayapan to URLs that start with the directory path of the seed URL. Pass `--no-same-path` to allow crawling URLs outside the directory path of the starting URL (crawling the entire domain).

- **Example**:
  ```bash
  python scraper.py https://example.com/html/trivia/index.html --no-same-path --name full_domain_crawl
  ```

---

## Combining Flags (Full Production Example)

To run a highly resilient crawl that:

- Uses JavaScript rendering with proxies.
- Speeds up parsing by loading from `sitemap.xml` first.
- Excludes media assets larger than 2MB.
- Extracts articles using custom selectors.
- Saves structured outputs in all formats (JSON, CSV, MD) under `project/production_run`.

```bash
python scraper.py https://example.com/blog \
  --js-wait 3000 \
  --sitemap \
  --proxies proxies.txt \
  --exclude-media \
  --max-size 2 \
  --blog \
  --select-title "h1.post-title" \
  --select-content "div.entry-content" \
  --format all \
  --name production_run
```

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
