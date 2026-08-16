import base64
import html
import os
from datetime import datetime
from urllib.parse import urlparse

import streamlit as st

from ai_processor import NEWS_CATEGORIES, OTHER_NEWS_CATEGORY, POLICY_AREAS, process_news
from news_scraper import fetch_wyoming_news
from org_scraper import fetch_org_updates


PUBLIC_PROCESSING_NOTICE = (
    "Current verified Wyoming coverage is shown below. "
    "Some AI categorization is temporarily limited; uncertain items remain available in Other News."
)

st.set_page_config(
    layout="wide",
    page_title="Wyoming Policy News Tracker",
)


def get_base64_of_bin_file(bin_file: str) -> str:
    with open(bin_file, "rb") as file_handle:
        return base64.b64encode(file_handle.read()).decode()


def safe_text(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def safe_url(value: object) -> str:
    candidate = str(value or "").strip()
    try:
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return html.escape(candidate, quote=True)
    except Exception:
        pass
    return "#"


def display_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone().strftime("%b %d, %Y at %I:%M %p")
    except Exception:
        return "Date unavailable"


current_dir = os.path.dirname(os.path.abspath(__file__))
bg_image_path = os.path.join(current_dir, "assets", "wyoming_landscape.jpg")

try:
    encoded_image = get_base64_of_bin_file(bg_image_path)
    bg_css = f"url(data:image/jpg;base64,{encoded_image})"
except FileNotFoundError:
    bg_css = "none"

st.markdown(
    f"""
<style>
    .stApp {{
        background-image: linear-gradient(rgba(0, 0, 0, 0.42), rgba(0, 0, 0, 0.62)), {bg_css};
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }}

    h1, h2, h3 {{
        color: #ffffff !important;
        text-shadow: 2px 2px 5px rgba(0, 0, 0, 0.82);
    }}

    .story-card, .policy-card, .org-card {{
        background-color: rgba(255, 255, 255, 0.97);
        border-radius: 12px;
        padding: 24px;
        box-shadow: 0 10px 18px rgba(0, 0, 0, 0.28);
        margin-bottom: 22px;
        color: #1e293b;
        transition: transform 0.18s ease, box-shadow 0.18s ease;
    }}

    .story-card:hover, .policy-card:hover, .org-card:hover {{
        transform: translateY(-3px);
        box-shadow: 0 14px 24px rgba(0, 0, 0, 0.34);
    }}

    .story-card {{ border-top: 5px solid #00529b; }}
    .policy-card {{ border-top: 5px solid #10b981; }}
    .org-card {{ border-top: 5px solid #f59e0b; }}

    .top-stories-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
        gap: 22px;
        margin-bottom: 34px;
    }}

    .badge {{
        display: inline-block;
        padding: 7px 12px;
        border-radius: 6px;
        background-color: #e2e8f0;
        color: #0f172a !important;
        font-size: 0.84rem;
        text-decoration: none;
        font-weight: 700;
        margin: 13px 7px 0 0;
    }}

    .badge:hover {{ background-color: #cbd5e1; }}

    .card-title {{
        margin: 0 0 12px 0;
        font-size: 1.38rem;
        font-weight: 850;
        color: #0f172a !important;
        line-height: 1.34;
    }}

    .card-meta {{
        margin-bottom: 14px;
        color: #334155 !important;
        font-size: 0.95rem;
        font-weight: 750;
        line-height: 1.45;
    }}

    .card-summary {{
        color: #172033 !important;
        font-size: 1.08rem;
        line-height: 1.72;
        font-weight: 520;
    }}

    .org-list {{
        margin: 10px 0;
        padding-left: 20px;
        color: #334155;
    }}

    .org-list li {{ margin-bottom: 8px; line-height: 1.4; }}
    .org-list a {{ color: #0284c7; text-decoration: none; font-weight: 650; }}
    .org-list a:hover {{ text-decoration: underline; }}

    .hero-card {{
        background-color: rgba(15, 23, 42, 0.78);
        backdrop-filter: blur(5px);
        border-radius: 16px;
        padding: 62px 36px;
        color: white;
        text-align: center;
        box-shadow: 0 20px 25px rgba(0, 0, 0, 0.28);
        margin-top: 24px;
        border: 1px solid rgba(255, 255, 255, 0.16);
    }}

    .hero-card h1 {{ font-size: 3rem !important; margin-bottom: 18px; }}
    .hero-card p {{
        color: rgba(255, 255, 255, 0.92) !important;
        font-size: 1.16rem !important;
        max-width: 850px;
        margin: 0 auto 25px auto;
        line-height: 1.65;
    }}

    .instruction-badge {{
        background-color: rgba(16, 185, 129, 0.95);
        color: white !important;
        padding: 10px 20px;
        border-radius: 30px;
        font-weight: 750;
        display: inline-block;
    }}

    [data-testid="stMetric"] {{
        background: rgba(255, 255, 255, 0.94);
        border-radius: 10px;
        padding: 12px 16px;
    }}

    div[data-testid="stAlert"] {{
        background: rgba(255, 255, 255, 0.93);
        border-radius: 10px;
    }}
</style>
""",
    unsafe_allow_html=True,
)

# WYOMING_POLICY_NEWS_TRACKER_CONTRAST_START
st.markdown(
    """
<style>
    .story-card,
    .policy-card,
    .org-card {
        background-color: rgba(255, 255, 255, 0.99) !important;
        border: 3px solid #020617 !important;
        border-radius: 12px !important;
        box-shadow:
            0 16px 30px rgba(0, 0, 0, 0.48),
            0 3px 8px rgba(0, 0, 0, 0.30) !important;
        color: #020617 !important;
    }

    .story-card {
        border-top: 7px solid #082f5b !important;
    }

    .policy-card {
        border-top: 7px solid #065f46 !important;
    }

    .org-card {
        border-top: 7px solid #78350f !important;
    }

    .card-title {
        color: #020617 !important;
        font-weight: 850 !important;
    }

    .card-meta {
        color: #334155 !important;
        font-weight: 700 !important;
    }

    .card-summary {
        color: #1e293b !important;
        font-weight: 500 !important;
    }

    [data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.99) !important;
        border: 3px solid #020617 !important;
        border-radius: 11px !important;
        box-shadow:
            0 14px 26px rgba(0, 0, 0, 0.42),
            0 2px 6px rgba(0, 0, 0, 0.26) !important;
    }

    [data-testid="stMetricLabel"] {
        color: #334155 !important;
        font-weight: 750 !important;
    }

    [data-testid="stMetricValue"] {
        color: #020617 !important;
        font-weight: 850 !important;
    }

    div[data-baseweb="input"] {
        border: 2px solid #0f172a !important;
        border-radius: 8px !important;
        background: rgba(255, 255, 255, 0.99) !important;
    }
</style>
""",
    unsafe_allow_html=True,
)
# WYOMING_POLICY_NEWS_TRACKER_CONTRAST_END

# WYOMING_POLICY_NEWS_TRACKER_EASY_READ_V6_START
st.markdown(
    """
<style>
    /* Larger, clearer general interface text */
    [data-testid="stSidebar"] {
        background: rgba(248, 250, 252, 0.985) !important;
        border-right: 3px solid #0f172a !important;
    }

    [data-testid="stSidebar"] h3 {
        color: #0f172a !important;
        text-shadow: none !important;
        font-size: 1.28rem !important;
        line-height: 1.3 !important;
    }

    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] span {
        font-size: 1.03rem !important;
        line-height: 1.45 !important;
    }

    [data-testid="stSidebar"] a {
        font-size: 1.02rem !important;
        font-weight: 700 !important;
    }

    .stButton > button {
        min-height: 52px !important;
        font-size: 1.08rem !important;
        font-weight: 850 !important;
        border: 2px solid #0f172a !important;
    }

    div[data-baseweb="select"] > div,
    div[data-baseweb="input"] > div {
        min-height: 50px !important;
        font-size: 1.06rem !important;
    }

    div[data-baseweb="select"] span,
    div[data-baseweb="input"] input {
        font-size: 1.06rem !important;
        color: #0f172a !important;
        font-weight: 650 !important;
    }

    [data-testid="stWidgetLabel"] p {
        font-size: 1.08rem !important;
        font-weight: 800 !important;
        color: #f8fafc !important;
    }

    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
        color: #0f172a !important;
    }

    .easy-guide {
        background: #ffffff;
        border: 3px solid #0f172a;
        border-left: 9px solid #065f46;
        border-radius: 12px;
        padding: 18px 22px;
        margin: 8px 0 22px 0;
        box-shadow: 0 10px 20px rgba(0,0,0,0.26);
        color: #0f172a;
    }

    .easy-guide-title {
        font-size: 1.35rem;
        line-height: 1.25;
        font-weight: 900;
        color: #0f172a;
        margin-bottom: 10px;
    }

    .easy-guide-step {
        font-size: 1.08rem;
        line-height: 1.58;
        color: #172033;
        margin: 5px 0;
        font-weight: 620;
    }

    .easy-guide-note {
        font-size: 0.98rem;
        line-height: 1.5;
        color: #334155;
        margin-top: 10px;
        font-weight: 600;
    }

    .browse-heading {
        background: #ffffff;
        border: 3px solid #0f172a;
        border-radius: 12px;
        padding: 16px 20px;
        margin: 18px 0 14px 0;
        color: #0f172a;
        box-shadow: 0 8px 18px rgba(0,0,0,0.22);
    }

    .browse-heading strong {
        font-size: 1.25rem;
        color: #0f172a;
    }

    .browse-heading span {
        display: block;
        margin-top: 5px;
        font-size: 1.03rem;
        color: #334155;
        font-weight: 600;
    }

    div[data-testid="stCaptionContainer"] p {
        font-size: 0.98rem !important;
        line-height: 1.5 !important;
        color: #f8fafc !important;
        font-weight: 650 !important;
    }

    [data-testid="stMetricLabel"] p {
        font-size: 1.02rem !important;
    }

    [data-testid="stMetricValue"] {
        font-size: 2rem !important;
    }

    .badge {
        font-size: 0.98rem !important;
        padding: 9px 13px !important;
    }

    /* Strong keyboard focus */
    button:focus,
    input:focus,
    [role="combobox"]:focus {
        outline: 4px solid #f59e0b !important;
        outline-offset: 2px !important;
    }
</style>
""",
    unsafe_allow_html=True,
)
# WYOMING_POLICY_NEWS_TRACKER_EASY_READ_V6_END

# WYOMING_POLICY_NEWS_TRACKER_SIDEBAR_CONTRAST_V61_START
st.markdown(
    """
<style>
    /* Force all sidebar instructional text to remain readable */
    [data-testid="stSidebar"] {
        color: #0f172a !important;
    }

    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] div {
        color: #0f172a !important;
    }

    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
        color: #334155 !important;
        font-size: 1rem !important;
        font-weight: 650 !important;
        line-height: 1.45 !important;
    }

    [data-testid="stSidebar"] [role="radiogroup"] label,
    [data-testid="stSidebar"] [role="radiogroup"] span {
        color: #0f172a !important;
        font-weight: 700 !important;
    }

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        color: #0f172a !important;
    }

    [data-testid="stSidebar"] a {
        color: #2563eb !important;
        font-weight: 750 !important;
    }

    /* Keep button text white */
    [data-testid="stSidebar"] .stButton button,
    [data-testid="stSidebar"] .stButton button p {
        color: #ffffff !important;
    }
</style>
""",
    unsafe_allow_html=True,
)
# WYOMING_POLICY_NEWS_TRACKER_SIDEBAR_CONTRAST_V61_END
st.markdown(
    """
<div style="text-align:left; padding-bottom:18px;">
    <h1 style="margin-bottom:0;">Wyoming Policy News Tracker</h1>
    <p style="color:#f8fafc; text-shadow:1px 1px 4px rgba(0,0,0,0.8); font-size:1.08rem; font-style:italic; margin-top:5px;">
        Current Wyoming policy news with verified source links and clear policy context
    </p>
</div>
""",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=1800, show_spinner=False)
def get_cached_news(max_age_hours: int):
    articles, diagnostics = fetch_wyoming_news(max_age_hours=max_age_hours)
    top_stories, policy_areas, processing_metadata = process_news(articles)
    return articles, diagnostics, top_stories, policy_areas, processing_metadata


if "analysis_complete" not in st.session_state:
    st.session_state.analysis_complete = False
    st.session_state.articles = []
    st.session_state.diagnostics = {}
    st.session_state.top_stories = []
    st.session_state.policy_areas = {area: [] for area in NEWS_CATEGORIES}
    st.session_state.processing_metadata = {}
    st.session_state.analysis_time = ""

if "org_fetched" not in st.session_state:
    st.session_state.org_fetched = False
    st.session_state.org_updates = []

window_options = {
    "Last 48 hours": 48,
    "Last 72 hours": 72,
    "Last 5 days": 120,
    "Last 7 days": 168,
}

with st.sidebar:
    st.image(
        "https://upload.wikimedia.org/wikipedia/commons/b/bc/Flag_of_Wyoming.svg",
        width=100,
    )

    st.markdown("### 1. Choose what you want to see")
    view_mode = st.radio(
        "News or organization updates",
        ["Latest News", "Organization Updates"],
        help="Choose Latest News to browse Wyoming news by category.",
    )

    st.markdown("---")
    st.markdown("### 2. Choose how far back to look")

    if view_mode == "Latest News":
        selected_window = st.selectbox(
            "How many days of news?",
            list(window_options.keys()),
            index=2,
            help="Last 5 days is a good starting point.",
        )
        force_refresh = st.checkbox(
            "Get a completely fresh update",
            value=False,
            help=(
                "Leave this unchecked for normal use. Check it only when you want "
                "the tracker to ignore saved results and check the sources again."
            ),
        )

        st.markdown("### 3. Start the update")
        st.caption("Click the blue button below. The tracker will collect and sort the news for you.")

        if st.button(
            "UPDATE WYOMING NEWS",
            type="primary",
            use_container_width=True,
        ):
            if force_refresh:
                get_cached_news.clear()

            with st.spinner("Collecting and categorizing current Wyoming coverage..."):
                try:
                    (
                        articles,
                        diagnostics,
                        top_stories,
                        policy_areas,
                        processing_metadata,
                    ) = get_cached_news(window_options[selected_window])

                    st.session_state.articles = articles
                    st.session_state.diagnostics = diagnostics
                    st.session_state.top_stories = top_stories
                    st.session_state.policy_areas = policy_areas
                    st.session_state.processing_metadata = processing_metadata
                    st.session_state.analysis_time = datetime.now().astimezone().isoformat()
                    st.session_state.analysis_complete = True
                except Exception:
                    st.warning(
                        "Policy news could not be updated right now. "
                        "Please try again shortly."
                    )

    else:
        st.markdown("### 3. Start the update")
        st.caption("Click the blue button below to check the organization pages.")
        if st.button(
            "CHECK ORGANIZATION UPDATES",
            type="primary",
            use_container_width=True,
        ):
            with st.spinner("Checking target organization pages..."):
                st.session_state.org_updates = fetch_org_updates()
                st.session_state.org_fetched = True

    st.markdown("---")
    st.markdown("### Vital Resources")
    st.markdown(
        "[WYLIB Legislative Calendar](https://wylib-wyocal-production.up.railway.app)"
    )
    st.markdown("[Wyoming Liberty Research](https://wylibertyresearch.org)")


def render_badges(story: dict) -> str:
    badges: list[str] = []

    if story.get("links"):
        sources = story.get("sources", [])
        for index, link in enumerate(story["links"]):
            source = sources[index] if index < len(sources) else f"Source {index + 1}"
            badges.append(
                f'<a href="{safe_url(link)}" target="_blank" '
                f'rel="noopener noreferrer" class="badge">{safe_text(source)}</a>'
            )
    elif story.get("link"):
        source = story.get("source", "View Source")
        badges.append(
            f'<a href="{safe_url(story["link"])}" target="_blank" '
            f'rel="noopener noreferrer" class="badge">{safe_text(source)}</a>'
        )

    return "".join(badges)


if view_mode == "Latest News":
    if st.session_state.analysis_complete:
        diagnostics = st.session_state.diagnostics
        processing_metadata = st.session_state.processing_metadata

        metric_columns = st.columns(3)
        metric_columns[0].metric("Articles reviewed", len(st.session_state.articles))
        metric_columns[1].metric(
            "Sources reporting",
            diagnostics.get("sources_with_recent_items", 0),
        )
        metric_columns[2].metric(
            "Categorized stories",
            sum(
                len(st.session_state.policy_areas.get(category, []))
                for category in NEWS_CATEGORIES
            ),
        )

        refresh_label = display_date(st.session_state.analysis_time)
        st.caption(
            f"Policy news updated {refresh_label}. "
            "Results are reused for 30 minutes unless sources are checked again."
        )

        if processing_metadata.get("used_fallback"):
            st.info(PUBLIC_PROCESSING_NOTICE)

        st.markdown(
            """
<div class="easy-guide">
    <div class="easy-guide-title">How to find the news you want</div>
    <div class="easy-guide-step"><strong>Step 1:</strong> Pick a news category below.</div>
    <div class="easy-guide-step"><strong>Step 2:</strong> Read the stories shown for that category.</div>
    <div class="easy-guide-step"><strong>Step 3 (optional):</strong> Type a word, name, place, or topic in the search box to narrow the list.</div>
    <div class="easy-guide-note">You only see one category at a time, so the page stays short and easy to read.</div>
</div>
""",
            unsafe_allow_html=True,
        )

        st.markdown("## Browse Wyoming News")

        category_counts = {
            category: len(st.session_state.policy_areas.get(category, []))
            for category in NEWS_CATEGORIES
        }
        total_categorized = sum(category_counts.values())

        st.caption(
            f"{total_categorized} current Wyoming stories are organized into the "
            "eight research policy areas plus Other News. Choose one category at a time."
        )

        st.markdown(
            """
<div class="browse-heading">
    <strong>STEP 1: Choose a category</strong>
    <span>Click the box below and choose the kind of news you want to read.</span>
</div>
""",
            unsafe_allow_html=True,
        )

        selected_category = st.selectbox(
            "News category",
            NEWS_CATEGORIES,
            format_func=lambda category: f"{category} ({category_counts.get(category, 0)} stories)",
            key="news_category_v6",
            help="The number in parentheses tells you how many current stories are in that category.",
        )

        st.markdown(
            """
<div class="browse-heading">
    <strong>STEP 2: Search this category (optional)</strong>
    <span>You can leave this blank. Or type a word such as school, taxes, election, hospital, Casper, or a person's name.</span>
</div>
""",
            unsafe_allow_html=True,
        )

        search_query = st.text_input(
            "Type a word to search",
            "",
            key="news_category_search_v6",
            placeholder="Example: school, taxes, election, hospital, Casper...",
            help="This searches only inside the category you selected above.",
        ).lower().strip()

        selected_stories = list(
            st.session_state.policy_areas.get(selected_category, [])
        )
        filtered_stories = [
            story
            for story in selected_stories
            if not search_query
            or search_query in str(story.get("title", "")).lower()
            or search_query in str(story.get("summary", "")).lower()
            or search_query in str(story.get("source_label", story.get("source", ""))).lower()
        ]

        st.markdown(
            f"### {safe_text(selected_category)} "
            f"({len(filtered_stories)} {'story' if len(filtered_stories) == 1 else 'stories'})",
            unsafe_allow_html=True,
        )

        PAGE_SIZE = 6
        page_count = max(1, (len(filtered_stories) + PAGE_SIZE - 1) // PAGE_SIZE)

        if page_count > 1:
            selected_page = st.selectbox(
                "More stories",
                list(range(1, page_count + 1)),
                format_func=lambda page: f"Showing page {page} of {page_count}",
                key=f"news_page_v6_{selected_category}",
                help="Each page shows up to 6 stories so you do not have to scroll through a long list.",
            )
        else:
            selected_page = 1

        start_index = (selected_page - 1) * PAGE_SIZE
        visible_stories = filtered_stories[start_index : start_index + PAGE_SIZE]

        if visible_stories:
            columns = st.columns(2)
            for index, story in enumerate(visible_stories):
                source_label = story.get(
                    "source_label",
                    story.get("source", "Unknown source"),
                )
                with columns[index % 2]:
                    st.markdown(
                        '<div class="policy-card">'
                        f'<div class="card-title">{safe_text(story.get("title", "Headline"))}</div>'
                        f'<div class="card-meta">{safe_text(source_label)} &middot; '
                        f'{safe_text(display_date(story.get("published_at", "")))}</div>'
                        f'<div class="card-summary">{safe_text(story.get("summary", ""))}</div>'
                        f'{render_badges(story)}'
                        "</div>",
                        unsafe_allow_html=True,
                    )
        else:
            st.info("No current stories matched this category and keyword filter.")

        if st.session_state.top_stories:
            with st.expander(
                f"Top Wyoming Stories ({len(st.session_state.top_stories)})",
                expanded=False,
            ):
                top_columns = st.columns(2)
                for index, story in enumerate(st.session_state.top_stories):
                    with top_columns[index % 2]:
                        st.markdown(
                            '<div class="story-card">'
                            f'<div class="card-title">{safe_text(story.get("title", "Headline"))}</div>'
                            f'<div class="card-meta">Latest supporting item: '
                            f'{safe_text(display_date(story.get("latest_published_at", "")))}</div>'
                            f'<div class="card-summary">{safe_text(story.get("summary", ""))}</div>'
                            f'{render_badges(story)}'
                            "</div>",
                            unsafe_allow_html=True,
                        )

    else:
        st.markdown(
            """
<div class="hero-card">
    <h1>Wyoming Policy News</h1>
    <p>
        Use the panel on the left to load current Wyoming news. The tracker will sort
        the stories into the eight Wyoming Liberty policy areas plus Other News.
    </p>
    <div class="instruction-badge">
        1. Choose how many days &nbsp; 2. Click UPDATE WYOMING NEWS &nbsp; 3. Pick a category
    </div>
</div>
""",
            unsafe_allow_html=True,
        )

elif view_mode == "Organization Updates":
    if st.session_state.org_fetched:
        st.markdown("## Organization Policy Radar")

        cards: list[str] = []
        for organization in st.session_state.org_updates:
            name = organization.get("organization", "Unknown")
            org_url = organization.get("url", "#")
            updates = organization.get("updates", [])

            bullets = []
            for item in updates:
                bullets.append(
                    f'<li><a href="{safe_url(item.get("link"))}" target="_blank" '
                    f'rel="noopener noreferrer">{safe_text(item.get("title"))}</a></li>'
                )

            cards.append(
                '<div class="org-card">'
                f'<div class="card-title">{safe_text(name)}</div>'
                '<div class="card-summary"><strong>Recent detected headings:</strong>'
                f'<ul class="org-list">{"".join(bullets)}</ul></div>'
                f'<a href="{safe_url(org_url)}" target="_blank" '
                'rel="noopener noreferrer" class="badge">Visit Main Site</a>'
                "</div>"
            )

        st.markdown(
            '<div class="top-stories-grid">' + "".join(cards) + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
<div class="hero-card">
    <h1>Organization Radar</h1>
    <p>
        Check selected Wyoming policy and community organization pages for recent
        visible headings and links.
    </p>
    <div class="instruction-badge">
        Use the sidebar to check organization updates.
    </div>
</div>
""",
            unsafe_allow_html=True,
        )


