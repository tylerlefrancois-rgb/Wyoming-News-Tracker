import streamlit as st
from news_scraper import fetch_wyoming_news
from ai_processor import process_news
import os
import base64

st.set_page_config(layout="wide", page_title="Wyoming Policy Tracker")

# Helper function to load and encode local image for CSS background
def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

# Use dynamic absolute pathing to prevent working directory errors
current_dir = os.path.dirname(os.path.abspath(__file__))
bg_image_path = os.path.join(current_dir, "assets", "wyoming_landscape.jpg")

try:
    encoded_image = get_base64_of_bin_file(bg_image_path)
    bg_css = f"url(data:image/jpg;base64,{encoded_image})"
except FileNotFoundError:
    bg_css = "none" # Fallback if missing
    st.error(f"Image not found at: {bg_image_path}")

# --- CUSTOM CSS ---
st.markdown(f"""
<style>
    /* Main Background for the Entire App */
    .stApp {{
        background-image: linear-gradient(rgba(0, 0, 0, 0.3), rgba(0, 0, 0, 0.5)), {bg_css};
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }}

    /* Force global headers to pop against the image */
    h1, h2, h3 {{
        color: #ffffff !important;
        text-shadow: 2px 2px 5px rgba(0,0,0,0.8);
    }}

    /* Standardized Cards */
    .story-card, .policy-card {{
        background-color: rgba(255, 255, 255, 0.95);
        border-radius: 12px;
        padding: 25px;
        box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3), 0 4px 6px -2px rgba(0,0,0,0.2);
        margin-bottom: 25px;
        transition: transform 0.2s ease-in-out;
        color: #1e293b;
    }}
    
    .story-card:hover, .policy-card:hover {{
        transform: translateY(-5px);
    }}

    .story-card {{ border-top: 5px solid #00529b; }}
    .policy-card {{ border-top: 5px solid #10b981; }}

    /* Layout Grids */
    .top-stories-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
        gap: 25px;
        margin-bottom: 40px;
    }}

    /* Badges & Links */
    .badge {{
        display: inline-block;
        padding: 6px 12px;
        border-radius: 6px;
        background-color: #e2e8f0;
        color: #0f172a !important;
        font-size: 0.85em;
        text-decoration: none;
        font-weight: 600;
        margin-right: 8px;
        margin-top: 15px;
        text-shadow: none !important;
    }}
    .badge:hover {{ background-color: #cbd5e1; }}

    /* Card Content overrides to keep text dark inside white cards */
    .card-title {{
        margin-top: 0; margin-bottom: 12px;
        font-size: 1.25em; font-weight: 800;
        color: #0f172a !important; 
        line-height: 1.3;
        text-shadow: none !important;
    }}
    .card-summary {{
        font-size: 0.95em; color: #4b5563 !important;
        line-height: 1.6;
        text-shadow: none !important;
    }}

    /* --- THE HERO WELCOME CARD --- */
    /* Now acts as a semi-transparent glass panel over the main background */
    .hero-card {{
        background-color: rgba(15, 23, 42, 0.7);
        backdrop-filter: blur(4px);
        border-radius: 16px;
        padding: 80px 40px;
        color: white;
        text-align: center;
        box-shadow: 0 20px 25px -5px rgba(0,0,0,0.3), 0 10px 10px -5px rgba(0,0,0,0.2);
        margin-top: 30px;
        border: 1px solid rgba(255,255,255,0.15);
    }}
    .hero-card h1 {{
        font-size: 3.5em !important;
        font-weight: 900 !important; 
        margin-bottom: 20px;
    }}
    .hero-card p {{
        color: rgba(255,255,255,0.9) !important; font-size: 1.3em !important;
        max-width: 800px; margin: 0 auto 30px auto; line-height: 1.6;
        text-shadow: 1px 1px 3px rgba(0,0,0,0.5);
    }}
    .instruction-badge {{
        background-color: rgba(16, 185, 129, 0.9);
        color: white !important; padding: 10px 20px;
        border-radius: 30px; font-weight: 700;
        display: inline-block; font-size: 1.1em;
        text-shadow: none !important;
    }}
</style>
""", unsafe_allow_html=True)

# Application Header
st.markdown("""
<div style='text-align: left; padding-bottom: 20px;'>
    <h1 style='margin-bottom: 0;'>Wyoming Policy Tracker</h1>
    <p style='color: #f8fafc; text-shadow: 1px 1px 4px rgba(0,0,0,0.8); font-size: 1.1em; font-style: italic; margin-top: 5px;'>
        Aggregated News & Policy-Driven Insight for the Equality State
    </p>
</div>
""", unsafe_allow_html=True)

