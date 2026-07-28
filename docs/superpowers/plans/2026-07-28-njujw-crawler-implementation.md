# NJUJW Crawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily crawler that fetches NJU academic affairs announcements via API, matches user-configured tags, sends email notifications, and updates README.

**Architecture:** `main.py` is the entry point — tries API first, falls back to importing `department.py` for HTML parsing. Reads config from `config.txt`, persists history in `department.csv`, outputs email HTML and updates README.md. GitHub Actions triggers daily and handles email sending.

**Tech Stack:** Python 3.14, requests, lxml, dawidd6/action-send-mail (GitHub Action)

---

### Task 1: Create config.txt

**Files:**
- Create: `config.txt`

- [ ] **Step 1: Write config.txt**

```txt
考试
毕业
课程
```

User can add more tags, one per line. Exact match against the `f1` field from the API.

- [ ] **Step 2: Commit**

```bash
git add config.txt
git commit -m "feat: add user tag config file"
```

---

### Task 2: Create main.py

**Files:**
- Create: `src/main.py`

This is the main script. It handles:
1. API fetch → HTML fallback
2. Dedup against existing CSV
3. Detail page summary extraction
4. Tag matching against config
5. Email HTML generation
6. README.md update
7. CSV append

- [ ] **Step 1: Write the full main.py**

