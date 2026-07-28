import feedparser
import datetime
from email.utils import parsedate_to_datetime

# Define the dictionary of RSS feeds covering Wyoming policy, news, and regions
RSS_FEEDS = {
    "WyoFile": "https://wyofile.com/feed/",
    "Wyoming Public Media": "https://www.wyomingpublicmedia.org/local-news.rss",
    "Cowboy State Daily": "https://cowboystatedaily.com/feed/",
    "The Wyoming Truth": "https://wyomingtruth.org/feed/",
    "Wyoming Tribune Eagle": "https://www.wyomingnews.com/search/?f=rss&t=article&c=news/local&l=50&s=start_time&sd=desc",
    "Casper Star-Tribune": "https://trib.com/search/?f=rss&t=article&c=news&l=50&s=start_time&sd=desc",
    "Jackson Hole News&Guide": "https://www.jhnewsandguide.com/search/?f=rss&t=article&c=news&l=50&s=start_time&sd=desc",
    "Gillette News Record": "https://www.gillettenewsrecord.com/search/?f=rss&t=article&c=news&l=50&s=start_time&sd=desc",
    "Oil City News": "https://oilcity.news/feed/",
    "Powell Tribune": "https://www.powelltribune.com/rss",
    "Sheridan Media": "https://sheridanmedia.com/feed/"
}

def parse_wyoming_feeds(max_age_hours=48):
    """
    Scrapes the RSS feeds, filters for articles published within max_age_hours,
    and returns a structured list of dictionaries.
    """
    recent_articles = []
    
    # Get the current time with timezone awareness (UTC)
    now = datetime.datetime.now(datetime.timezone.utc)
    
    for source_name, feed_url in RSS_FEEDS.items():
        print(f"Parsing feed: {source_name}...")
        try:
            feed = feedparser.parse(feed_url)
            
            for entry in feed.entries:
                # Attempt to extract and parse the publication date
                published_str = entry.get('published', entry.get('updated', None))
                
                if not published_str:
                    continue
                
                try:
                    # Parse the string into a timezone-aware datetime object
                    published_dt = parsedate_to_datetime(published_str)
                except Exception:
                    continue
                
                # Ensure the parsed date is in UTC for accurate comparison
                if published_dt.tzinfo is None:
                    published_dt = published_dt.replace(tzinfo=datetime.timezone.utc)
                    
                # Calculate the age of the article
                time_difference = now - published_dt
                age_in_hours = time_difference.total_seconds() / 3600
                
                # If the article is newer than the max age, add it to our payload
                if 0 <= age_in_hours <= max_age_hours:
                    article_data = {
                        "source": source_name,
                        "title": entry.get('title', 'No Title'),
                        "link": entry.get('link', ''),
                        "summary": entry.get('summary', entry.get('description', '')),
                        "published_date": published_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
                    }
                    recent_articles.append(article_data)
                    
        except Exception as e:
            print(f"Error parsing {source_name}: {e}")
            
    # Sort the final list by publication date, newest first
    recent_articles.sort(key=lambda x: x['published_date'], reverse=True)
    
    return recent_articles

if __name__ == "__main__":
    # Test the feed parser by running this script directly
    print("Starting feed parser...")
    articles = parse_wyoming_feeds(max_age_hours=48)
    
    print(f"\nFound {len(articles)} articles published in the last 48 hours.\n")
    for article in articles:
        print(f"[{article['source']}] {article['title']}")
        print(f"URL: {article['link']}\n")