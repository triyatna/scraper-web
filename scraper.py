import os
import sys
import argparse
import json
import csv
import re
import hashlib
import time
import sqlite3
import random
import posixpath
from urllib.parse import urlparse, urljoin, urldefrag
import requests
from bs4 import BeautifulSoup

PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
]

MEDIA_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.ico',
    '.mp4', '.webm', '.ogg', '.mp3', '.wav', '.flac', '.aac',
    '.zip', '.tar', '.gz', '.rar', '.7z', '.pdf', '.dmg', '.exe'
}

class CrawlSession:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS to_visit (url TEXT PRIMARY KEY, depth INTEGER)")
        cursor.execute("CREATE TABLE IF NOT EXISTS visited (url TEXT PRIMARY KEY)")
        cursor.execute("CREATE TABLE IF NOT EXISTS page_hashes (hash TEXT PRIMARY KEY, url TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS blog_data (url TEXT PRIMARY KEY, title TEXT, author TEXT, date TEXT, content TEXT)")
        self.conn.commit()

    def add_to_visit(self, url, depth):
        cursor = self.conn.cursor()
        try:
            cursor.execute("INSERT INTO to_visit (url, depth) VALUES (?, ?)", (url, depth))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def pop_to_visit(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT url, depth FROM to_visit LIMIT 1")
        row = cursor.fetchone()
        if row:
            cursor.execute("DELETE FROM to_visit WHERE url = ?", (row[0],))
            self.conn.commit()
            return row[0], row[1]
        return None

    def mark_visited(self, url):
        cursor = self.conn.cursor()
        try:
            cursor.execute("INSERT INTO visited (url) VALUES (?)", (url,))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def is_visited(self, url):
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM visited WHERE url = ?", (url,))
        return cursor.fetchone() is not None

    def is_in_to_visit(self, url):
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM to_visit WHERE url = ?", (url,))
        return cursor.fetchone() is not None

    def is_duplicate_content(self, content_hash, url):
        cursor = self.conn.cursor()
        cursor.execute("SELECT url FROM page_hashes WHERE hash = ?", (content_hash,))
        row = cursor.fetchone()
        if row:
            return True, row[0]
        try:
            cursor.execute("INSERT INTO page_hashes (hash, url) VALUES (?, ?)", (content_hash, url))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass
        return False, None

    def save_blog_data(self, url, title, author, date, content):
        cursor = self.conn.cursor()
        try:
            cursor.execute("INSERT OR REPLACE INTO blog_data (url, title, author, date, content) VALUES (?, ?, ?, ?, ?)", 
                           (url, title, author, date, content))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def get_all_blog_data(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT url, title, author, date, content FROM blog_data")
        rows = cursor.fetchall()
        return [
            {
                "url": r[0],
                "title": r[1],
                "author": r[2],
                "date": r[3],
                "content_preview": r[4][:1000] + "..." if len(r[4]) > 1000 else r[4],
                "content_full": r[4]
            }
            for r in rows
        ]

    def close(self):
        self.conn.close()

def clean_filename(path):
    return re.sub(r'[<>:"|?*]', '_', path)

def get_local_path(url, base_url, output_dir, is_page=False):
    parsed_url = urlparse(url)
    parsed_base = urlparse(base_url)
    netloc = parsed_url.netloc or parsed_base.netloc
    path = parsed_url.path
    query = parsed_url.query
    if not path or path.endswith('/'):
        path_dir = path
        filename = 'index.html' if is_page else 'index'
    else:
        path_dir, filename = os.path.split(path)
    name, ext = os.path.splitext(filename)
    if is_page:
        if ext.lower() not in ['.html', '.htm', '.php', '.asp', '.aspx', '.jsp']:
            if ext:
                name = name + ext
            ext = '.html'
    if query:
        clean_query = re.sub(r'[^a-zA-Z0-9_\-]', '_', query)
        if len(clean_query) > 50:
            clean_query = hashlib.md5(query.encode('utf-8')).hexdigest()[:10]
        name = f"{name}_{clean_query}"
    filename = f"{name}{ext}"
    full_path_parts = []
    if path_dir:
        for part in path_dir.strip('/').split('/'):
            if part:
                full_path_parts.append(clean_filename(part))
    full_path_parts.append(clean_filename(filename))
    relative_path = os.path.join(*full_path_parts) if full_path_parts else 'index.html'
    if netloc != parsed_base.netloc:
        return os.path.join(output_dir, 'external', clean_filename(netloc), relative_path)
    return os.path.join(output_dir, relative_path)

def get_relative_path(from_path, to_path):
    from_dir = os.path.dirname(from_path)
    try:
        rel = os.path.relpath(to_path, from_dir)
        return rel.replace('\\', '/')
    except ValueError:
        return to_path

def get_content_hash(text):
    clean_text = re.sub(r'[^a-zA-Z0-9]', '', text).lower()
    return hashlib.md5(clean_text.encode('utf-8')).hexdigest()

def clean_html_for_gemini(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    for tag in soup(['script', 'style', 'iframe', 'noscript', 'svg', 'header', 'footer', 'nav']):
        tag.decompose()
    return str(soup)[:15000]

def clean_proxy_url(proxy_str):
    proxy_str = proxy_str.strip()
    if not proxy_str.startswith(('http://', 'https://', 'socks5://')):
        proxy_str = 'http://' + proxy_str
    return proxy_str

def load_proxies(proxy_file):
    if not proxy_file or not os.path.exists(proxy_file):
        return []
    proxies = []
    with open(proxy_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                proxies.append(clean_proxy_url(line))
    return proxies

def get_request_proxies(proxy_list):
    if not proxy_list:
        return None
    p = random.choice(proxy_list)
    return {"http": p, "https": p}

def get_playwright_proxy(proxy_list):
    if not proxy_list:
        return None
    p = random.choice(proxy_list)
    parsed = urlparse(p)
    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"
    proxy_opt = {"server": server}
    if parsed.username:
        proxy_opt["username"] = parsed.username
    if parsed.password:
        proxy_opt["password"] = parsed.password
    return proxy_opt

def parse_sitemap(sitemap_url, proxy_list=None):
    try:
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        proxies = get_request_proxies(proxy_list)
        res = requests.get(sitemap_url, headers=headers, proxies=proxies, timeout=15)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            urls = [loc.get_text().strip() for loc in soup.find_all('loc')]
            return urls
    except Exception:
        pass
    return []

def extract_blog_data_gemini(html_content, api_key):
    cleaned_html = clean_html_for_gemini(html_content)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    prompt = (
        "Extract blog article metadata from the following HTML structure. "
        "Return a JSON object with these keys: 'title', 'author', 'date', 'content'. "
        "Keep the 'content' key under 1000 characters. "
        "HTML:\n" + cleaned_html
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    try:
        res = requests.post(url, json=payload, timeout=20)
        if res.status_code == 200:
            data = res.json()
            text_response = data['candidates'][0]['content']['parts'][0]['text']
            cleaned_text = text_response.strip()
            if cleaned_text.startswith("```"):
                lines = cleaned_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                cleaned_text = "\n".join(lines).strip()
            parsed_data = json.loads(cleaned_text)
            return {
                "title": parsed_data.get("title", ""),
                "author": parsed_data.get("author", "Unknown"),
                "date": parsed_data.get("date", "Unknown"),
                "content_preview": parsed_data.get("content", ""),
                "content_full": parsed_data.get("content", "")
            }
    except Exception:
        pass
    return None

def download_file(url, local_path, exclude_media=False, max_size_mb=None, proxy_list=None):
    try:
        ext = os.path.splitext(local_path)[1].lower()
        if exclude_media and ext in MEDIA_EXTENSIONS:
            return False
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        proxies = get_request_proxies(proxy_list)
        with requests.get(url, headers=headers, proxies=proxies, timeout=15, stream=True) as res:
            if res.status_code == 200:
                if max_size_mb:
                    size = res.headers.get('Content-Length')
                    if size and int(size) > max_size_mb * 1024 * 1024:
                        return False
                with open(local_path, 'wb') as f:
                    for chunk in res.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                return True
    except Exception:
        pass
    return False

def process_css_file(url, local_path, target_url, output_dir, exclude_media=False, max_size_mb=None, proxy_list=None):
    try:
        with open(local_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        urls = re.findall(r'url\s*\(\s*[\'"]?([^\'")\s]+)[\'"]?\s*\)', content)
        modified = False
        for css_ref in urls:
            if css_ref.startswith(('data:', 'http://', 'https://')):
                continue
            full_ref_url = urljoin(url, css_ref)
            local_ref_path = get_local_path(full_ref_url, target_url, output_dir, is_page=False)
            if local_ref_path:
                if download_file(full_ref_url, local_ref_path, exclude_media, max_size_mb, proxy_list):
                    rel_ref_path = get_relative_path(local_path, local_ref_path)
                    content = content.replace(css_ref, rel_ref_path)
                    modified = True
        if modified:
            with open(local_path, 'w', encoding='utf-8', errors='ignore') as f:
                f.write(content)
    except Exception:
        pass

def extract_blog_data(soup, url, custom_sel=None):
    title = ""
    author = "Unknown"
    date = "Unknown"
    content = ""
    if custom_sel:
        if custom_sel.get('title'):
            t_tag = soup.select_one(custom_sel['title'])
            if t_tag:
                title = t_tag.get_text().strip()
        if custom_sel.get('author'):
            a_tag = soup.select_one(custom_sel['author'])
            if a_tag:
                author = a_tag.get_text().strip()
        if custom_sel.get('date'):
            d_tag = soup.select_one(custom_sel['date'])
            if d_tag:
                date = d_tag.get_text().strip()
        if custom_sel.get('content'):
            c_tag = soup.select_one(custom_sel['content'])
            if c_tag:
                content = c_tag.get_text(separator='\n').strip()
    if not title:
        title_tag = soup.find('h1')
        if title_tag:
            title = title_tag.get_text().strip()
        else:
            title_meta = soup.find('meta', attrs={"property": "og:title"})
            if title_meta:
                title = title_meta.get('content', '').strip()
            else:
                title_tag = soup.find('title')
                if title_tag:
                    title = title_tag.get_text().strip()
    if not content:
        article_tag = soup.find('article')
        if article_tag:
            content = article_tag.get_text(separator='\n').strip()
        else:
            content_div = soup.find(attrs={"class": re.compile(r'post-content|entry-content|article-body|post-body', re.I)})
            if content_div:
                content = content_div.get_text(separator='\n').strip()
            else:
                main_tag = soup.find('main')
                if main_tag:
                    content = main_tag.get_text(separator='\n').strip()
                else:
                    body_tag = soup.find('body')
                    if body_tag:
                        content = body_tag.get_text(separator='\n').strip()
    if author == "Unknown":
        author_tag = soup.find(attrs={"class": re.compile(r'author|byline|writer', re.I)})
        if author_tag:
            author = author_tag.get_text().strip()
        else:
            author_meta = soup.find('meta', attrs={"name": "author"})
            if author_meta and author_meta.get('content'):
                author = author_meta.get('content').strip()
    if date == "Unknown":
        date_tag = soup.find(attrs={"class": re.compile(r'date|publish|time', re.I)})
        if date_tag:
            date = date_tag.get_text().strip()
        else:
            date_meta = soup.find('meta', attrs={"property": "published_time|date", "content": True})
            if date_meta:
                date = date_meta.get('content').strip()
    if not title and not content:
        return None
    return {
        "url": url,
        "title": title,
        "author": author,
        "date": date,
        "content_preview": content[:1000] + "..." if len(content) > 1000 else content,
        "content_full": content
    }

def export_data(blog_data, output_dir, export_format):
    if not blog_data:
        return
    formats = [export_format.lower()]
    if export_format.lower() == 'all':
        formats = ['json', 'csv', 'markdown']
    if 'json' in formats:
        blog_file = os.path.join(output_dir, 'blog_content.json')
        with open(blog_file, 'w', encoding='utf-8') as f:
            json.dump(blog_data, f, indent=4, ensure_ascii=False)
        print(f"Blog content exported to JSON: {blog_file}")
    if 'csv' in formats:
        csv_file = os.path.join(output_dir, 'blog_content.csv')
        keys = ['url', 'title', 'author', 'date', 'content_preview']
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for row in blog_data:
                filtered_row = {k: row.get(k, '') for k in keys}
                writer.writerow(filtered_row)
        print(f"Blog content exported to CSV: {csv_file}")
    if 'markdown' in formats:
        articles_dir = os.path.join(output_dir, 'articles')
        os.makedirs(articles_dir, exist_ok=True)
        for article in blog_data:
            title = article.get('title', 'untitled')
            clean_title = clean_filename(title).replace(' ', '_')
            if not clean_title:
                clean_title = hashlib.md5(article['url'].encode('utf-8')).hexdigest()[:8]
            filepath = os.path.join(articles_dir, f"{clean_title}.md")
            content = article.get('content_full', article.get('content_preview', ''))
            md_content = f"# {title}\n\n"
            md_content += f"- **Author**: {article.get('author', 'Unknown')}\n"
            md_content += f"- **Date**: {article.get('date', 'Unknown')}\n"
            md_content += f"- **URL**: {article.get('url', '')}\n\n"
            md_content += "---\n\n"
            md_content += content
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(md_content)
        print(f"Blog content exported to Markdown articles inside: {articles_dir}")

def main():
    parser = argparse.ArgumentParser(description="Advanced Smart Python Web Scraper CLI")
    parser.add_argument("url", help="Target URL to scrape")
    parser.add_argument("-o", "--output", help="Explicit output directory (overrides project/ folder mapping)")
    parser.add_argument("--name", help="Name of the folder inside project/ to save results")
    parser.add_argument("-d", "--depth", type=int, default=-1, help="Maximum crawl depth (use -1 for unlimited)")
    parser.add_argument("-w", "--delay", type=float, default=0.5, help="Base delay between requests in seconds")
    parser.add_argument("--blog", action="store_true", help="Extract and save blog contents")
    parser.add_argument("--js", action="store_true", help="Enable JavaScript rendering via Playwright")
    parser.add_argument("--gemini-key", help="Gemini API Key for AI blog extraction")
    parser.add_argument("--proxies", help="Path to proxy list file")
    parser.add_argument("--sitemap", action="store_true", help="Crawl via sitemap.xml first")
    parser.add_argument("--exclude-media", action="store_true", help="Exclude media files (images, audio, video)")
    parser.add_argument("--max-size", type=float, help="Maximum file size of assets in MB")
    parser.add_argument("--format", choices=["json", "csv", "markdown", "all"], default="json", help="Export format for blog content")
    parser.add_argument("--select-title", help="Custom CSS selector for blog title")
    parser.add_argument("--select-author", help="Custom CSS selector for blog author")
    parser.add_argument("--select-date", help="Custom CSS selector for blog date")
    parser.add_argument("--select-content", help="Custom CSS selector for blog content")
    parser.add_argument("--no-dedup", action="store_true", help="Disable page content deduplication")
    parser.add_argument("--same-path", action="store_true", help="Restrict crawling to URLs under the path of the starting URL")
    args = parser.parse_args()

    target_url = args.url
    if not target_url.startswith(('http://', 'https://')):
        target_url = 'https://' + target_url
    parsed_target = urlparse(target_url)
    domain = parsed_target.netloc
    
    target_path = parsed_target.path
    if not target_path:
        target_path = '/'
    if target_path.endswith('/'):
        target_dir = target_path
    else:
        target_dir = posixpath.dirname(target_path)
        if not target_dir.endswith('/'):
            target_dir += '/'
    
    output_dir = args.output
    if not output_dir:
        if args.name:
            output_dir = os.path.join("project", clean_filename(args.name))
        else:
            output_dir = os.path.join("project", f"scraped_{clean_filename(domain)}")
    os.makedirs(output_dir, exist_ok=True)

    proxy_list = load_proxies(args.proxies) if args.proxies else []
    session = None
    browser = None
    playwright_instance = None

    try:
        session = CrawlSession(os.path.join(output_dir, "session.db"))
        
        cursor = session.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM to_visit")
        if cursor.fetchone()[0] == 0:
            session.add_to_visit(target_url, 0)

        if args.sitemap:
            sitemap_url = urljoin(target_url, '/sitemap.xml')
            print(f"Fetching sitemap from: {sitemap_url}")
            sitemap_urls = parse_sitemap(sitemap_url, proxy_list)
            if sitemap_urls:
                print(f"Discovered {len(sitemap_urls)} URLs from sitemap. Adding to queue.")
                for s_url in sitemap_urls:
                    parsed_s = urlparse(s_url)
                    if parsed_s.netloc == domain:
                        if not args.same_path or parsed_s.path.startswith(target_dir):
                            session.add_to_visit(s_url, 0)
            else:
                print("Sitemap not found or empty.")

        if args.js:
            if PLAYWRIGHT_AVAILABLE:
                playwright_instance = sync_playwright().start()
                proxy_opt = get_playwright_proxy(proxy_list)
                browser = playwright_instance.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                    proxy=proxy_opt
                )
                print("JavaScript rendering enabled via Playwright.")
            else:
                print("Warning: Playwright not installed. Falling back to static requests.")

        api_key = args.gemini_key or os.environ.get("GEMINI_API_KEY")
        current_delay = args.delay
        custom_sel = {
            "title": args.select_title,
            "author": args.select_author,
            "date": args.select_date,
            "content": args.select_content
        }

        while True:
            next_item = session.pop_to_visit()
            if not next_item:
                break
            url, depth = next_item
            if session.is_visited(url) or (args.depth >= 0 and depth > args.depth):
                continue
            session.mark_visited(url)
            print(f"Scraping: {url} (Depth: {depth})")
            time.sleep(current_delay)
            
            try:
                start_time = time.time()
                if browser and args.js:
                    proxy_opt = get_playwright_proxy(proxy_list)
                    context = None
                    page = None
                    try:
                        context = browser.new_context(
                            user_agent=random.choice(USER_AGENTS),
                            viewport={"width": 1280, "height": 720},
                            locale="en-US",
                            timezone_id="America/New_York",
                            proxy=proxy_opt
                        )
                        page = context.new_page()
                        page_res = page.goto(url, wait_until="networkidle", timeout=30000)
                        status_code = page_res.status if page_res else 500
                        html_content = page.content()
                    finally:
                        if page:
                            page.close()
                        if context:
                            context.close()
                else:
                    headers = {'User-Agent': random.choice(USER_AGENTS)}
                    proxies = get_request_proxies(proxy_list)
                    res = requests.get(url, headers=headers, proxies=proxies, timeout=15)
                    status_code = res.status_code
                    html_content = res.text
                
                elapsed = time.time() - start_time
                if elapsed > 2.0:
                    current_delay = min(args.delay * 3.0, current_delay + 0.5)
                elif elapsed < 0.5:
                    current_delay = max(args.delay, current_delay - 0.1)

                if status_code != 200:
                    continue

                soup = BeautifulSoup(html_content, 'html.parser')
                
                if not args.no_dedup:
                    text_content = soup.get_text()
                    content_hash = get_content_hash(text_content)
                    is_dup, dup_url = session.is_duplicate_content(content_hash, url)
                    if is_dup:
                        print(f"Skipped duplicate page content. Similar to: {dup_url}")
                        continue

                if args.blog:
                    data = None
                    if api_key:
                        data = extract_blog_data_gemini(html_content, api_key)
                    if not data:
                        data = extract_blog_data(soup, url, custom_sel)
                    if data:
                        session.save_blog_data(
                            url, 
                            data.get("title", ""), 
                            data.get("author", "Unknown"), 
                            data.get("date", "Unknown"), 
                            data.get("content_full", data.get("content_preview", ""))
                        )

                local_html_path = get_local_path(url, target_url, output_dir, is_page=True)
                if not local_html_path:
                    continue
                os.makedirs(os.path.dirname(local_html_path), exist_ok=True)

                for tag in soup.find_all(['link', 'script', 'img', 'video', 'audio', 'source', 'iframe']):
                    src_attr = 'href' if tag.name == 'link' else 'src'
                    src_url = tag.get(src_attr)
                    if not src_url:
                        continue
                    full_src_url = urljoin(url, src_url)
                    local_asset_path = get_local_path(full_src_url, target_url, output_dir, is_page=False)
                    if local_asset_path:
                        if download_file(full_src_url, local_asset_path, args.exclude_media, args.max_size, proxy_list):
                            is_css = (tag.name == 'link' and 'stylesheet' in tag.get('rel', []))
                            if is_css:
                                process_css_file(full_src_url, local_asset_path, target_url, output_dir, args.exclude_media, args.max_size, proxy_list)
                            tag[src_attr] = get_relative_path(local_html_path, local_asset_path)

                for tag in soup.find_all(srcset=True):
                    srcset = tag.get('srcset')
                    if srcset:
                        parts = []
                        for part in srcset.split(','):
                            part = part.strip()
                            if not part:
                                continue
                            subparts = part.split()
                            if not subparts:
                                continue
                            img_url = subparts[0]
                            full_img_url = urljoin(url, img_url)
                            local_img_path = get_local_path(full_img_url, target_url, output_dir, is_page=False)
                            if local_img_path:
                                download_file(full_img_url, local_img_path, args.exclude_media, args.max_size, proxy_list)
                                subparts[0] = get_relative_path(local_html_path, local_img_path)
                            parts.append(' '.join(subparts))
                        tag['srcset'] = ', '.join(parts)

                for style_tag in soup.find_all('style'):
                    if style_tag.string:
                        content = style_tag.string
                        urls = re.findall(r'url\s*\(\s*[\'"]?([^\'")\s]+)[\'"]?\s*\)', content)
                        modified = False
                        for css_ref in urls:
                            if css_ref.startswith(('data:', 'http://', 'https://')):
                                continue
                            full_ref_url = urljoin(url, css_ref)
                            local_ref_path = get_local_path(full_ref_url, target_url, output_dir, is_page=False)
                            if local_ref_path:
                                if download_file(full_ref_url, local_ref_path, args.exclude_media, args.max_size, proxy_list):
                                    rel_ref_path = get_relative_path(local_html_path, local_ref_path)
                                    content = content.replace(css_ref, rel_ref_path)
                                    modified = True
                        if modified:
                            style_tag.string = content

                for tag_with_style in soup.find_all(style=True):
                    content = tag_with_style['style']
                    urls = re.findall(r'url\s*\(\s*[\'"]?([^\'")\s]+)[\'"]?\s*\)', content)
                    modified = False
                    for css_ref in urls:
                        if css_ref.startswith(('data:', 'http://', 'https://')):
                            continue
                        full_ref_url = urljoin(url, css_ref)
                        local_ref_path = get_local_path(full_ref_url, target_url, output_dir, is_page=False)
                        if local_ref_path:
                            if download_file(full_ref_url, local_ref_path, args.exclude_media, args.max_size, proxy_list):
                                rel_ref_path = get_relative_path(local_html_path, local_ref_path)
                                content = content.replace(css_ref, rel_ref_path)
                                modified = True
                    if modified:
                        tag_with_style['style'] = content

                for link in soup.find_all('a'):
                    href = link.get('href')
                    if not href:
                        continue
                    full_href = urljoin(url, href)
                    clean_href, fragment = urldefrag(full_href)
                    parsed_href = urlparse(clean_href)
                    if parsed_href.netloc == domain:
                        in_scope = True
                        if args.same_path:
                            href_path = parsed_href.path
                            if not href_path.startswith(target_dir):
                                in_scope = False
                        if in_scope:
                            local_link_path = get_local_path(clean_href, target_url, output_dir, is_page=True)
                            if local_link_path:
                                rel_link_path = get_relative_path(local_html_path, local_link_path)
                                link['href'] = f"{rel_link_path}#{fragment}" if fragment else rel_link_path
                                if not session.is_visited(clean_href) and not session.is_in_to_visit(clean_href):
                                    session.add_to_visit(clean_href, depth + 1)
                        else:
                            link['href'] = full_href

                with open(local_html_path, 'w', encoding='utf-8') as f:
                    f.write(str(soup))
            except Exception as e:
                print(f"Error scraping {url}: {e}")
    finally:
        if browser:
            browser.close()
        if playwright_instance:
            playwright_instance.stop()
        if session:
            if args.blog:
                blog_data = session.get_all_blog_data()
                export_data(blog_data, output_dir, args.format)
            session.close()
    print("Scraping completed successfully!")

if __name__ == "__main__":
    main()
