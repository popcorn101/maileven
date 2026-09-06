# ⚡ InboxPilot

> **Autonomous AI-powered email triage and calendar synchronization engine.**

InboxPilot parses incoming Gmail correspondence, screens messages against user-defined focus topics, generates executive-grade one-sentence TL;DRs, and automatically extracts and synchronizes actionable deadlines or meetings straight to Google Calendar.

---

## ✨ Features

- **Topic Alignment Engine**: Sifts through high-volume inboxes and surfaces only messages relevant to your selected interests (e.g., *Hackathons, Tech Talks, AI Meetups*).
- **Sub-Second LLM Parsing**: Uses Groq LPU inference (`openai/gpt-oss-20b`) with strict JSON schema enforcement to process entire email batches in a single API roundtrip.
- **Automated Google Calendar Sync**: Automatically resolves relative dates (e.g., *"this Friday at 4 PM"*) into RFC 3339 timestamps and pushes events directly to Google Calendar.
- **Enterprise-Grade Triage Dashboard**: Custom-styled Linear/Vercel-inspired UI featuring KPI metric counters, priority indicators (High/Medium/Low), and bulk synchronization tools.
- **Persistent Session Handling**: Offline OAuth 2.0 refresh mechanics maintain your authenticated session across browser reloads without repeated sign-ins.

---

## 🛠️ Tech Stack

- **Frontend & App Framework**: [Streamlit](https://streamlit.io/)
- **LLM Inference**: [GroqCloud](https://console.groq.com/) via the OpenAI Python SDK
- **Google Workspace APIs**: Gmail API (`v1`), Google Calendar API (`v3`)
- **Authentication**: Google OAuth 2.0 Web Server Flow with PKCE
- **Data Validation**: Pydantic v2

---

## 📋 Prerequisites

Before running the application, make sure you have:

1. **Python 3.10+** installed on your system.
2. A **Google Cloud Console Project** with:
   - **Gmail API** enabled.
   - **Google Calendar API** enabled.
   - An **OAuth 2.0 Client ID** configured as a **Web application**.
   - Your email added under **OAuth Consent Screen > Test Users** (while in testing mode).
3. A **GroqCloud API Key** (free tier available at [console.groq.com](https://console.groq.com/)).

---

## 🚀 Local Installation & Setup

### 1. Clone the Repository

```bash
git clone [https://github.com/popcorn101/maileven.git](https://github.com/popcorn101/maileven.git)
cd maileven
