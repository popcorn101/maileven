import streamlit as st
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import os
from pathlib import Path
from analyzer import analyze_emails_batch, add_to_calendar

# -----------------------------------------------------------------------------
# 1. Page Config & High-Contrast Light Theme
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="InboxPilot | Executive Hub",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"], .stApp {
        font-family: 'Plus Jakarta Sans', -apple-system, sans-serif !important;
        background-color: #f8fafc !important;
        color: #090d16 !important;
    }

    header[data-testid="stHeader"] { display: none !important; }
    footer { display: none !important; }
    .block-container { padding-top: 1.5rem !important; max-width: 1120px !important; }

    .brand-logo {
        font-size: 1.25rem;
        font-weight: 800;
        color: #0f172a;
        letter-spacing: -0.02em;
    }

    .stat-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
    }
    .stat-label {
        font-size: 0.75rem;
        font-weight: 700;
        color: #475569;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .stat-value {
        font-size: 1.8rem;
        font-weight: 800;
        color: #090d16;
        margin-top: 4px;
    }

    /* Standard Raw Inbox Row */
    .inbox-row {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 16px 20px;
        margin-bottom: 10px;
        transition: all 0.15s ease;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.02);
    }
    .inbox-row:hover {
        border-color: #cbd5e1;
        box-shadow: 0 4px 10px rgba(15, 23, 42, 0.04);
    }

    /* AI Analysis Card */
    .email-card {
        background: #ffffff;
        border: 1.5px solid #e2e8f0;
        border-radius: 14px;
        padding: 20px 24px;
        margin-bottom: 14px;
        box-shadow: 0 2px 4px rgba(15, 23, 42, 0.02);
    }

    .badge {
        font-size: 0.72rem;
        font-weight: 700;
        padding: 3px 9px;
        border-radius: 20px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .badge-topic { background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; }
    .badge-high { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }
    .badge-medium { background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }
    .badge-low { background: #f3f4f6; color: #4b5563; border: 1px solid #e5e7eb; }

    .event-banner {
        background: #f0fdf4;
        border: 1.5px solid #86efac;
        border-radius: 10px;
        padding: 12px 16px;
        margin-top: 14px;
        display: flex;
        align-items: center;
        gap: 12px;
    }

    div.stButton > button {
        border-radius: 8px !important;
        font-weight: 600 !important;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. Hybrid OAuth Flow (Cloud & Local Support)
# -----------------------------------------------------------------------------
CLIENT_SECRETS_FILE = Path(__file__).parent / "client_secret.json"
TOKEN_FILE = Path(__file__).parent / "token.json"
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar.events'
]

REDIRECT_URI = st.secrets.get("APP_URL", "http://localhost:8501")

def get_oauth_flow():
    if "google_oauth" in st.secrets:
        raw_config = st.secrets["google_oauth"]
        if "web" in raw_config:
            client_config = {"web": dict(raw_config["web"])}
        else:
            client_config = {"web": dict(raw_config)}
        return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    elif CLIENT_SECRETS_FILE.exists():
        return Flow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), scopes=SCOPES, redirect_uri=REDIRECT_URI)
    else:
        st.error("Missing Google OAuth credentials.")
        st.stop()

# Session State Initialization
if "raw_inbox" not in st.session_state:
    st.session_state.raw_inbox = []
if "scan_results" not in st.session_state:
    st.session_state.scan_results = []
if "synced_events" not in st.session_state:
    st.session_state.synced_events = set()
if "credentials" not in st.session_state:
    st.session_state.credentials = None

# Auto-login via persisted token.json
if not st.session_state.credentials and os.path.exists(TOKEN_FILE):
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, 'w') as tf:
                tf.write(creds.to_json())
        if creds and creds.valid:
            st.session_state.credentials = creds
    except Exception:
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)

def logout_user():
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)
    st.session_state.credentials = None
    st.session_state.raw_inbox = []
    st.session_state.scan_results = []
    st.session_state.synced_events = set()
    st.rerun()

