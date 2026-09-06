import streamlit as st
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from pathlib import Path
from datetime import datetime
from analyzer import analyze_emails_batch, add_to_calendar

# -----------------------------------------------------------------------------
# 1. Page Config & Modern SaaS Styling
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="InboxPilot | AI Intelligence Hub",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Theme: Linear/Vercel slate palette, Inter typography, micro-borders
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: #0f172a;
    }

    /* Remove default Streamlit top blank padding */
    .block-container {
        padding-top: 1.75rem;
        padding-bottom: 3rem;
        max-width: 1200px;
    }

    /* Metric Cards */
    .metric-box {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1rem 1.25rem;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
    }
    .metric-label {
        font-size: 0.75rem;
        font-weight: 600;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .metric-value {
        font-size: 1.6rem;
        font-weight: 700;
        color: #0f172a;
        margin-top: 0.2rem;
    }

    /* Event & Digest Card Container */
    .dashboard-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1rem;
        transition: all 0.15s ease;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
    }
    .dashboard-card:hover {
        border-color: #cbd5e1;
        box-shadow: 0 6px 16px rgba(0, 0, 0, 0.05);
    }

    /* Pill Badges */
    .badge {
        display: inline-flex;
        align-items: center;
        font-size: 0.72rem;
        font-weight: 600;
        padding: 3px 9px;
        border-radius: 9999px;
        letter-spacing: 0.02em;
    }
    .badge-topic {
        background: #f1f5f9;
        color: #334155;
        border: 1px solid #e2e8f0;
    }
    .badge-event {
        background: #eff6ff;
        color: #2563eb;
        border: 1px solid #bfdbfe;
    }

    /* Highlight Banner for Scheduled Events */
    .event-banner {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-left: 4px solid #3b82f6;
        border-radius: 6px;
        padding: 10px 14px;
        margin: 12px 0;
        display: flex;
        flex-direction: column;
        gap: 3px;
    }

    /* Modern Buttons */
    div.stButton > button {
        border-radius: 8px;
        font-weight: 500;
        font-size: 0.9rem;
        transition: all 0.15s ease;
    }
    div.stButton > button:hover {
        border-color: #94a3b8;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. Session State & Authentication Setup
# -----------------------------------------------------------------------------
CLIENT_SECRETS_FILE = str(Path(__file__).parent / "client_secret.json")
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar.events'
]
REDIRECT_URI = "http://localhost:8501"

if "credentials" not in st.session_state:
    st.session_state.credentials = None
if "scan_results" not in st.session_state:
    st.session_state.scan_results = []
if "synced_events" not in st.session_state:
    st.session_state.synced_events = set()
if "total_scanned_count" not in st.session_state:
    st.session_state.total_scanned_count = 0

def get_auth_url():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    with open("verifier.txt", "w") as f:
        f.write(flow.code_verifier)
    return auth_url

# OAuth Callback Handler
query_params = st.query_params
if "code" in query_params and not st.session_state.credentials:
    code = query_params["code"]
    try:
        with open("verifier.txt", "r") as f:
            saved_verifier = f.read().strip()
    except FileNotFoundError:
        st.error("Authentication expired. Please log in again.")
        st.stop()

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(code=code, code_verifier=saved_verifier)
    st.session_state.credentials = flow.credentials
    st.query_params.clear()
    st.rerun()

def fetch_recent_emails(gmail_service, max_results=10):
    results = gmail_service.users().messages().list(
        userId='me', q='newer_than:7d', maxResults=max_results
    ).execute()
    messages = results.get('messages', [])
    
    fetched = []
    for msg in messages:
        full_msg = gmail_service.users().messages().get(
            userId='me', id=msg['id'], format='full'
        ).execute()
        snippet = full_msg.get('snippet', '')
        payload = full_msg.get('payload', {})
        headers = {h['name']: h['value'] for h in payload.get('headers', [])}
        
        fetched.append({
            'id': msg['id'],
            'subject': headers.get('Subject', 'No Subject'),
            'sender': headers.get('From', 'Unknown Sender'),
            'snippet': snippet
        })
    return fetched

# -----------------------------------------------------------------------------
# 3. Sidebar Command Center
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚡ **InboxPilot**")
    st.caption("Context-Aware Email Triage & Calendar Sync Engine")
    st.divider()

    st.markdown("**⚙️ Configuration**")
    interests_input = st.text_area(
        "Focus Topics",
        value="Hackathons, Tech Talks, Workshops, AI Meetups, College Seminars",
        help="InboxPilot evaluates all incoming correspondence against these topics."
    )
    interest_list = [t.strip() for t in interests_input.split(",") if t.strip()]

    email_count_limit = st.slider("Inbox Depth (Messages)", min_value=5, max_value=20, value=8)

    st.divider()

    if not st.session_state.credentials:
        auth_url = get_auth_url()
        st.link_button("🔗 Connect Google Account", auth_url, use_container_width=True)
    else:
        st.success("🟢 Google Services Connected")
        if st.button("Disconnect Account", use_container_width=True):
            st.session_state.credentials = None
            st.session_state.scan_results = []
            st.session_state.synced_events = set()
            st.session_state.total_scanned_count = 0
            st.rerun()

# -----------------------------------------------------------------------------
# 4. Top Analytics Bar
# -----------------------------------------------------------------------------
matched_threads = st.session_state.scan_results
actionable_events = [m for m in matched_threads if m["analysis"].is_calendar_event]
synced_count = len(st.session_state.synced_events)

col_m1, col_m2, col_m3, col_m4 = st.columns(4)

