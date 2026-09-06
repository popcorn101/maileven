import streamlit as st
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import base64
from pathlib import Path
from analyzer import analyze_emails_batch, add_to_calendar

# -----------------------------------------------------------------------------
# 1. Page Config & High-Contrast Light Theme
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="MailEven | Executive Hub",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"], .stApp {
        font-family: 'Plus Jakarta Sans', -apple-system, sans-serif !important;
        background-color: #f8fafc !important; color: #090d16 !important;
    }
    header[data-testid="stHeader"] { display: none !important; }
    footer { display: none !important; }
    .block-container { padding-top: 1.5rem !important; max-width: 1120px !important; }
    .brand-logo { font-size: 1.25rem; font-weight: 800; color: #0f172a; letter-spacing: -0.02em; }
    .stat-card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px 20px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03); }
    .stat-label { font-size: 0.75rem; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: 0.05em; }
    .stat-value { font-size: 1.8rem; font-weight: 800; color: #090d16; margin-top: 4px; }
    .inbox-row { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px 20px; margin-bottom: 8px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.02); }
    .email-card { background: #ffffff; border: 1.5px solid #e2e8f0; border-radius: 14px; padding: 20px 24px; margin-bottom: 12px; box-shadow: 0 2px 4px rgba(15, 23, 42, 0.02); }
    .badge { font-size: 0.72rem; font-weight: 700; padding: 3px 9px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.04em; }
    .badge-topic { background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; }
    .badge-high { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }
    .badge-medium { background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }
    .badge-low { background: #f3f4f6; color: #4b5563; border: 1px solid #e5e7eb; }
    .event-banner { background: #f0fdf4; border: 1.5px solid #86efac; border-radius: 10px; padding: 12px 16px; margin: 12px 0; display: flex; align-items: center; gap: 12px; }
    div.stButton > button { border-radius: 8px !important; font-weight: 600 !important; }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. Multi-Tenant OAuth Flow (Server-Side Cache for Verifier Persistence)
# -----------------------------------------------------------------------------
CLIENT_SECRETS_FILE = Path(__file__).parent / "client_secret.json"
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/calendar.events']
REDIRECT_URI = st.secrets.get("APP_URL", "http://localhost:8501")

# This cache securely survives Streamlit page refreshes and redirects
@st.cache_resource
def get_oauth_store():
    return {}

def get_oauth_flow():
    if "google_oauth" in st.secrets:
        raw_config = st.secrets["google_oauth"]
        client_config = {"web": dict(raw_config["web"])} if "web" in raw_config else {"web": dict(raw_config)}
        return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    elif CLIENT_SECRETS_FILE.exists():
        return Flow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), scopes=SCOPES, redirect_uri=REDIRECT_URI)
    else:
        st.error("Missing Google OAuth configuration.")
        st.stop()

if "raw_inbox" not in st.session_state: st.session_state.raw_inbox = []
if "scan_results" not in st.session_state: st.session_state.scan_results = []
if "synced_events" not in st.session_state: st.session_state.synced_events = set()
if "credentials" not in st.session_state: st.session_state.credentials = None

def logout_user():
    st.session_state.clear()
    st.rerun()

# OAuth Callback Handler
query_params = st.query_params
if "code" in query_params and not st.session_state.credentials:
    code = query_params["code"]
    state = query_params.get("state")
    
    oauth_store = get_oauth_store()
    saved_verifier = oauth_store.get(state)

    if not saved_verifier:
        st.error("Login session timed out or browser refreshed. Please click Back to Login.")
        if st.button("Back to Login", type="primary"):
            st.query_params.clear()
            st.rerun()
        st.stop()

    flow = get_oauth_flow()
    try:
        flow.fetch_token(code=code, code_verifier=saved_verifier)
        st.session_state.credentials = flow.credentials
        oauth_store.pop(state, None) # Clean up cache
    except Exception as e:
        st.error(f"Failed to authenticate: {e}")
        st.stop()
    finally:
        st.query_params.clear()
        st.rerun()

def decode_body(payload):
    body_text = ""
    if 'parts' in payload:
        for part in payload['parts']:
            mime = part.get('mimeType', '')
            data = part.get('body', {}).get('data', '')
            if mime == 'text/plain' and data:
                return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            elif mime == 'text/html' and data and not body_text:
                body_text = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            elif 'parts' in part:
                res = decode_body(part)
                if res: return res
    else:
        data = payload.get('body', {}).get('data', '')
        if data: return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
    return body_text

def fetch_recent_emails(gmail_service, max_results=15):
    results = gmail_service.users().messages().list(userId='me', maxResults=max_results).execute()
    messages = results.get('messages', [])
    fetched = []
    for msg in messages:
        full = gmail_service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
        snippet = full.get('snippet', '')
        payload = full.get('payload', {})
        headers = {h['name']: h['value'] for h in payload.get('headers', [])}
        body_content = decode_body(payload)
        fetched.append({
            'id': msg['id'],
            'subject': headers.get('Subject', '(No Subject)'),
            'sender': headers.get('From', 'Unknown Sender'),
            'date': headers.get('Date', ''),
            'snippet': snippet,
            'body': body_content if body_content.strip() else snippet
        })
    return fetched

@st.dialog("Email Details", width="large")
def show_email_modal(msg):
    st.markdown(f"### {msg['subject']}")
    c1, c2 = st.columns([3, 1])
    with c1: st.markdown(f"**From:** `{msg['sender']}`")
    with c2: st.caption(msg.get('date', ''))
    st.divider()
    
    body = msg.get('body', msg.get('snippet', ''))
    if "<html" in body.lower() or "<div" in body.lower() or "<p" in body.lower():
        st.components.v1.html(f"<div style='font-family: sans-serif; color: #1e293b; line-height: 1.6; word-break: break-word;'>{body}</div>", height=450, scrolling=True)
    else:
        st.text_area("Content", value=body, height=400, disabled=True, label_visibility="collapsed")

# -----------------------------------------------------------------------------
# 3. Unauthenticated Screen
# -----------------------------------------------------------------------------
if not st.session_state.credentials:
    st.markdown("<div style='margin-top: 12vh;'></div>", unsafe_allow_html=True)
    _, login_col, _ = st.columns([1, 1.8, 1])
    with login_col:
        st.markdown("""
        <div style="background:#ffffff; border:1.5px solid #e2e8f0; border-radius:16px; padding:40px; text-align:center;">
            <div style="font-size:2.2rem; font-weight:800; color:#0f172a; margin-bottom:8px;">⚡ MailEven</div>
            <div style="font-size:1rem; font-weight:500; color:#64748b; margin-bottom:28px;">Autonomous event detection and executive inbox triage.</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

        flow = get_oauth_flow()
        auth_url, state = flow.authorization_url(prompt='consent', access_type='offline')
        
        # Save verifier dynamically to cache so it survives the browser redirect
        oauth_store = get_oauth_store()
        oauth_store[state] = flow.code_verifier

        st.link_button("Sign in with Google Workspace →", auth_url, type="primary", use_container_width=True)
    st.stop()

# -----------------------------------------------------------------------------
# 4. Top Navigation Bar
# -----------------------------------------------------------------------------
header_left, header_mid, header_right = st.columns([2.5, 5, 1.5], vertical_alignment="center")
with header_left: st.markdown('<div class="brand-logo"><span style="color:#2563eb;">⚡</span> MailEven</div>', unsafe_allow_html=True)
with header_mid:
    nav_selection = st.radio("Navigation", ["📬 Inbox", "⚡ AI Triage", "📊 Analytics"], horizontal=True, label_visibility="collapsed")
with header_right:
    if st.button("Log out", type="secondary", use_container_width=True): logout_user()

st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 5. Routing Views
# -----------------------------------------------------------------------------
if nav_selection == "📬 Inbox":
    inbox_col1, inbox_col2 = st.columns([4, 1.2], vertical_alignment="center")
    with inbox_col1:
        st.markdown("#### Primary Inbox")
        st.caption("Direct Gmail synchronization. Click any message to open the full content.")
    with inbox_col2:
        fetch_limit = st.selectbox("Messages to fetch", [10, 15, 25, 30], index=1)
        if st.button("🔄 Refresh Inbox", type="primary", use_container_width=True):
            with st.spinner("Fetching latest messages..."):
                st.session_state.raw_inbox = fetch_recent_emails(build('gmail', 'v1', credentials=st.session_state.credentials), max_results=fetch_limit)
            st.rerun()

    if not st.session_state.raw_inbox:
        with st.spinner("Connecting to Gmail..."):
            st.session_state.raw_inbox = fetch_recent_emails(build('gmail', 'v1', credentials=st.session_state.credentials), max_results=fetch_limit)
        st.rerun()

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    for msg in st.session_state.raw_inbox:
        sender_clean = msg["sender"].replace("<", "&lt;").replace(">", "&gt;")
        st.markdown(f"""
        <div class="inbox-row">
            <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:4px;">
                <span style="font-weight:700; color:#0f172a; font-size:1.02rem;">{msg['subject']}</span>
                <span style="font-size:0.78rem; color:#94a3b8; font-weight:600;">{msg['date'][:16]}</span>
            </div>
            <div style="font-size:0.82rem; font-weight:600; color:#2563eb; margin-bottom:6px;">{sender_clean}</div>
            <div style="font-size:0.88rem; color:#475569; line-height:1.45;">{msg['snippet']}</div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("📖 Read Full Email", key=f"view_raw_{msg['id']}"):
            show_email_modal(msg)

elif nav_selection == "⚡ AI Triage":
    cfg_c1, cfg_c2 = st.columns([3.5, 1])
    with cfg_c1:
        interests_input = st.text_input("Filter Targets", value="Hackathons, Tech Talks, AI Meetups, Dev Conferences, Seminars")
        interest_list = [t.strip() for t in interests_input.split(",") if t.strip()]
    with cfg_c2:
        triage_limit = st.selectbox("Scan Depth", [5, 8, 12, 16], index=1)

    scan_col1, scan_col2 = st.columns([3, 1.2])
    with scan_col1:
        scan_btn = st.button("⚡ Run AI Analysis on Inbox", type="primary", use_container_width=True)
    with scan_col2:
        pending_events = [item for item in st.session_state.scan_results if item["analysis"].is_calendar_event and item["id"] not in st.session_state.synced_events]
        if pending_events:
            if st.button(f"📅 Sync All ({len(pending_events)})", use_container_width=True):
                cal = build('calendar', 'v3', credentials=st.session_state.credentials)
                for item in pending_events:
                    try:
                        add_to_calendar(cal, item["analysis"])
                        st.session_state.synced_events.add(item["id"])
                    except Exception as e: st.error(f"Failed {item['subject']}: {e}")
                st.toast("Events Synced!")
                st.rerun()

    if scan_btn:
        with st.status("Executing AI scan...", expanded=True) as status_box:
            raw = fetch_recent_emails(build('gmail', 'v1', credentials=st.session_state.credentials), max_results=triage_limit)
            st.session_state.raw_inbox = raw
            
            st.write("Evaluating emails with Groq LLaMA-3...")
            analyses = analyze_emails_batch(raw, interest_list)
            analysis_map = {a.id: a for a in analyses}
            
            processed = []
            for item in raw:
                an = analysis_map.get(item["id"])
                if an and an.is_relevant:
                    item["analysis"] = an
                    processed.append(item)
            
            st.session_state.scan_results = processed
            status_box.update(label=f"Done — Identified {len(processed)} relevant threads", state="complete", expanded=False)
            st.rerun()

    if st.session_state.scan_results:
        st.markdown(f"<div style='font-size:0.85rem; font-weight:700; color:#475569; margin: 20px 0 10px 0;'>FILTERED THREADS ({len(st.session_state.scan_results)})</div>", unsafe_allow_html=True)
        for item in st.session_state.scan_results:
            an = item["analysis"]
            sender_clean = item["sender"].replace("<", "&lt;").replace(">", "&gt;")
            priority_class = f"badge-{an.priority.lower()}" if an.priority.lower() in ["high", "medium", "low"] else "badge-medium"
            event_html = f"""
                <div class="event-banner">
                    <div style="font-size:1.3rem;">🗓️</div>
                    <div>
                        <div style="font-weight:700; color:#14532d; font-size:0.92rem;">{an.event_title or 'Detected Event'}</div>
                        <div style="font-size:0.82rem; color:#166534; font-weight:600;">⏰ {an.start_time.replace('T', ' ')}</div>
                    </div>
                </div>
                """ if an.is_calendar_event and an.start_time else ""

            st.markdown(f"""
            <div class="email-card">
                <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:6px;">
                    <div style="font-size:1.05rem; font-weight:700; color:#0f172a;">{item['subject']}</div>
                    <div style="display:flex; gap:6px;"><span class="badge {priority_class}">{an.priority}</span><span class="badge badge-topic">{an.matched_topic or 'General'}</span></div>
                </div>
                <div style="font-size:0.82rem; font-weight:600; color:#64748b; margin-bottom:10px;">From: {sender_clean}</div>
                <div style="font-size:0.95rem; line-height:1.55; color:#1e293b;">{an.summary}</div>
                {event_html}
            </div>
            """, unsafe_allow_html=True)

            bc1, bc2, _ = st.columns([1.5, 1.8, 3])
            with bc1:
                if st.button("📖 Read Email", key=f"view_triage_{item['id']}"): show_email_modal(item)
            with bc2:
                if an.is_calendar_event and an.start_time:
                    if item["id"] in st.session_state.synced_events:
                        st.button("✓ Added", key=f"synced_{item['id']}", disabled=True)
                    elif st.button("📅 Add to Calendar", key=f"add_{item['id']}", type="primary"):
                        try:
                            add_to_calendar(build('calendar', 'v3', credentials=st.session_state.credentials), an)
                            st.session_state.synced_events.add(item["id"])
                            st.rerun()
                        except Exception as e: st.error(f"Sync Error: {e}")
    else:
        st.info("No AI-triaged threads yet. Configure your topics and click **⚡ Run AI Analysis on Inbox** above.")

elif nav_selection == "📊 Analytics":
    st.markdown("#### Operational Overview")
    total_raw = len(st.session_state.raw_inbox)
    total_matched = len(st.session_state.scan_results)
    total_events = sum(1 for x in st.session_state.scan_results if x["analysis"].is_calendar_event)
    total_synced = len(st.session_state.synced_events)
    
    m1, m2, m3, m4 = st.columns(4)
    with m1: st.markdown(f'<div class="stat-card"><div class="stat-label">Raw Inbox</div><div class="stat-value">{total_raw}</div></div>', unsafe_allow_html=True)
    with m2: st.markdown(f'<div class="stat-card"><div class="stat-label">AI Matches</div><div class="stat-value">{total_matched}</div></div>', unsafe_allow_html=True)
    with m3: st.markdown(f'<div class="stat-card"><div class="stat-label">Detected Events</div><div class="stat-value">{total_events}</div></div>', unsafe_allow_html=True)
    with m4: st.markdown(f'<div class="stat-card"><div class="stat-label">Calendar Syncs</div><div class="stat-value">{total_synced}</div></div>', unsafe_allow_html=True)
    
    st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
    st.markdown("#### Calendar Sync History")
    if not st.session_state.synced_events:
        st.caption("No events added to Google Calendar in this session.")
    else:
        for item in st.session_state.scan_results:
            if item["id"] in st.session_state.synced_events:
                st.markdown(f"""
                <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:10px; padding:14px 20px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
                    <div><span style="font-weight:700; color:#0f172a;">{item['analysis'].event_title}</span><span style="color:#64748b; font-size:0.85rem; margin-left:12px;">{item['analysis'].start_time}</span></div>
                    <span style="color:#16a34a; font-weight:700; font-size:0.8rem;">✓ Synced</span>
                </div>
                """, unsafe_allow_html=True)