# OAuth Callback Handler
query_params = st.query_params
if "code" in query_params and not st.session_state.credentials:
    code = query_params["code"]
    saved_verifier = st.session_state.get("code_verifier")
    if not saved_verifier and os.path.exists("verifier.txt"):
        try:
            with open("verifier.txt", "r") as vf:
                saved_verifier = vf.read().strip()
        except Exception:
            pass

    if not saved_verifier:
        st.error("Authentication expired. Please restart.")
        st.stop()

    flow = get_oauth_flow()
    flow.fetch_token(code=code, code_verifier=saved_verifier)
    creds = flow.credentials

    try:
        with open(TOKEN_FILE, 'w') as tf:
            tf.write(creds.to_json())
    except Exception:
        pass

    st.session_state.credentials = creds
    st.query_params.clear()
    st.rerun()

def fetch_recent_emails(gmail_service, max_results=15):
    """Fetches messages directly from Gmail API without filtering dates."""
    results = gmail_service.users().messages().list(
        userId='me',
        maxResults=max_results
    ).execute()
    messages = results.get('messages', [])
    fetched = []
    for msg in messages:
        full = gmail_service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
        snippet = full.get('snippet', '')
        headers = {h['name']: h['value'] for h in full.get('payload', {}).get('headers', [])}
        fetched.append({
            'id': msg['id'],
            'subject': headers.get('Subject', '(No Subject)'),
            'sender': headers.get('From', 'Unknown Sender'),
            'date': headers.get('Date', ''),
            'snippet': snippet
        })
    return fetched

