import streamlit as st
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from pathlib import Path
from analyzer import analyze_email, add_to_calendar

# -----------------------------------------------------------------------------
# 1. Page Configuration & Custom CSS (Notion/Linear Design System)
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="InboxPilot | AI Email & Calendar Engine",
    page_icon="⚡",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Custom Design System: Inter typography, minimalist cards, sleek badges, subtle borders
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    /* Main Container Padding */
    .block-container {
        padding-top: 2.5rem;
        padding-bottom: 4rem;
        max-width: 780px;
    }

    /* Clean Card Container */
    .notion-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1rem;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
        transition: all 0.2s ease;
    }
    .notion-card:hover {
        border-color: #d1d5db;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
    }

    /* Typography */
    .card-title {
        font-size: 1.05rem;
        font-weight: 600;
        color: #111827;
        margin-bottom: 0.25rem;
    }
    .card-meta {
        font-size: 0.8rem;
        color: #6b7280;
        margin-bottom: 0.75rem;
    }
    .card-summary {
        font-size: 0.92rem;
        color: #374151;
        line-height: 1.5;
        margin-bottom: 0.9rem;
    }

    /* Pill Badges */
    .badge {
        display: inline-block;
        font-size: 0.72rem;
        font-weight: 500;
        padding: 2px 8px;
        border-radius: 9999px;
        text-transform: uppercase;
        letter-spacing: 0.03em;
    }
    .badge-topic {
        background-color: #f3f4f6;
        color: #374151;
        border: 1px solid #e5e7eb;
    }
    .badge-event {
        background-color: #eff6ff;
        color: #1d4ed8;
        border: 1px solid #bfdbfe;
    }

    /* Event highlight strip */
    .event-strip {
        display: flex;
        align-items: center;
        gap: 8px;
        background: #f8fafc;
        border-left: 3px solid #3b82f6;
        padding: 8px 12px;
        border-radius: 4px;
        font-size: 0.85rem;
        color: #1e293b;
        margin-bottom: 0.75rem;
    }

    /* Primary CTA Button Polish */
    div.stButton > button:first-child {
        border-radius: 8px;
        font-weight: 500;
        border: 1px solid #e5e7eb;
        transition: all 0.15s ease;
    }
    div.stButton > button:first-child:hover {
        border-color: #9ca3af;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. App State & OAuth Setup
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

# Handle OAuth redirect
query_params = st.query_params
if "code" in query_params and not st.session_state.credentials:
    code = query_params["code"]
    try:
        with open("verifier.txt", "r") as f:
            saved_verifier = f.read().strip()
    except FileNotFoundError:
        st.error("Session expired. Please sign in again.")
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

def fetch_recent_emails(gmail_service, max_results=8):
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
# 3. Clean Notion-like Header & Controls
# -----------------------------------------------------------------------------
st.title("⚡ InboxPilot")
st.caption("Intelligent inbox triage and calendar sync aligned with your personal interests.")

st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

# Interest tags input
interests_input = st.text_input(
    "Target Interests",
    value="Hackathons, Tech Talks, AI, Coding Meetups",
    help="InboxPilot parses incoming emails against these topics."
)
interest_list = [item.strip() for item in interests_input.split(",") if item.strip()]

# -----------------------------------------------------------------------------
# 4. Auth & Action Flow
# -----------------------------------------------------------------------------
if not st.session_state.credentials:
    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
    auth_url = get_auth_url()
    st.link_button("Connect Google Workspace / Gmail →", auth_url, use_container_width=True)
else:
    col1, col2 = st.columns([3, 1])
    with col1:
        scan_btn = st.button("Run Inbox Scan", type="primary", use_container_width=True)
    with col2:
        if st.button("Disconnect", use_container_width=True):
            st.session_state.credentials = None
            st.session_state.scan_results = []
            st.rerun()

    if scan_btn:
        with st.status("Analyzing inbox against focus topics...", expanded=True) as status:
            st.write("Connecting to Gmail API...")
            gmail = build('gmail', 'v1', credentials=st.session_state.credentials)
            calendar = build('calendar', 'v3', credentials=st.session_state.credentials)
            
            st.write("Extracting recent primary messages...")
            raw_emails = fetch_recent_emails(gmail)
            
            st.write("Processing context with Gemini Flash...")
            processed = []
            for email in raw_emails:
                analysis = analyze_email(
                    subject=email['subject'],
                    sender=email['sender'],
                    snippet=email['snippet'],
                    interests=interest_list
                )
                if analysis.is_relevant:
                    processed.append({
                        "id": email["id"],
                        "subject": email["subject"],
                        "sender": email["sender"],
                        "analysis": analysis
                    })
            
            st.session_state.scan_results = processed
            status.update(label=f"Scan complete — {len(processed)} relevant threads found", state="complete", expanded=False)

    # -------------------------------------------------------------------------
    # 5. Notion/Linear Card Feed
    # -------------------------------------------------------------------------
    if st.session_state.scan_results:
        st.markdown(f"<p style='font-size: 0.85rem; color: #6b7280; font-weight: 500; margin-top: 1.5rem;'>RELEVANT THREADS ({len(st.session_state.scan_results)})</p>", unsafe_allow_html=True)

        for item in st.session_state.scan_results:
            email_id = item["id"]
            analysis = item["analysis"]
            
            with st.container():
                # Render clean HTML Card
                event_html = ""
                if analysis.is_calendar_event and analysis.start_time:
                    event_html = f"""
                    <div class="event-strip">
                        <span>📅</span>
                        <span><strong>{analysis.event_title or 'Event'}</strong> · {analysis.start_time} {f'· {analysis.location}' if analysis.location else ''}</span>
                    </div>
                    """

                st.markdown(f"""
                <div class="notion-card">
                    <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px;">
                        <span class="card-title">{item['subject']}</span>
                        <span class="badge badge-topic">{analysis.matched_topic or 'General'}</span>
                    </div>
                    <div class="card-meta">From: {item['sender']}</div>
                    <div class="card-summary">{analysis.summary}</div>
                    {event_html}
                </div>
                """, unsafe_allow_html=True)

                # Quick Actions for detected events
                if analysis.is_calendar_event and analysis.start_time:
                    cal_col1, cal_col2 = st.columns([1, 2])
                    with cal_col1:
                        if email_id in st.session_state.synced_events:
                            st.button("✓ Added to Calendar", key=f"synced_{email_id}", disabled=True, use_container_width=True)
                        else:
                            if st.button("Add to Google Calendar", key=f"add_{email_id}", use_container_width=True):
                                try:
                                    calendar = build('calendar', 'v3', credentials=st.session_state.credentials)
                                    cal_link = add_to_calendar(calendar, analysis, user_timezone="Asia/Kolkata")
                                    st.session_state.synced_events.add(email_id)
                                    st.toast(f"Scheduled: {analysis.event_title}")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Sync error: {e}")