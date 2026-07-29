import streamlit as st
from news_scraper import fetch_wyoming_news
from ai_processor import process_news

st.set_page_config(layout="wide", page_title="Wyoming Policy Tracker")

# Custom CSS for UI polish (cards, grids, badges)
st.markdown("""
<style>
    .story-card {
        background-color: #ffffff;
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 20px;
        border-top: 4px solid #00529b;
        color: #1e293b;
    }
    .policy-card {
        background-color: #ffffff;
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 20px;
        border-top: 4px solid #10b981;
        color: #1e293b;
    }
    .top-stories-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
        gap: 20px;
        margin-bottom: 30px;
    }
    .badge {
        display: inline-block;
        padding: 4px 8px;
        border-radius: 4px;
        background-color: #e2e8f0;
        color: #0f172a !important;
        font-size: 0.8em;
        text-decoration: none;
        font-weight: 600;
        margin-right: 5px;
        margin-top: 10px;
    }
    .badge:hover {
        background-color: #cbd5e1;
    }
    .card-title {
        margin-top: 0;
        margin-bottom: 10px;
        font-size: 1.1em;
        font-weight: 700;
    }
    .card-summary {
        font-size: 0.9em;
        color: #4b5563;
        line-height: 1.5;
    }
</style>
""", unsafe_allow_html=True)

st.title("Wyoming Policy Tracker")
st.markdown("Automated News Aggregation & AI Analysis")

# 1. CACHING ADDED HERE
# This prevents the app from burning API credits on every page interaction
@st.cache_data(ttl=3600) # Caches data for 1 hour
def get_cached_news():
    articles = fetch_wyoming_news()
    top_stories, policy_areas = process_news(articles)
    return top_stories, policy_areas

# Initialize Session State
if "analysis_complete" not in st.session_state:
    st.session_state.analysis_complete = False
    st.session_state.top_stories = []
    st.session_state.policy_areas = {}

# 2. SIDEBAR LINKS ADDED HERE
with st.sidebar:
    st.markdown("### 🏛️ Resources")
    st.markdown("🔗 [Wyoming Liberty Group](https://wyliberty.org)")
    st.markdown("🔗 [WyLiberty Research](https://wylibertyresearch.org)")
    st.markdown("---")
    
    if st.button("Fetch & Analyze Latest News", type="primary"):
        with st.spinner("Fetching and analyzing data..."):
            top_stories, policy_areas = get_cached_news()
            
            st.session_state.top_stories = top_stories
            st.session_state.policy_areas = policy_areas
            st.session_state.analysis_complete = True

def render_badges(story):
    """Helper to generate styled source links gracefully."""
    badges_html = ""
    if 'sources' in story and 'links' in story:
        for idx, link in enumerate(story['links']):
            src_name = story['sources'][idx] if idx < len(story['sources']) else f"Source {idx+1}"
            badges_html += f'<a href="{link}" target="_blank" class="badge">{src_name}</a>'
    elif 'link' in story:
        src_name = story.get('source', 'View Source')
        badges_html += f'<a href="{story["link"]}" target="_blank" class="badge">{src_name}</a>'
    return badges_html

# Main UI Rendering
if st.session_state.analysis_complete:
    
    # 3. SEARCH BAR ADDED HERE
    search_query = st.text_input("🔍 Search Policy News...", "").lower()
    
    st.markdown("## 🔥 Top 5 Wyoming Stories")
    
    # CSS Grid Layout for Top 5
    grid_html = '<div class="top-stories-grid">\n'
    for story in st.session_state.top_stories:
        title = story.get('title', 'Headline')
        summary = story.get('summary', '').replace('[Source]', '').strip()
        
        # Search Filter Logic for Top Stories
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
    st.markdown("## 🏛️ Policy Area Breakdown")
    
    col1, col2 = st.columns(2)
    cols = [col1, col2]
    
    for i, (policy_name, stories) in enumerate(st.session_state.policy_areas.items()):
        # Filter stories in this policy area by search query
        filtered_stories = [
            s for s in stories 
            if not search_query or search_query in s.get('title', '').lower() or search_query in s.get('summary', '').lower()
        ]
        
        # Only display the policy area if there are stories matching the search
        if filtered_stories:
            with cols[i % 2]:
                st.markdown(f"### {policy_name}")
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
    st.info("Click the button in the sidebar to fetch today's news.")