# CACHING
@st.cache_data(ttl=3600)
def get_cached_news():
    articles = fetch_wyoming_news()
    top_stories, policy_areas = process_news(articles)
    return top_stories, policy_areas

# Initialize Session State
if "analysis_complete" not in st.session_state:
    st.session_state.analysis_complete = False
    st.session_state.top_stories = []
    st.session_state.policy_areas = {}

# SIDEBAR
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/b/bc/Flag_of_Wyoming.svg", width=100)
    st.markdown("### 🏛️ Vital Resources")
    st.markdown("🔗 [Wyoming Legislature Calendar](https://wyoleg.gov/Calendar)")
    st.markdown("🔗 [Wyoming Liberty Group](https://wyliberty.org)")
    st.markdown("🔗 [WyLiberty Research](https://wylibertyresearch.org)")
    st.markdown("---")
    
    st.markdown("### 🔄 Control Panel")
    if st.button("Fetch & Analyze Latest News", type="primary", use_container_width=True):
        with st.spinner("Analyzing today's Wyoming news landscape..."):
            top_stories, policy_areas = get_cached_news()
            st.session_state.top_stories = top_stories
            st.session_state.policy_areas = policy_areas
            st.session_state.analysis_complete = True

def render_badges(story):
    badges_html = ""
    if 'sources' in story and 'links' in story:
        for idx, link in enumerate(story['links']):
            src_name = story['sources'][idx] if idx < len(story['sources']) else f"Source {idx+1}"
            badges_html += f'<a href="{link}" target="_blank" class="badge">{src_name}</a>'
    elif 'link' in story:
        src_name = story.get('source', 'View Source')
        badges_html += f'<a href="{story["link"]}" target="_blank" class="badge">{src_name}</a>'
    return badges_html

# ==============================================================================
# MAIN UI RENDERING
# ==============================================================================
if st.session_state.analysis_complete:
    
    search_query = st.text_input("🔍 Filter News by Keyword...", "").lower()
    
    st.markdown("<h2>🔥 The Top Wyoming Stories</h2>", unsafe_allow_html=True)
    
    grid_html = '<div class="top-stories-grid">\n'
    for story in st.session_state.top_stories:
        title = story.get('title', 'Headline')
        summary = story.get('summary', '').replace('[Source]', '').strip()
        
        if search_query and search_query not in title.lower() and search_query not in summary.lower():
            continue
            
        badges = render_badges(story)
        
        grid_html += f"""<div class="story-card">
<div class="card-title">{title}</div>
<div class="card-summary">{summary}</div>
{badges}
</div>\n"""
    
    grid_html += '</div>'
    st.markdown(grid_html, unsafe_allow_html=True)
    
    st.markdown("---")
    st.markdown("<h2>🏛️ Comprehensive Policy Breakdown</h2>", unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    cols = [col1, col2]
    
    for i, (policy_name, stories) in enumerate(st.session_state.policy_areas.items()):
        filtered_stories = [
            s for s in stories 
            if not search_query or search_query in s.get('title', '').lower() or search_query in s.get('summary', '').lower()
        ]
        
        if filtered_stories:
            with cols[i % 2]:
                st.markdown(f"<h3>{policy_name}</h3>", unsafe_allow_html=True)
                for story in filtered_stories:
                    title = story.get('title', 'Headline')
                    summary = story.get('summary', '').replace('[Source]', '').strip()
                    badges = render_badges(story)
                    
                    card_html = f"""<div class="policy-card">
<div class="card-title">{title}</div>
<div class="card-summary">{summary}</div>
{badges}
</div>"""
                    st.markdown(card_html, unsafe_allow_html=True)
else:
    # ==========================================================================
    # THE WELCOME HERO
    # ==========================================================================
    st.markdown("""
    <div class="hero-card">
        <h1>Wyoming Policy Insight</h1>
        <p>
            The Equality State's first automated news intelligence platform. We track the sources, 
            aggregate the coverage, and apply AI to break down exactly how today's news affects Wyoming policy.
        </p>
        <div class="instruction-badge">
            👈 Click "Fetch & Analyze" in the sidebar to begin.
        </div>
    </div>
    """, unsafe_allow_html=True)