```python
#!/usr/bin/env python3
"""
NJUJW Announcement Crawler
- API-first, HTML fallback
- Tag matching with email notification
- Daily README update
"""

import csv
import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Optional

import requests
from lxml import etree

# === Constants ===
API_URL = "https://jw.nju.edu.cn/_wp3services/generalQuery?queryObj=articles"
LIST_URL = "https://jw.nju.edu.cn/ggtz/list1.htm"
CSV_FILE = "department.csv"
CONFIG_FILE = "config.txt"
README_FILE = "README.md"
EMAIL_FILE = "email_content.html"
API_ROWS = 14
SUMMARY_CHARS = 50


# === Helpers ===

def extract_url_key(url: str) -> str:
    """Extract the unique path suffix from a URL for dedup.

    Handles both formats:
      - https://jw.nju.edu.cn/ggtz/list1.htm/d3/2d/c26263a840493/page.htm
      - https://jw.nju.edu.cn/d3/2d/c26263a840493/page.htm
    Returns: d3/2d/c26263a840493/page.htm
    """
    # Remove domain prefix
    path = re.sub(r'^https?://[^/]+', '', url)
    # Remove /ggtz/list1.htm prefix if present
    path = re.sub(r'^/ggtz/list1\.htm', '', path)
    return path.strip('/')


# === Config ===

def read_config() -> list[str]:
    """Read user's interested tags from config.txt, one per line."""
    if not os.path.exists(CONFIG_FILE):
        print("No config.txt found, skipping tag matching")
        return []
    with open(CONFIG_FILE, encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]


# === CSV ===

def read_existing_urls() -> set[str]:
    """Read existing CSV and return set of URL keys for dedup."""
    if not os.path.exists(CSV_FILE):
        return set()
    urls = set()
    with open(CSV_FILE, newline='', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter='\t')
        for row in reader:
            if len(row) >= 4:
                urls.add(extract_url_key(row[3]))
    return urls


def append_csv(items: list[list[str]]):
    """Append new items to CSV."""
    with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter='\t')
        for item in items:
            writer.writerow(item)
    print(f"Appended {len(items)} new items to {CSV_FILE}")


def read_all_csv_items() -> list[dict]:
    """Read all items from CSV for README generation."""
    items = []
    if not os.path.exists(CSV_FILE):
        return items
    with open(CSV_FILE, newline='', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter='\t')
        for row in reader:
            if len(row) >= 4:
                # Normalize URL format if needed
                url = row[3]
                if '/ggtz/list1.htm' in url:
                    url = re.sub(r'^https?://[^/]+/ggtz/list1\.htm', 'https://jw.nju.edu.cn', url)
                items.append({
                    'tags': eval(row[0]) if row[0].startswith('[') else [row[0]],
                    'title': row[1],
                    'time': row[2],
                    'url': url,
                    'summary': row[4] if len(row) >= 5 else '',
                })
    return items


# === API Fetch ===

def fetch_via_api() -> Optional[list[dict]]:
    """Fetch announcements via API. Returns list of items or None on failure."""
    try:
        headers = {'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8'}
        data = {
            'siteId': '414',
            'columnId': '26263',
            'pageIndex': '1',
            'rows': str(API_ROWS),
            'conditions': '[]',
            'orders': json.dumps([
                {'field': 'publishTime', 'type': 'desc'},
                {'field': 'visitCount', 'type': 'asc'},
            ]),
            'returnInfos': json.dumps([
                {'field': 'title', 'name': 'title'},
                {'field': 'f1', 'name': 'f1'},
                {'field': 'publishTime', 'pattern': [{'name': 'd', 'value': 'yyyy-MM-dd'}], 'name': 'publishTime'},
                {'field': 'link', 'name': 'link'},
            ]),
            'scope': '1',
        }
        resp = requests.post(API_URL, headers=headers, data=data, timeout=30, verify=False)
        resp.raise_for_status()
        result = resp.json()
        if result.get('status') != 1:
            print(f"API returned status={result.get('status')}")
            return None

        items = []
        for art in result.get('data', []):
            tags_str = art.get('f1', '').strip()
            tags = [t.strip() for t in tags_str.split('，') if t.strip()] if tags_str else []
            url = art.get('url', '')
            # Normalize to https
            if url.startswith('http://'):
                url = 'https://' + url[7:]
            items.append({
                'tags': tags,
                'title': art.get('title', '').strip(),
                'time': art.get('publishTime', ''),
                'url': url,
            })
        print(f"API: fetched {len(items)} items")
        return items
    except Exception as e:
        print(f"API fetch failed: {e}")
        return None


# === HTML Fallback ===

def fetch_via_html() -> list[dict]:
    """Fall back to HTML parsing when API fails."""
    print("Falling back to HTML parsing...")
    try:
        command = ['curl', '-k', LIST_URL]
        import subprocess
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        if result.returncode != 0:
            raise Exception(f"curl failed: {result.stderr}")
        html = result.stdout
    except Exception:
        # Fall back to requests
        resp = requests.get(LIST_URL, verify=False, timeout=30)
        resp.raise_for_status()
        html = resp.text

    tree = etree.HTML(html)
    nodes = tree.xpath('/html/body/div[7]/div/div/div[2]/div/div[2]/div/div/div[1]/ul/li')

    items = []
    for node in nodes:
        children = node.getchildren()
        if len(children) < 3:
            continue
        tag_node, title_node, time_node = children

        # Parse tags
        tag_texts = tag_node.xpath('.//text()')
        if tag_texts:
            tags_raw = tag_texts[0].strip()
            tags = [t.strip() for t in tags_raw.split('，') if t.strip()]
        else:
            tags = []

        # Parse title + href
        a_tag = title_node.xpath('./a')
        if not a_tag:
            continue
        title = a_tag[0].get('title', '').strip()
        href = a_tag[0].get('href', '').strip()
        url = 'https://jw.nju.edu.cn' + href if href.startswith('/') else href

        # Parse time
        time_text = ''.join(time_node.xpath('.//text()')).strip()
        time_text = time_text.split(' ')[0]  # Take only date part

        items.append({
            'tags': tags,
            'title': title,
            'time': time_text,
            'url': url,
        })

    print(f"HTML: parsed {len(items)} items")
    return items


# === Detail Page Summary ===

def fetch_summary(url: str) -> str:
    """Fetch detail page and extract first SUMMARY_CHARS chars of content."""
    try:
        resp = requests.get(url, verify=False, timeout=15)
        resp.raise_for_status()
        tree = etree.HTML(resp.text)
        # Content is in div.entry within .article
        entry = tree.xpath('//*[contains(@class, "entry")]')
        if entry:
            text = ''.join(entry[0].itertext()).strip()
        else:
            # Fallback: try .article
            article = tree.xpath('//*[contains(@class, "article")]')
            if article:
                text = ''.join(article[0].itertext()).strip()
            else:
                text = resp.text
        # Clean whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) <= SUMMARY_CHARS:
            return text
        return text[:SUMMARY_CHARS] + '...'
    except Exception as e:
        print(f"  Failed to fetch detail: {url[:60]} - {e}")
        return "（无法获取内容）"


# === Tag Matching ===

def match_tags(item_tags: list[str], config_tags: list[str]) -> bool:
    """Check if any item tag matches any config tag (exact match)."""
    if not config_tags:
        return False
    for tag in item_tags:
        if tag in config_tags:
            return True
    return False


# === Email Generation ===

def generate_email(matched_items: list[dict], config_tags: list[str]) -> str:
    """Generate HTML email content for matched items."""
    rows_html = ''
    for item in matched_items:
        rows_html += f'''
        <tr>
            <td style="padding:8px;border:1px solid #ddd;white-space:nowrap">{item['time']}</td>
            <td style="padding:8px;border:1px solid #ddd">
                <a href="{item['url']}" style="color:#8470a3;text-decoration:none">{item['title']}</a>
            </td>
            <td style="padding:8px;border:1px solid #ddd">
                {', '.join(f'<span style="display:inline-block;background:#8470a3;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;margin:2px">{t}</span>' for t in item['tags'])}
            </td>
            <td style="padding:8px;border:1px solid #ddd;color:#666;font-size:13px">{item.get('summary', '')}</td>
        </tr>'''

    tag_badges = ', '.join(
        f'<span style="display:inline-block;background:#8470a3;color:#fff;padding:2px 10px;border-radius:4px;font-size:13px">{t}</span>'
        for t in config_tags
    )

    html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;padding:20px;background:#f5f5f5">
<div style="max-width:680px;margin:0 auto;background:#fff;border-radius:8px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
    <div style="border-bottom:2px solid #8470a3;padding-bottom:12px;margin-bottom:20px">
        <h2 style="margin:0;color:#333">📬 南京大学教务处通知提醒</h2>
    </div>
    <p style="color:#555;font-size:14px">
        你关心的标签：{tag_badges}
    </p>
    <p style="color:#555;font-size:14px">本次有 <strong>{len(matched_items)}</strong> 条新通知：</p>
    <table style="width:100%;border-collapse:collapse;margin-top:12px">
        <thead>
            <tr style="background:#8470a3;color:#fff">
                <th style="padding:8px;text-align:left">时间</th>
                <th style="padding:8px;text-align:left">标题</th>
                <th style="padding:8px;text-align:left">标签</th>
                <th style="padding:8px;text-align:left">摘要</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>
    <p style="margin-top:20px;font-size:12px;color:#999;text-align:center">
        <a href="https://jw.nju.edu.cn/ggtz/list1.htm" style="color:#8470a3">查看全部通知 →</a>
    </p>
</div>
</body>
</html>'''
    return html


# === README Update ===

def update_readme(all_items: list[dict]):
    """Update README.md with latest 10 items in a table, history folded."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    total = len(all_items)
    latest = all_items[:10]

    # Build latest items table
    rows = ''
    for item in latest:
        tags_display = ', '.join(item['tags']) if item['tags'] else '—'
        summary = item.get('summary', '')
        if len(summary) > 50:
            summary = summary[:50] + '...'
        rows += f'| {item["time"]} | [{item["title"]}]({item["url"]}) | {tags_display} | {summary} |\n'

    # Build history section (items 11+)
    history_rows = ''
    for item in all_items[10:]:
        history_rows += f'| {item["time"]} | [{item["title"]}]({item["url"]}) |\n'

    readme = f'''# 南京大学教务处通知公告

> 每日自动抓取，更新于 {now}

## 📢 最新通知

| 时间 | 标题 | 标签 | 摘要 |
|------|------|------|------|
{rows}

<details>
<summary>📜 历史通知（共 {total} 条）</summary>

| 时间 | 标题 |
|------|------|
{history_rows}
</details>

---

*由 GitHub Actions 自动更新*
'''
    with open(README_FILE, 'w', encoding='utf-8') as f:
        f.write(readme)
    print(f"Updated {README_FILE} with {total} items")


# === Main ===

def main():
    # 1. Read config
    config_tags = read_config()
    print(f"Config tags: {config_tags}")

    # 2. Read existing URLs for dedup
    existing_urls = read_existing_urls()
    print(f"Existing items in CSV: {len(existing_urls)}")

    # 3. Fetch items (API first, HTML fallback)
    items = fetch_via_api()
    if items is None:
        items = fetch_via_html()
    if not items:
        print("No items fetched")
        return

    # 4. Find new items
    new_items = [item for item in items if extract_url_key(item['url']) not in existing_urls]
    if not new_items:
        print("No new items")
        # Still update README (to show latest items)
        all_items = read_all_csv_items()
        if all_items:
            update_readme(all_items)
        return

    print(f"New items: {len(new_items)}")

    # 5. Fetch summaries for new items
    print("Fetching detail page summaries...")
    for item in new_items:
        summary = fetch_summary(item['url'])
        item['summary'] = summary
        print(f"  {item['title'][:30]}... → {summary[:30]}...")

    # 6. Match tags
    matched = [item for item in new_items if match_tags(item['tags'], config_tags)]
    print(f"Matched tags: {len(matched)}/{len(new_items)}")

    # 7. Generate email if matched
    if matched:
        email_html = generate_email(matched, config_tags)
        with open(EMAIL_FILE, 'w', encoding='utf-8') as f:
            f.write(email_html)
        # Signal to GitHub Actions
        print("MATCHED=true")
        print(f"Email content written to {EMAIL_FILE}")
    else:
        print("MATCHED=false")

    # 8. Append to CSV
    csv_rows = []
    for item in new_items:
        tags_str = json.dumps(item['tags'], ensure_ascii=False)
        # Normalize URL for CSV (keep old format for consistency)
        url = item['url']
        csv_rows.append([tags_str, item['title'], item['time'], url, item.get('summary', '')])
    append_csv(csv_rows)

    # 9. Update README
    all_items = read_all_csv_items()
    if all_items:
        update_readme(all_items)


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Test the script locally**

```bash
cd /Users/macbook/Project/njujw && .venv/bin/python src/main.py 2>&1
```

Expected output (approximate):
```
Config tags: ['考试', '毕业', '课程']
Existing items in CSV: 354
API: fetched 14 items
New items: 2
Fetching detail page summaries...
  ...
