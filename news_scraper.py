import urllib.request
import xml.etree.ElementTree as ET
import re

WYOMING_FEEDS = [
    {"source": "WyoFile", "url": "https://wyofile.com/feed/"},
    {"source": "Oil City News", "url": "https://oilcity.news/feed/"},
    {"source": "Cap City News", "url": "https://capcity.news/feed/"},
    {"source": "Cowboy State Daily", "url": "https://cowboystatedaily.com/feed/"}
]

def clean_html(raw_html):
    """Strip HTML tags from RSS summaries."""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext.strip()

def fetch_wyoming_news():
    """Fetch RSS items across feeds with built-in title deduplication."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    articles = []
    seen_titles = set()

    for feed in WYOMING_FEEDS:
        try:
            req = urllib.request.Request(feed["url"], headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
                root = ET.fromstring(xml_data)

                for item in root.findall(".//item")[:10]:
                    title = item.findtext("title", "No Title").strip()
                    link = item.findtext("link", "#").strip()
                    description = item.findtext("description", "")

                    # Deduplicate across feeds by normalized title
                    norm_title = title.lower().strip()
                    if norm_title in seen_titles:
                        continue
                    seen_titles.add(norm_title)

                    articles.append({
                        "title": title,
                        "source": feed["source"],
                        "summary": clean_html(description)[:250] + "...",
                        "link": link
                    })
        except Exception as e:
            print(f"Error fetching {feed['source']}: {e}")
            continue

    return articles