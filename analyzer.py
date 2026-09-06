import os
import json
from datetime import datetime, timedelta
from typing import Optional, List
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from openai import OpenAI
import streamlit as st

load_dotenv()

# Data validation schema
class SingleEmailAnalysis(BaseModel):
    id: str = Field(default="")
    is_relevant: bool = Field(default=False)
    matched_topic: Optional[str] = None
    priority: str = Field(default="Medium", description="High, Medium, or Low")
    summary: str = Field(default="")
    is_calendar_event: bool = Field(default=False)
    event_title: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None

# Pull Groq key dynamically from Streamlit Cloud secrets, fallback to local .env
api_key = st.secrets.get("GROQ_API_KEY", os.environ.get("GROQ_API_KEY"))

client = OpenAI(
    api_key=api_key,
    base_url="https://api.groq.com/openai/v1"
)

def analyze_emails_batch(emails: list[dict], interests: list[str]) -> list[SingleEmailAnalysis]:
    if not emails:
        return []

    now_dt = datetime.now()
    current_time_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    email_payload = "\n---\n".join([
        f"ID: {e['id']}\nSubject: {e['subject']}\nSnippet: {e['snippet'][:250]}"
        for e in emails
    ])

    prompt = f"""
Current Anchor Date/Time: {current_time_str}
User Target Interests: {interests}

Emails to evaluate:
{email_payload}

Instructions:
Evaluate each email and return a JSON object with a single root key "analyses" containing an array of objects.
For every email, output:
- "id": string (the exact email ID provided)
- "is_relevant": boolean (true if relevant to user interests)
- "matched_topic": string or null
- "priority": string ("High", "Medium", or "Low")
- "summary": string (concise 1-sentence summary)
- "is_calendar_event": boolean (true ONLY if there is an explicit date/time or deadline)
- "event_title": string or null
- "start_time": string in strict ISO 8601 format (YYYY-MM-DDTHH:MM:SS) without timezone offset, or null
- "end_time": string in strict ISO 8601 format (YYYY-MM-DDTHH:MM:SS) without timezone offset, or null
- "location": string (venue, meeting link, or null)

Rules:
1. Relative dates like "tomorrow at 3 PM" must be computed relative to {current_time_str}.
2. If only a date is mentioned (no hour), default the time to 10:00:00.
3. If no end time is specified, calculate it as 1 hour after start_time.
4. Return ONLY valid JSON.
"""

    try:
        # Fixed: Using the highly reliable LLaMA 3 70B model on Groq for JSON tasks
        response = client.chat.completions.create(
            model="llama3-70b-8192", 
            messages=[
                {"role": "system", "content": "You are a precise JSON-generating data extraction engine."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=2048
        )

        content = response.choices[0].message.content
        raw_json = json.loads(content)
        raw_list = raw_json.get("analyses", [])
        return [SingleEmailAnalysis(**item) for item in raw_list]

    except Exception as e:
        print(f"Groq API Error: {e}")
        # Return empty list gracefully so the app doesn't crash on API failure
        return []

def format_rfc3339(iso_str: str, timezone_offset="+05:30") -> str:
    """Ensures timestamp string strictly complies with Google Calendar RFC 3339."""
    if not iso_str:
        return ""
    clean_str = iso_str.strip().replace("Z", "")
    if len(clean_str) == 10:
        clean_str += "T10:00:00"
    return f"{clean_str}{timezone_offset}"

def add_to_calendar(calendar_service, analysis: SingleEmailAnalysis, user_timezone="Asia/Kolkata"):
    """Safely adds an event to Google Calendar with guaranteed valid timestamps."""
    if not analysis.start_time:
        raise ValueError("Missing start_time for calendar event.")

    start_rfc = format_rfc3339(analysis.start_time)
    
    if analysis.end_time:
        end_rfc = format_rfc3339(analysis.end_time)
    else:
        try:
            start_dt = datetime.fromisoformat(analysis.start_time[:19])
            end_rfc = format_rfc3339((start_dt + timedelta(hours=1)).isoformat())
        except Exception:
            end_rfc = start_rfc

    event_body = {
        'summary': analysis.event_title or 'Actionable Email Event',
        'description': f"Auto-detected by InboxPilot.\n\nSummary: {analysis.summary}\nTopic: {analysis.matched_topic}",
        'location': analysis.location or '',
        'start': {
            'dateTime': start_rfc,
            'timeZone': user_timezone,
        },
        'end': {
            'dateTime': end_rfc,
            'timeZone': user_timezone,
        },
    }

    created = calendar_service.events().insert(
        calendarId='primary',
        body=event_body
    ).execute()

    return created.get('htmlLink')
