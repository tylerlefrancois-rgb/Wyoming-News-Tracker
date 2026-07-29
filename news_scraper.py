import urllib.request
import xml.etree.ElementTree as ET
import re

# ==============================================================================
# NEWS SOURCES
# ==============================================================================
WYOMING_FEEDS = [
    # Standard WordPress feed paths
    {"source": "WyoFile", "url": "https://wyofile.com/feed/"},
    {"source": "Oil City News", "url": "https://oilcity.news/feed/"},
    {"source": "Cap City News", "url": "https://capcity.news/feed/"},
    
    # REPAIRED: Upgraded to target the raw XML path to bypass 404 errors
    {"source": "Cowboy State Daily", "url": "https://cowboystatedaily.com/rss.xml"},
    
    # Custom query string feed for the Star-Tribune's proprietary system
    {"source": "Casper Star-Tribune", "url": "https://trib.com/search/?f=rss&t=article&l=50&s=start_time&sd=desc"},
    
    # REPAIRED: Wyoming Public Media's core publisher uses the rss.xml path
    {"source": "Wyoming Public Media", "url": "https://www.wyomingpublicmedia.org/rss.xml"}
]

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
def clean_html(raw_html):
    """
    Strips raw HTML tags from RSS summaries so they don't break our Streamlit UI.
    """
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext.strip()

def fetch_wyoming_news():
    """
    Fetches, parses, and deduplicates RSS items across all defined feeds.
    Returns a list of dictionaries containing title, source, summary, and link.
    """
    # Upgraded User-Agent to mimic a real modern browser. 
    # Many news sites block generic python-urllib headers to prevent scraping.
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
    }
    
    articles = []
    seen_titles = set()

    # Loop through our sources one by one
    for feed in WYOMING_FEEDS:
        try:
            # Build the request with our upgraded browser disguise
            req = urllib.request.Request(feed["url"], headers=headers)
            
            # Open the connection with a 10-second timeout so the app doesn't hang forever
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
                
                # Parse the raw XML into a navigable tree
                root = ET.fromstring(xml_data)

                # Find all <item> tags (the articles) and grab the top 10 from each source
                for item in root.findall(".//item")[:10]:
                    title = item.findtext("title", "No Title").strip()
                    link = item.findtext("link", "#").strip()
                    description = item.findtext("description", "")

                    # Normalize the title (lowercase, no extra spaces) to check for duplicates
                    norm_title = title.lower().strip()
                    
                    # If we have already seen this exact headline from another paper, skip it
                    if norm_title in seen_titles:
                        continue
                    
                    # Add to our tracker so we don't grab it again
                    seen_titles.add(norm_title)

                    # Append the cleaned article data to our master list
                    articles.append({
                        "title": title,
                        "source": feed["source"],
                        # Clean the HTML and truncate to 250 characters for a clean card layout
                        "summary": clean_html(description)[:250] + "...",
                        "link": link
                    })
        except Exception as e:
            # If a site is down or blocks us, print the error to the terminal but keep running the app
            print(f"Error fetching {feed['source']}: {e}")
            continue

    return articles