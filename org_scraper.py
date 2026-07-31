import requests
from bs4 import BeautifulSoup
import json

TARGET_ORGS = {
    "Mountain States Policy Center": {
        "url": "https://www.mountainstatespolicy.org/",
        "base_url": "https://www.mountainstatespolicy.org"
    },
    "ACLU of Wyoming": {
        "url": "https://www.aclu-wy.org/",
        "base_url": "https://www.aclu-wy.org"
    },
    "Wyoming Business Council": {
        "url": "https://wyomingbusiness.org/",
        "base_url": "https://wyomingbusiness.org"
    },
    "Wyoming Taxpayers Association": {
        "url": "https://wyotax.org/",
        "base_url": "https://wyotax.org"
    },
    "Wyoming Community Foundation": {
        "url": "https://wycf.org/",
        "base_url": "https://wycf.org"
    },
    "Wyoming Outdoor Council": {
        "url": "https://wyomingoutdoorcouncil.org/",
        "base_url": "https://wyomingoutdoorcouncil.org"
    }
}

def fetch_org_updates():
    results = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9'
    }

    for name, info in TARGET_ORGS.items():
        url = info["url"]
        org_data = {
            "organization": name,
            "url": url,
            "updates": []
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Extract primary headings and links as recent updates
                headlines = []
                for tag in soup.find_all(['h2', 'h3', 'h4']):
                    text = tag.get_text(strip=True)
                    # Exclude navigation clutter and short text
                    if text and len(text) > 15 and text not in headlines:
                        link_tag = tag.find('a') if tag.name != 'a' else tag
                        if not link_tag:
                            link_tag = tag.find_parent('a')
                        
                        href = link_tag['href'] if link_tag and 'href' in link_tag.attrs else url
                        if href.startswith('/'):
                            href = info["base_url"] + href
                            
                        headlines.append({"title": text, "link": href})
                        if len(headlines) >= 4:  # Cap at top 4 updates per organization
                            break
                
                org_data["updates"] = headlines if headlines else [{"title": "No major recent headlines detected.", "link": url}]
            else:
                org_data["updates"] = [{"title": f"Failed to retrieve data (HTTP {response.status_code})", "link": url}]
                
        except Exception as e:
            org_data["updates"] = [{"title": f"Error fetching updates: {str(e)}", "link": url}]
            
        results.append(org_data)
        
    return results

if __name__ == "__main__":
    test_run = fetch_org_updates()
    print(json.dumps(test_run, indent=2))