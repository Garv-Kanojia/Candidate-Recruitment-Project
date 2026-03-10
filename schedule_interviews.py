import datetime
import os
import uuid

import pandas as pd
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Scope required to create and manage calendar events
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

# Interview scheduling config
INTERVIEW_DURATION_MINUTES = 30
INTERVIEW_GAP_MINUTES = 15
TIMEZONE = 'Asia/Kolkata'


def get_calendar_service():
    """Authenticate and return Google Calendar service."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build('calendar', 'v3', credentials=creds)


def is_selected(test_la, test_code):
    """Check if a candidate meets the selection criteria.

    Selected if:
      - Both scores >= 75, OR
      - One score >= 90 and the other >= 60
    """
    if test_la >= 75 and test_code >= 75:
        return True
    if (test_la >= 90 and test_code >= 60) or (test_code >= 90 and test_la >= 60):
        return True
    return False


def schedule_interview(service, candidate, start_time):
    """Create a Google Calendar event with Google Meet for the candidate."""
    end_time = start_time + datetime.timedelta(minutes=INTERVIEW_DURATION_MINUTES)

    resume_link = candidate.get('resume', '')
    resume_text = resume_link if pd.notna(resume_link) and resume_link else 'Not provided'

    description = (
        f"Resume: {resume_text}\n\n"
        f"Candidate Details:\n"
        f"  Name: {candidate['name']}\n"
        f"  College: {candidate['college']}\n"
        f"  Branch: {candidate['branch']}\n"
        f"  CGPA: {candidate['cgpa']}\n\n"
        f"Assessment Scores:\n"
        f"  Logical Assessment: {candidate['test_la']}\n"
        f"  Code Test: {candidate['test_code']}"
    )

    event_body = {
        'summary': f"Interview - {candidate['name']}",
        'description': description,
        'start': {
            'dateTime': start_time.isoformat(),
            'timeZone': TIMEZONE,
        },
        'end': {
            'dateTime': end_time.isoformat(),
            'timeZone': TIMEZONE,
        },
        'attendees': [
            {'email': candidate['email']},
        ],
        'conferenceData': {
            'createRequest': {
                'requestId': str(uuid.uuid4()),
                'conferenceSolutionKey': {
                    'type': 'hangoutsMeet'
                }
            }
        },
        'reminders': {
            'useDefault': True,
        },
    }

    # sendUpdates='all' sends email invites to all attendees
    event = service.events().insert(
        calendarId='primary',
        body=event_body,
        conferenceDataVersion=1,
        sendUpdates='all'
    ).execute()

    return event


def main():
    # 1. Read candidate data from CSV
    df = pd.read_csv('test.csv')
    print(f"Total candidates in CSV: {len(df)}\n")

    # 2. Apply selection criteria
    selected = df[
        df.apply(lambda row: is_selected(row['test_la'], row['test_code']), axis=1)
    ].copy()

    if selected.empty:
        print("No candidates met the selection criteria.")
        return

    print(f"Selected {len(selected)} candidate(s) for interview:")
    for _, row in selected.iterrows():
        print(f"  - {row['name']} | LA: {row['test_la']} | Code: {row['test_code']}")

    # 3. Authenticate with Google Calendar
    service = get_calendar_service()

    # 4. Schedule interviews starting tomorrow at 11:30 AM IST, staggered
    base_time = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(days=1)
    ).replace(hour=6, minute=0, second=0, microsecond=0)  # 6:00 UTC = 11:30 IST

    print("\nScheduling interviews...\n")
    for idx, (_, candidate) in enumerate(selected.iterrows()):
        slot_start = base_time + datetime.timedelta(
            minutes=idx * (INTERVIEW_DURATION_MINUTES + INTERVIEW_GAP_MINUTES)
        )
        try:
            event = schedule_interview(service, candidate, slot_start)
            meet_link = event.get('hangoutLink', 'N/A')
            print(f"[OK]  {candidate['name']} ({candidate['email']})")
            print(f"      Meet Link : {meet_link}")
            print(f"      Event Link: {event.get('htmlLink')}\n")
        except Exception as e:
            print(f"[FAIL] {candidate['name']} — {e}\n")

    print("Done.")


if __name__ == '__main__':
    main()
