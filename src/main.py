#!/usr/bin/env python3
"""
NJUJW Announcement Crawler (main entry point)

Flow:
  1. Read config.txt for user's interested tags
  2. Fetch announcements via API (primary) or HTML (fallback)
  3. Compare with department.csv to find new items
  4. Fetch detail page summaries for new items
  5. Match tags against user config
  6. Generate email_content.html if matches found
  7. Append new items to department.csv
  8. Update README.md with latest 10 items
"""

import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from typing import Optional

import requests
from lxml import etree

# Ensure src/ is in path for local imports from department.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# === Constants ===
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root (parent of src/)
API_URL = "https://jw.nju.edu.cn/_wp3services/generalQuery?queryObj=articles"
LIST_URL = "https://jw.nju.edu.cn/ggtz/list1.htm"
CSV_FILE = os.path.join(BASE_DIR, "department.csv")
CONFIG_FILE = os.path.join(BASE_DIR, "config.txt")
README_FILE = os.path.join(BASE_DIR, "README.md")
EMAIL_FILE = os.path.join(BASE_DIR, "email_content.html")
API_ROWS = 14
SUMMARY_CHARS = 50

# Suppress SSL warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# === Helpers ===

def extract_url_key(url: str) -> str:
    """Extract the unique path suffix from a URL for dedup.

    Handles both formats:
      - https://jw.nju.edu.cn/ggtz/list1.htm/d3/2d/c26263a840493/page.htm
      - https://jw.nju.edu.cn/d3/2d/c26263a840493/page.htm
    Returns: d3/2d/c26263a840493/page.htm
    """
    path = re.sub(r'^https?://[^/]+', '', url)
    path = re.sub(r'^/ggtz/list1\.htm', '', path)
    return path.strip('/')


# === Config ===

def read_config() -> list[str]:
    """Read user's interested tags from config.txt, one per line."""
    if not os.path.exists(CONFIG_FILE):
        print("[config] No config.txt found, skipping tag matching")
        return []
    with open(CONFIG_FILE, encoding='utf-8') as f:
        tags = [line.strip() for line in f if line.strip()]
    print(f"[config] Tags: {tags}")
    return tags


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
    print(f"[csv] Existing items: {len(urls)}")
    return urls


def append_csv(items: list[list[str]]):
    """Append new items to CSV."""
    with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter='\t')
        for item in items:
            writer.writerow(item)
    print(f"[csv] Appended {len(items)} new items")


