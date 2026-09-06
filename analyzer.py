import os
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from dotenv import load_dotenv
load_dotenv()

# 1. Define the exact structure we want back from the LLM
class EmailAnalysis(BaseModel):
    is_relevant: bool = Field(description="True if the email matches any of the user's interests")
    matched_topic: Optional[str] = Field(None, description="The specific interest topic matched")
    summary: str = Field(description="A crisp 1-2 sentence TL;DR of the email")
    is_calendar_event: bool = Field(description="True if the email announces an event with a specific date/time")
    event_title: Optional[str] = Field(None, description="Clear, short event title")
    start_time: Optional[str] = Field(None, description="Event start in ISO 8601 format: YYYY-MM-DDTHH:MM:SS")
    end_time: Optional[str] = Field(None, description="Event end in ISO 8601 format: YYYY-MM-DDTHH:MM:SS")
    location: Optional[str] = Field(None, description="Physical location or virtual meeting URL")

# Initialize client (picks up GEMINI_API_KEY from environment)
client = genai.Client()

def analyze_email(subject: str, sender: str, snippet: str, interests: list[str]) -> EmailAnalysis:
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    prompt = f"""
    Current Date & Time: {current_time_str}
    User Interests: {interests}

    Email Details:
    - From: {sender}
    - Subject: {subject}
    - Content/Snippet: {snippet}

    Instructions:
    1. Determine if this email genuinely aligns with the user's interests.
    2. Provide a 1-2 sentence summary.
    3. If this email mentions an event (hackathon, meeting, webinar, concert, deadline):
       - Extract the title, location, and start/end dates.
       - Use the Current Date & Time to resolve relative terms like "this Friday" or "tomorrow at 4pm" into full ISO 8601 timestamps (YYYY-MM-DDTHH:MM:SS).
       - If no end time is specified, estimate it as 1 hour after the start time.
    """

    response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=EmailAnalysis,
            temperature=0.1  # Low temperature for strict factual extraction
        ),
    )

    # Automatically validated as an EmailAnalysis Pydantic instance
    return response.parsed


def add_to_calendar(calendar_service, analysis: EmailAnalysis, user_timezone="Asia/Kolkata"):
    """Inserts the parsed event into the user's primary Google Calendar."""
    event_body = {
        'summary': analysis.event_title or 'Event from Email',
        'description': f"Auto-synced from email.\n\nSummary: {analysis.summary}",
        'location': analysis.location or '',
        'start': {
            'dateTime': analysis.start_time,
            'timeZone': user_timezone,
        },
        'end': {
            'dateTime': analysis.end_time or analysis.start_time,
            'timeZone': user_timezone,
        },
    }
    created_event = calendar_service.events().insert(
        calendarId='primary', 
        body=event_body
    ).execute()
    return created_event.get('htmlLink')