# -----------------------------------------------------------------------------
# 3. Unauthenticated Screen
# -----------------------------------------------------------------------------
if not st.session_state.credentials:
    st.markdown("<div style='margin-top: 12vh;'></div>", unsafe_allow_html=True)
    _, login_col, _ = st.columns([1, 1.8, 1])
    with login_col:
        st.markdown("""
        <div style="background:#ffffff; border:1.5px solid #e2e8f0; border-radius:16px; padding:40px; text-align:center;">
            <div style="font-size:2.2rem; font-weight:800; color:#0f172a; margin-bottom:8px;">⚡ InboxPilot</div>
            <div style="font-size:1rem; font-weight:500; color:#64748b; margin-bottom:28px;">Autonomous event detection and executive inbox triage.</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

        flow = get_oauth_flow()
        auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
        st.session_state["code_verifier"] = flow.code_verifier
        try:
            with open("verifier.txt", "w") as vf:
                vf.write(flow.code_verifier)
        except Exception:
            pass

        st.link_button("Sign in with Google Workspace →", auth_url, type="primary", use_container_width=True)
    st.stop()

# -----------------------------------------------------------------------------
# 4. Top Navigation Bar (Three Distinct Tabs)
# -----------------------------------------------------------------------------
header_left, header_mid, header_right = st.columns([2.5, 5, 1.5], vertical_alignment="center")

with header_left:
    st.markdown('<div class="brand-logo"><span style="color:#2563eb;">⚡</span> InboxPilot</div>', unsafe_allow_html=True)

with header_mid:
    nav_selection = st.radio(
        "Navigation",
        ["📬 Inbox", "⚡ AI Triage", "📊 Analytics"],
        horizontal=True,
        label_visibility="collapsed"
    )

with header_right:
    if st.button("Log out", type="secondary", use_container_width=True):
        logout_user()

st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 5. Routing Views
# -----------------------------------------------------------------------------

# --- VIEW 1: REGULAR RAW INBOX (NO GROQ / NO TOKEN USAGE) ---
if nav_selection == "📬 Inbox":
    inbox_col1, inbox_col2 = st.columns([4, 1.2], vertical_alignment="center")
    with inbox_col1:
        st.markdown("#### Primary Inbox")
        st.caption("Direct Gmail synchronization. Review incoming messages before running AI triage.")
    with inbox_col2:
        fetch_limit = st.selectbox("Messages to fetch", [10, 15, 25, 30], index=1)
        if st.button("🔄 Refresh Inbox", type="primary", use_container_width=True):
            with st.spinner("Fetching latest messages from Gmail..."):
                gmail = build('gmail', 'v1', credentials=st.session_state.credentials)
                st.session_state.raw_inbox = fetch_recent_emails(gmail, max_results=fetch_limit)
            st.rerun()

    # Initial auto-load if list is empty
    if not st.session_state.raw_inbox:
        with st.spinner("Connecting to Gmail..."):
            gmail = build('gmail', 'v1', credentials=st.session_state.credentials)
            st.session_state.raw_inbox = fetch_recent_emails(gmail, max_results=fetch_limit)
        st.rerun()

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    # Render Regular Email List
    for msg in st.session_state.raw_inbox:
        sender_clean = msg["sender"].replace("<", "&lt;").replace(">", "&gt;")
        st.markdown(f"""
        <div class="inbox-row">
            <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:4px;">
                <span style="font-weight:700; color:#0f172a; font-size:1.02rem;">{msg['subject']}</span>
                <span style="font-size:0.78rem; color:#94a3b8; font-weight:600;">{msg['date'][:16]}</span>
            </div>
            <div style="font-size:0.82rem; font-weight:600; color:#2563eb; margin-bottom:8px;">{sender_clean}</div>
            <div style="font-size:0.88rem; color:#475569; line-height:1.45;">{msg['snippet']}</div>
        </div>
        """, unsafe_allow_html=True)


# --- VIEW 2: AI TRIAGE (USES GROQ) ---
elif nav_selection == "⚡ AI Triage":
    with st.container():
        cfg_c1, cfg_c2 = st.columns([3.5, 1])
        with cfg_c1:
            interests_input = st.text_input(
                "Filter Targets",
                value="Hackathons, Tech Talks, AI Meetups, Dev Conferences, Seminars",
                placeholder="Topics separated by comma..."
            )
            interest_list = [t.strip() for t in interests_input.split(",") if t.strip()]
        with cfg_c2:
            triage_limit = st.selectbox("Scan Depth", [5, 8, 12, 16], index=1)

    scan_col1, scan_col2 = st.columns([3, 1.2])
    with scan_col1:
        scan_btn = st.button("⚡ Run AI Analysis on Inbox", type="primary", use_container_width=True)
    with scan_col2:
        pending_events = [
            item for item in st.session_state.scan_results
            if item["analysis"].is_calendar_event and item["id"] not in st.session_state.synced_events
        ]
        if pending_events:
            if st.button(f"📅 Sync All ({len(pending_events)})", use_container_width=True):
                calendar_service = build('calendar', 'v3', credentials=st.session_state.credentials)
                success_count = 0
                for item in pending_events:
                    try:
                        add_to_calendar(calendar_service, item["analysis"])
                        st.session_state.synced_events.add(item["id"])
                        success_count += 1
                    except Exception as e:
                        st.error(f"Failed to sync {item['subject']}: {e}")
                st.toast(f"Successfully synced {success_count} events!")
                st.rerun()

    if scan_btn:
        with st.status("Executing AI scan...", expanded=True) as status_box:
            gmail = build('gmail', 'v1', credentials=st.session_state.credentials)
            raw = fetch_recent_emails(gmail, max_results=triage_limit)
            st.session_state.raw_inbox = raw

            st.write("Evaluating emails with Groq...")
            analyses = analyze_emails_batch(raw, interest_list)

            analysis_map = {a.id: a for a in analyses}
            processed = []
            for item in raw:
                an = analysis_map.get(item["id"])
                # Show matches, or all emails parsed if debug needed
                if an and an.is_relevant:
                    processed.append({
                        "id": item["id"],
                        "subject": item["subject"],
                        "sender": item["sender"],
                        "analysis": an
                    })

            st.session_state.scan_results = processed
            status_box.update(label=f"Done — Identified {len(processed)} relevant threads", state="complete", expanded=False)
            st.rerun()

    # Triage Results Feed
    if st.session_state.scan_results:
        st.markdown(f"<div style='font-size:0.85rem; font-weight:700; color:#475569; margin: 20px 0 10px 0;'>FILTERED THREADS ({len(st.session_state.scan_results)})</div>", unsafe_allow_html=True)

        for item in st.session_state.scan_results:
            email_id = item["id"]
            an = item["analysis"]
            sender_clean = item["sender"].replace("<", "&lt;").replace(">", "&gt;")

            priority_class = f"badge-{an.priority.lower()}" if an.priority.lower() in ["high", "medium", "low"] else "badge-medium"

            event_html = ""
            if an.is_calendar_event and an.start_time:
                loc_txt = f" &nbsp;•&nbsp; 📍 {an.location}" if an.location else ""
                event_html = f"""
                <div class="event-banner">
                    <div style="font-size:1.3rem;">🗓️</div>
                    <div>
                        <div style="font-weight:700; color:#14532d; font-size:0.92rem;">{an.event_title or 'Detected Event'}</div>
                        <div style="font-size:0.82rem; color:#166534; font-weight:600;">⏰ {an.start_time.replace('T', ' ')}{loc_txt}</div>
                    </div>
                </div>
                """

            st.markdown(f"""
            <div class="email-card">
                <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:6px;">
                    <div style="font-size:1.05rem; font-weight:700; color:#0f172a;">{item['subject']}</div>
                    <div style="display:flex; gap:6px;">
                        <span class="badge {priority_class}">{an.priority}</span>
                        <span class="badge badge-topic">{an.matched_topic or 'General'}</span>
                    </div>
                </div>
                <div style="font-size:0.82rem; font-weight:600; color:#64748b; margin-bottom:10px;">From: {sender_clean}</div>
                <div style="font-size:0.95rem; line-height:1.55; color:#1e293b;">{an.summary}</div>
                {event_html}
            </div>
            """, unsafe_allow_html=True)

            if an.is_calendar_event and an.start_time:
                btn_col, _ = st.columns([1.6, 4])
                with btn_col:
                    if email_id in st.session_state.synced_events:
                        st.button("✓ Added to Calendar", key=f"synced_{email_id}", disabled=True)
                    else:
                        if st.button("📅 Add to Calendar", key=f"add_{email_id}", type="primary"):
                            try:
                                cal = build('calendar', 'v3', credentials=st.session_state.credentials)
                                link = add_to_calendar(cal, an)
                                st.session_state.synced_events.add(email_id)
                                st.toast(f"Synced: {an.event_title}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Calendar Sync Error: {e}")
    else:
        st.info("No AI-triaged threads yet. Configure your topics and click **⚡ Run AI Analysis on Inbox** above.")


# --- VIEW 3: ANALYTICS DASHBOARD ---
elif nav_selection == "📊 Analytics":
    st.markdown("#### Operational Overview")

    total_raw = len(st.session_state.raw_inbox)
    total_matched = len(st.session_state.scan_results)
    total_events = sum(1 for x in st.session_state.scan_results if x["analysis"].is_calendar_event)
    total_synced = len(st.session_state.synced_events)

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(f'<div class="stat-card"><div class="stat-label">Raw Inbox Count</div><div class="stat-value">{total_raw}</div></div>', unsafe_allow_html=True)
    with m2:
        st.markdown(f'<div class="stat-card"><div class="stat-label">AI Matches</div><div class="stat-value">{total_matched}</div></div>', unsafe_allow_html=True)
    with m3:
        st.markdown(f'<div class="stat-card"><div class="stat-label">Detected Events</div><div class="stat-value">{total_events}</div></div>', unsafe_allow_html=True)
    with m4:
        st.markdown(f'<div class="stat-card"><div class="stat-label">Calendar Syncs</div><div class="stat-value">{total_synced}</div></div>', unsafe_allow_html=True)

    st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
    st.markdown("#### Calendar Sync History")

    if not st.session_state.synced_events:
        st.caption("No events added to Google Calendar in this session.")
    else:
        for item in st.session_state.scan_results:
            if item["id"] in st.session_state.synced_events:
                an = item["analysis"]
                st.markdown(f"""
                <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:10px; padding:14px 20px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span style="font-weight:700; color:#0f172a;">{an.event_title}</span>
                        <span style="color:#64748b; font-size:0.85rem; margin-left:12px;">{an.start_time}</span>
                    </div>
                    <span style="color:#16a34a; font-weight:700; font-size:0.8rem;">✓ Synced</span>
                </div>
                """, unsafe_allow_html=True)