with col_m1:
    st.markdown(f"""
    <div class="metric-box">
        <div class="metric-label">Threads Scanned</div>
        <div class="metric-value">{st.session_state.total_scanned_count}</div>
    </div>
    """, unsafe_allow_html=True)

with col_m2:
    st.markdown(f"""
    <div class="metric-box">
        <div class="metric-label">Relevant Matches</div>
        <div class="metric-value">{len(matched_threads)}</div>
    </div>
    """, unsafe_allow_html=True)

with col_m3:
    st.markdown(f"""
    <div class="metric-box">
        <div class="metric-label">Detected Events</div>
        <div class="metric-value">{len(actionable_events)}</div>
    </div>
    """, unsafe_allow_html=True)

with col_m4:
    st.markdown(f"""
    <div class="metric-box">
        <div class="metric-label">Calendar Syncs</div>
        <div class="metric-value">{synced_count}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 5. Primary Control Deck & Batch Runner
# -----------------------------------------------------------------------------
action_col1, action_col2 = st.columns([3, 1])

with action_col1:
    st.markdown("#### **Active Triage Feed**")
    st.caption("Emails categorized by topic alignment, actionable dates, and executive summaries.")

with action_col2:
    if st.session_state.credentials:
        trigger_scan = st.button("⚡ Run Inbox Scan", type="primary", use_container_width=True)
    else:
        trigger_scan = False

if trigger_scan:
    with st.status("Analyzing inbox...", expanded=True) as status_box:
        st.write("Fetching messages via Gmail API...")
        gmail = build('gmail', 'v1', credentials=st.session_state.credentials)
        raw_emails = fetch_recent_emails(gmail, max_results=email_count_limit)
        st.session_state.total_scanned_count = len(raw_emails)

        st.write("Executing high-speed batch context parsing...")
        analyses = analyze_emails_batch(raw_emails, interest_list)

        analysis_map = {a.id: a for a in analyses}
        processed = []
        for email in raw_emails:
            an = analysis_map.get(email["id"])
            if an and an.is_relevant:
                processed.append({
                    "id": email["id"],
                    "subject": email["subject"],
                    "sender": email["sender"],
                    "analysis": an
                })

        st.session_state.scan_results = processed
        status_box.update(label=f"Done — Identified {len(processed)} relevant threads", state="complete", expanded=False)
        st.rerun()

# -----------------------------------------------------------------------------
# 6. Tabbed Dashboard Feed
# -----------------------------------------------------------------------------
if not st.session_state.credentials:
    st.info("👋 Welcome! Connect your Google Account using the sidebar to begin syncing events.")
elif not st.session_state.scan_results:
    st.info("No scanned threads yet. Tap **⚡ Run Inbox Scan** above to process your inbox.")
else:
    tab1, tab2, tab3 = st.tabs([
        f"🎯 All Matches ({len(matched_threads)})",
        f"📅 Events to Sync ({len(actionable_events)})",
        f"📝 Summaries Only ({len(matched_threads) - len(actionable_events)})"
    ])

    def render_card(item):
        email_id = item["id"]
        analysis = item["analysis"]
        sender_clean = item['sender'].replace('<', '&lt;').replace('>', '&gt;')

        event_markup = ""
        if analysis.is_calendar_event and analysis.start_time:
            loc_text = f" &nbsp;•&nbsp; 📍 {analysis.location}" if analysis.location else ""
            event_markup = f"""
            <div class="event-banner">
                <div style="font-weight: 600; font-size: 0.88rem; color: #1e3a8a;">
                    🗓️ {analysis.event_title or 'Scheduled Event'}
                </div>
                <div style="font-size: 0.8rem; color: #475569;">
                    ⏰ {analysis.start_time.replace('T', ' ')}{loc_text}
                </div>
            </div>
            """

        st.markdown(f"""
        <div class="dashboard-card">
            <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px;">
                <span style="font-weight: 600; font-size: 1.02rem; color: #0f172a;">{item['subject']}</span>
                <span class="badge badge-topic">{analysis.matched_topic or 'General'}</span>
            </div>
            <div style="font-size: 0.8rem; color: #64748b; margin-bottom: 8px;">From: {sender_clean}</div>
            <div style="font-size: 0.92rem; color: #334155; line-height: 1.5;">{analysis.summary}</div>
            {event_markup}
        </div>
        """, unsafe_allow_html=True)

        # Action Buttons
        if analysis.is_calendar_event and analysis.start_time:
            btn_col1, btn_col2 = st.columns([1, 4])
            with btn_col1:
                if email_id in st.session_state.synced_events:
                    st.button("✓ Added", key=f"synced_{email_id}", disabled=True, use_container_width=True)
                else:
                    if st.button("Add to Calendar", key=f"add_{email_id}", use_container_width=True):
                        try:
                            calendar = build('calendar', 'v3', credentials=st.session_state.credentials)
                            cal_link = add_to_calendar(calendar, analysis, user_timezone="Asia/Kolkata")
                            st.session_state.synced_events.add(email_id)
                            st.toast(f"Event scheduled: {analysis.event_title}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Sync failed: {e}")

    with tab1:
        for item in matched_threads:
            render_card(item)

    with tab2:
        if not actionable_events:
            st.caption("No calendar events detected in the current inbox batch.")
        else:
            for item in actionable_events:
                render_card(item)

    with tab3:
        digest_threads = [m for m in matched_threads if not m["analysis"].is_calendar_event]
        if not digest_threads:
            st.caption("All current matches contain actionable calendar dates.")
        else:
            for item in digest_threads:
                render_card(item)
