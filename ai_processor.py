import os
import json
from google import genai
from dotenv import load_dotenv

load_dotenv()
# Using the new SDK client syntax
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MODEL_NAME = "gemini-2.5-flash"

def analyze_policy_news(articles):
    """Analyzes articles for the 8 Wyoming Liberty Group policy areas."""
    if not articles:
        return {}
    
    content_payload = ""
    for i, art in enumerate(articles):
        title = art.get('title', 'No Title')
        source = art.get('source', 'Unknown')
        summary = art.get('summary', '')
        link = art.get('link', '#')
        content_payload += f"ID: {i}\nTitle: {title}\nSource: {source}\nSummary: {summary}\nLink: {link}\n\n"

    prompt = """
    You are a policy analyst for the Wyoming Liberty Group. 
    Analyze the provided news articles and categorize them strictly into these 8 policy areas:
    1. Energy & Natural Resources
    2. Economics & State Budget
    3. Government Transparency, Regulation & Legal Reform
    4. Education
    5. Marijuana / THC
    6. Health Care
    7. Campaign Finance & Election Integrity
    8. Criminal Justice

    You MUST return a JSON object containing ALL 8 of these exact keys, no matter what. 
    The value for each key should be a list of objects containing 'title', 'summary' (a brief 1-2 sentence explanation of the policy impact), 'link', and 'source'.
    If no articles fit a specific category, return an empty list [] for that key. Do not omit any of the 8 keys.
    Do not include any markdown formatting like ```json.
    """

    try:
        response = client.models.generate_content(
            model=MODEL_NAME, 
            contents=[prompt, content_payload]
        )
        response_text = response.text.strip()
        
        # Strip markdown if Gemini ignores instructions
        if response_text.startswith("```json"):
            response_text = response_text[7:-3]
        elif response_text.startswith("```"):
            response_text = response_text[3:-3]
            
        return json.loads(response_text)
    except Exception as e:
        print(f"Error during policy analysis: {e}")
        return {}

def get_top_wyoming_stories(articles):
    """Clusters articles to find the top 5 most heavily covered distinct stories."""
    if not articles:
        return []
    
    content_payload = ""
    for art in articles:
        title = art.get('title', 'No Title')
        source = art.get('source', 'Unknown')
        link = art.get('link', '#')
        content_payload += f"Title: {title}\nSource: {source}\nLink: {link}\n\n"

    prompt = """
    You are an expert Wyoming news editor. I am giving you a list of recent news headlines from various Wyoming outlets.
    Group the headlines by topic to find the consensus of what the media is covering most heavily right now.
    Identify the top 5 distinct news stories.
    
    Return ONLY a valid JSON array of exactly 5 objects. Each object must have:
    - 'title': A synthesized, professional headline for the overall story.
    - 'summary': A 2-sentence summary of what the story is about.
    - 'links': A list of URLs to the original articles covering this story (include up to 3 links).
    - 'sources': A list of the source names matching the URLs.
    
    Do not include any markdown formatting like ```json.
    """

    try:
        response = client.models.generate_content(
            model=MODEL_NAME, 
            contents=[prompt, content_payload]
        )
        response_text = response.text.strip()
        
        # Strip markdown if Gemini ignores instructions
        if response_text.startswith("```json"):
            response_text = response_text[7:-3]
        elif response_text.startswith("```"):
            response_text = response_text[3:-3]
            
        return json.loads(response_text)
    except Exception as e:
        print(f"Error during top stories clustering: {e}")
        return []

def process_news(articles):
    """Wrapper function expected by app.py to handle both analysis tasks."""
    top_stories = get_top_wyoming_stories(articles)
    policy_areas = analyze_policy_news(articles)
    return top_stories, policy_areas