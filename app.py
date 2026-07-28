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

# Initialize Session State
if "analysis_complete" not in st.session_state:
    st.session_state.analysis_complete = False
    st.session_state.top_stories = []
    st.session_state.policy_areas = {}

with st.sidebar:
    if st.button("Fetch & Analyze Latest News", type="primary"):
        with st.spinner("Fetching and analyzing data..."):
            articles = fetch_wyoming_news()
            top_stories, policy_areas = process_news(articles)
            
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
    st.markdown("## 🔥 Top 5 Wyoming Stories")
    
    # CSS Grid Layout for Top 5
    grid_html = '<div class="top-stories-grid">\n'
    for story in st.session_state.top_stories:
        title = story.get('title', 'Headline')
        summary = story.get('summary', '').replace('[Source]', '').strip()
        badges = render_badges(story)
        
        # No indentation here to prevent Streamlit from rendering it as a Markdown code block
        grid_html += f"""<div class="story-card">
<div class="card-title">{title}</div>
<div class="card-summary">{summary}</div>
{badges}
</div>\n"""
    
    grid_html += '</div>'
    st.markdown(grid_html, unsafe_allow_html=True)
    
    st.markdown("---")
    st.markdown("## 🏛️ Policy Area Breakdown")
    
    # Two-column layout for specific policy areas
    col1, col2 = st.columns(2)
    cols = [col1, col2]
    
    for i, (policy_name, stories) in enumerate(st.session_state.policy_areas.items()):
        with cols[i % 2]:
            st.markdown(f"### {policy_name}")
            for story in stories:
                title = story.get('title', 'Headline')
                summary = story.get('summary', '').replace('[Source]', '').strip()
                badges = render_badges(story)
                
                # No indentation here either
                card_html = f"""<div class="policy-card">
<div class="card-title">{title}</div>
<div class="card-summary">{summary}</div>
{badges}
</div>"""
                st.markdown(card_html, unsafe_allow_html=True)
else:
    st.info("Click the button in the sidebar to fetch today's news.")