def read_all_csv_items() -> list[dict]:
    """Read all items from CSV for README generation."""
    items = []
    if not os.path.exists(CSV_FILE):
        return items
    with open(CSV_FILE, newline='', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter='\t')
        for row in reader:
            if len(row) >= 4:
                tags = eval(row[0]) if row[0].startswith('[') else [row[0]]
                url = row[3]
                # Normalize old URL format: /ggtz/list1.htm/d1/7c/... → /d1/7c/...
                # Also handle malformed: /ggtz/list1.htmhttps://xgb.nju.edu.cn/...
                m = re.match(r'^(https?://[^/]+)/ggtz/list1\.htm(.+)$', url)
                if m:
                    suffix = m.group(2)
                    if suffix.startswith('http://') or suffix.startswith('https://'):
                        url = suffix  # external URL, use as-is
                    else:
                        url = m.group(1) + suffix  # strip /ggtz/list1.htm
                items.append({
                    'tags': tags,
                    'title': row[1],
                    'time': row[2].split(' ')[0],  # normalize to date only
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
            print(f"[api] API returned status={result.get('status')}")
            return None

        items = []
        for art in result.get('data', []):
            tags_str = art.get('f1', '').strip()
            tags = [t.strip() for t in tags_str.split('，') if t.strip()] if tags_str else []
            url = art.get('url', '')
            if url.startswith('http://'):
                url = 'https://' + url[7:]
            items.append({
                'tags': tags,
                'title': art.get('title', '').strip(),
                'time': art.get('publishTime', ''),
                'url': url,
            })
        print(f"[api] Fetched {len(items)} items")
        return items
    except Exception as e:
        print(f"[api] Failed: {e}")
        return None


# === HTML Fallback ===

def fetch_via_html() -> list[dict]:
    """Fall back to HTML parsing when API fails."""
    print("[html] Falling back to HTML parsing...")
    try:
        from department import parse_html_items
    except ImportError as e:
        print(f"[html] Cannot import parse_html_items: {e}")
        return []

    try:
        # Use curl to avoid encoding issues
        result = subprocess.run(
            ['curl', '-k', LIST_URL],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=30
        )
        if result.returncode == 0:
            html = result.stdout
        else:
            # Fall back to requests with raw bytes
            resp = requests.get(LIST_URL, verify=False, timeout=30)
            html = resp.content  # raw bytes, let lxml handle encoding
    except Exception:
        resp = requests.get(LIST_URL, verify=False, timeout=30)
        html = resp.content

    items = parse_html_items(html)
    print(f"[html] Parsed {len(items)} items")
    return items


# === Detail Page Summary ===

def fetch_summary(url: str) -> str:
    """Fetch detail page and extract first SUMMARY_CHARS chars of content."""
    try:
        resp = requests.get(url, verify=False, timeout=15)
        resp.raise_for_status()
        tree = etree.HTML(resp.content)
        entry = tree.xpath('//*[contains(@class, "entry")]')
        if entry:
            text = ''.join(entry[0].itertext()).strip()
        else:
            article = tree.xpath('//*[contains(@class, "article")]')
            if article:
                text = ''.join(article[0].itertext()).strip()
            else:
                text = resp.text
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) <= SUMMARY_CHARS:
            return text
        return text[:SUMMARY_CHARS] + '...'
    except Exception as e:
        print(f"  [detail] Failed: {url[:60]} - {e}")
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
    def tag_badge(t: str) -> str:
        return f'<span style="display:inline-block;background:#8470a3;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;margin:2px">{t}</span>'

    rows_html = ''
    for item in matched_items:
        tags_html = ' '.join(tag_badge(t) for t in item['tags'])
        rows_html += (
            f'<tr>'
            f'<td style="padding:8px;border:1px solid #ddd;white-space:nowrap">{item["time"]}</td>'
            f'<td style="padding:8px;border:1px solid #ddd">'
            f'<a href="{item["url"]}" style="color:#8470a3;text-decoration:none">{item["title"]}</a></td>'
            f'<td style="padding:8px;border:1px solid #ddd">{tags_html}</td>'
            f'<td style="padding:8px;border:1px solid #ddd;color:#666;font-size:13px">{item.get("summary", "")}</td>'
            f'</tr>\n'
        )

    tag_badges = ' '.join(tag_badge(t) for t in config_tags)

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

    rows = ''
    for item in latest:
        tags_display = ', '.join(item['tags']) if item['tags'] else '—'
        summary = item.get('summary', '')
        if len(summary) > 50:
            summary = summary[:50] + '...'
        rows += f'| {item["time"]} | [{item["title"]}]({item["url"]}) | {tags_display} | {summary} |\n'

    history_rows = ''
    for item in all_items[10:30]:  # at most 20 items in history
        history_rows += f'| {item["time"]} | [{item["title"]}]({item["url"]}) |\n'
    if len(all_items) > 30:
        history_rows += f'| ... | 共 {total} 条，仅显示最近 20 条 |\n'

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
    print(f"[readme] Updated with {total} items")


# === Main ===

def main():
    print("=" * 50)
    print("NJUJW Crawler")
    print("=" * 50)

    # 1. Read config
    config_tags = read_config()

    # 2. Read existing URLs for dedup
    existing_urls = read_existing_urls()

    # 3. Fetch items (API first, HTML fallback)
    items = fetch_via_api()
    if items is None:
        items = fetch_via_html()
    if not items:
        print("[main] No items fetched")
        return

    # 4. Find new items
    new_items = [item for item in items if extract_url_key(item['url']) not in existing_urls]
    if not new_items:
        print("[main] No new items")
        all_items = read_all_csv_items()
        all_items.sort(key=lambda x: x['time'], reverse=True)
        if all_items:
            update_readme(all_items)
        return

    print(f"[main] New items: {len(new_items)}")

    # 5. Fetch summaries for new items
    print("[main] Fetching detail page summaries...")
    for item in new_items:
        summary = fetch_summary(item['url'])
        item['summary'] = summary
        print(f"  {item['title'][:30]}... → {summary[:30]}...")

    # 6. Match tags
    matched = [item for item in new_items if match_tags(item['tags'], config_tags)]
    print(f"[main] Matched: {len(matched)}/{len(new_items)}")

    # 7. Generate email if matched
    if matched:
        email_html = generate_email(matched, config_tags)
        with open(EMAIL_FILE, 'w', encoding='utf-8') as f:
            f.write(email_html)
        print(f"[main] Email written to {EMAIL_FILE}")
        print("MATCHED=true")
    else:
        print("MATCHED=false")

    # 8. Append to CSV
    csv_rows = []
    for item in new_items:
        tags_str = json.dumps(item['tags'], ensure_ascii=False)
        csv_rows.append([tags_str, item['title'], item['time'], item['url'], item.get('summary', '')])
    append_csv(csv_rows)

    # 9. Update README
    all_items = read_all_csv_items()
    # Sort by time descending (newest first)
    all_items.sort(key=lambda x: x['time'], reverse=True)
    if all_items:
        update_readme(all_items)

    print("[main] Done")


if __name__ == '__main__':
    main()