Matched tags: 0/2
MATCHED=false
Appended 2 new items to department.csv
Updated README.md with 356 items
```

- [ ] **Step 3: Verify README.md and CSV were updated**

```bash
head -5 README.md
echo "---"
tail -3 department.csv
```

- [ ] **Step 4: Restore CSV if test was destructive**

```bash
cd /Users/macbook/Project/njujw && git checkout department.csv
```

- [ ] **Step 5: Commit**

```bash
git add src/main.py
git commit -m "feat: add main crawler script with API and HTML fallback"
```

---

### Task 3: Update requirements.txt

**Files:**
- Create: `requirements.txt`

- [ ] **Step 1: Write requirements.txt**

```
requests>=2.31.0
lxml>=5.0.0
```

- [ ] **Step 2: Commit**

```bash
git add requirements.txt
git commit -m "chore: add requirements.txt"
```

---

### Task 4: Create GitHub Actions workflow

**Files:**
- Create: `.github/workflows/daily.yml`

- [ ] **Step 1: Write daily.yml**

```yaml
name: Daily Crawl

on:
  schedule:
    # UTC 1:00 = 北京时间 9:00
    - cron: '0 1 * * *'
  workflow_dispatch:

jobs:
  crawl:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt

      - name: Run crawler
        run: python src/main.py
        env:
          # Suppress SSL warnings
          PYTHONWARNINGS: ignore

      - name: Send email notification
        if: hashFiles('email_content.html') != ''
        uses: dawidd6/action-send-mail@v4
        with:
          server_address: ${{ secrets.SMTP_HOST }}
          server_port: ${{ secrets.SMTP_PORT }}
          username: ${{ secrets.SMTP_USER }}
          password: ${{ secrets.SMTP_PASS }}
          subject: 📬 南京大学教务处通知提醒
          to: ${{ secrets.MAIL_TO }}
          from: ${{ secrets.SMTP_USER }}
          html_body: file://email_content.html

      - name: Commit updates
        run: |
          git config user.name "github-actions"
          git config user.email "actions@github.com"
          git add README.md department.csv email_content.html 2>/dev/null
          git commit -m "daily update $(date +%Y-%m-%d)" || echo "No changes to commit"
          git push
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/daily.yml
git commit -m "feat: add GitHub Actions daily workflow"
```

---

### Task 5: Update README.md template

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Create initial README.md**

```markdown
# 南京大学教务处通知公告

> 每日自动抓取，首次运行后更新

## 📢 最新通知

| 时间 | 标题 | 标签 | 摘要 |
|------|------|------|------|
| 等待首次爬取... |  |  |  |

---

*由 GitHub Actions 自动更新*
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add initial README template"
```

---

### Task 6: Create .gitignore

**Files:**
- Create: `.gitignore`

- [ ] **Step 1: Write .gitignore**

```
__pycache__/
*.pyc
.venv/
.env
email_content.html
.playwright-mcp/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: add gitignore"
```