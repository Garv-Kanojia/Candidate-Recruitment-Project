import csv
import datetime
import io
import json
import os
import random
import smtplib
import string
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager

import fitz
import gdown
import requests
from dotenv import load_dotenv
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from supabase import create_client, Client

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────────
API_KEY = os.getenv("API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
TEST_LINK = "https://recruitment-test.example.com/start?token=ABC123XYZ"

SUPABASE_URL = os.getenv("SUPABASE_URL")           # e.g. https://xxxx.supabase.co
SUPABASE_KEY = os.getenv("SUPABASE_KEY")           # anon / public key
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # service-role key (for admin ops)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY or SUPABASE_KEY)

INTERVIEW_DURATION_MINUTES = 30
INTERVIEW_GAP_MINUTES = 5
TIMEZONE = "Asia/Kolkata"

INTERVIEWERS = [
    {"email": "rajesh.mehta@example.com", "displayName": "Rajesh Mehta"},
    {"email": "ananya.sharma@example.com", "displayName": "Ananya Sharma"},
]

JOB_DESCRIPTION = """
# **Job Title: Applied AI Engineer (Entry-Level / Fresher)**

**Department:** Engineering / Data Science
**Experience:** 0-1 Year (Includes Internships/Strong Project Portfolios)
**Location:** Hybrid / Remote

## **About the Role**
We are looking for a passionate and builder-oriented Applied AI Engineer to join our growing team. In this role, you will bridge the gap between AI research and real-world software. You won't just be analyzing data; you will be designing intelligent systems, integrating large language models (LLMs) into production environments, and building the backend infrastructure to support them. If you love tackling complex problems and turning AI concepts into functional, scalable products, we want you on our team.

## **Key Responsibilities**
* Design, develop, and deploy machine learning and deep learning models to solve specific business problems.
* Build and maintain robust data pipelines and backend APIs to serve AI models in real-time.
* Develop generative AI applications leveraging LLMs, Retrieval-Augmented Generation (RAG), and custom prompts.
* Evaluate, fine-tune, and optimize open-source AI models to balance latency, accuracy, and computational cost.
* Collaborate with frontend developers, product managers, and data engineers to integrate AI features seamlessly into user-facing applications.
* Stay up-to-date with the rapidly evolving AI landscape and prototype new architectures to improve existing systems.

## **Required Skills & Qualifications**
* B.S. or M.S. in Computer Science, Artificial Intelligence, Data Science, or a related technical field.
* Strong programming fundamentals with high proficiency in **Python** and **SQL**.
* Solid theoretical understanding of core Machine Learning and Deep Learning concepts (supervised/unsupervised learning, neural networks, optimization).
* Hands-on experience with standard ML frameworks (e.g., PyTorch, TensorFlow, Scikit-Learn).
* Practical experience building applications using LLMs and orchestration frameworks (e.g., OpenAI API, LangChain).
* Familiarity with backend web frameworks (e.g., Django, FastAPI) for creating RESTful APIs.
* Understanding of standard database management systems, particularly relational databases like PostgreSQL.
* Strong problem-solving skills and the ability to write clean, maintainable, and well-documented code.

## **Bonus Points (How to Stand Out)**
* Experience designing and implementing **Agentic AI** workflows (e.g., LangGraph) for complex, multi-step reasoning tasks.
* Knowledge of **Graph Neural Networks (GNNs)** or experience working with **Knowledge Graphs** (e.g., Neo4j) to map complex relationships.
* Hands-on experience with LLM fine-tuning, adapter merging, or model quantization techniques (e.g., **QLoRA, AWQ**).
* Familiarity with modern AI deployment and high-throughput inference engines like **vLLM**.
* Exposure to real-time data processing, such as live audio transcription pipelines (e.g., **faster_whisper**, Redis, Celery).
* A basic understanding of modern frontend frameworks (e.g., **Vue.js**, React) to effectively collaborate with full-stack teams.

## **What We Offer**
* Competitive fresher salary with performance-based bonuses.
* Direct mentorship from senior AI engineers and software architects.
* A hands-on environment where your code directly impacts the product.
* Flexible working hours and comprehensive health benefits.
"""


# ── Startup: write Google credentials from env vars if present ─────────────────
def _write_google_creds_from_env():
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json and not os.path.exists("credentials.json"):
        with open("credentials.json", "w") as f:
            f.write(creds_json)

    token_json = os.getenv("GOOGLE_TOKEN_JSON")
    if token_json and not os.path.exists("token.json"):
        with open("token.json", "w") as f:
            f.write(token_json)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _write_google_creds_from_env()
    yield


app = FastAPI(
    title="Candidate Recruitment API",
    description="Evaluate candidates against a job description and schedule interviews.",
    lifespan=lifespan,
)

# ── CORS (allow frontend origins) ─────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://YOUR_USERNAME.github.io"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ────────────────────────────────────────────────────────────
class AuthRequest(BaseModel):
    email: EmailStr
    password: str


# ── Supabase Auth helpers ──────────────────────────────────────────────────────
def get_current_user(authorization: str = Header(None)):
    """Dependency that extracts and verifies the Supabase JWT token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    # Accept "Bearer <token>" or raw token
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")

    try:
        user_response = supabase.auth.get_user(token)
        return user_response.user
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {e}")


# ── Helpers ─────────────────────────────────────────────────────────────────────
def is_empty(value):
    if value is None:
        return True
    v = str(value).strip().lower()
    return v in ("", "nan", "n/a", "none", "null")


def parse_csv_upload(contents: bytes) -> list[dict]:
    text = contents.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


# ── LLM Helper ─────────────────────────────────────────────────────────────────
def call_llm(prompt: str) -> str:
    response = requests.post(
        url="https://lightning.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "openai/gpt-5-nano",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                }
            ],
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


# ══════════════════════════════════════════════════════════════════════════════
#  EVALUATE CANDIDATES — helpers
# ══════════════════════════════════════════════════════════════════════════════

def download_and_extract_resume(drive_link: str) -> str:
    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = os.path.join(tmp_dir, "resume.pdf")
        gdown.download(drive_link, pdf_path, fuzzy=True, quiet=True)
        text = ""
        with fitz.open(pdf_path) as pdf:
            for page in pdf:
                page_text = page.get_text()
                if page_text.strip():
                    text += page_text + "\n"
    return text


def agent_resume(resume_link: str, candidate_info: dict) -> str:
    resume_text = download_and_extract_resume(resume_link)
    if not resume_text.strip():
        return "Could not extract text from resume."

    system_prompt = (
        "You are an expert technical recruiter. Analyse the candidate's resume "
        "against the provided Job Description. Evaluate their education, skills, "
        "projects, and experience. Give a **brief and concise summary** of "
        "strengths and weaknesses.\n"
    )
    user_prompt = (
        f"Job Description:\n{JOB_DESCRIPTION}\n\n"
        f"Candidate Info — Branch: {candidate_info.get('branch', 'N/A')}, "
        f"CGPA: {candidate_info.get('cgpa', 'N/A')}\n\n"
        f"Resume Text:\n{resume_text}"
    )
    return call_llm(system_prompt + user_prompt)


def fetch_github_repos(github_url: str) -> str:
    username = github_url.rstrip("/").split("/")[-1]
    api_url = f"https://api.github.com/users/{username}/repos"
    resp = requests.get(api_url, params={"per_page": 100, "sort": "updated"}, timeout=30)
    if resp.status_code != 200:
        return f"Could not fetch GitHub repos for {username}."
    repos = resp.json()
    lines = []
    for repo in repos:
        name = repo.get("name", "")
        desc = repo.get("description") or ""
        lang = repo.get("language") or ""
        stars = repo.get("stargazers_count", 0)
        lines.append(f"- {name} ({lang}, {stars}★): {desc}")
    return "\n".join(lines) if lines else "No public repositories found."


def agent_github(github_url: str, best_ai_project: str, research_work: str) -> str:
    repo_info = fetch_github_repos(github_url)

    system_prompt = (
        "You are an expert technical recruiter. Analyse the candidate's GitHub "
        "profile, their best AI project description, and their research work "
        "against the provided Job Description. Evaluate technical depth, "
        "relevance, and quality. Give a concise summary.\n"
    )
    user_prompt = (
        f"Job Description:\n{JOB_DESCRIPTION}\n\n"
        f"GitHub Repositories:\n{repo_info}\n\n"
        f"Best AI Project:\n{best_ai_project}\n\n"
        f"Research Work:\n{research_work}"
    )
    return call_llm(system_prompt + user_prompt)


def agent_verdict(candidate_name: str, resume_analysis: str, github_analysis: str) -> str:
    system_prompt = (
        "You are the hiring manager making the final decision. Based on the "
        "resume analysis and GitHub analysis provided, decide whether this "
        "candidate should proceed to the online test.\n"
        "Reply STRICTLY in this format:\n"
        "Verdict: YES or NO\n"
        "Reason: (one-paragraph justification)\n"
    )
    user_prompt = (
        f"Candidate: {candidate_name}\n\n"
        f"Resume Analysis:\n{resume_analysis}\n\n"
        f"GitHub Analysis:\n{github_analysis}"
    )
    return call_llm(system_prompt + user_prompt)


def send_test_email(recipient: str) -> bool:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your Candidate Assessment Link"
    msg["From"] = SENDER_EMAIL
    msg["To"] = recipient

    body = (
        "Hello,\n\n"
        "Thank you for applying. Please use the link below to complete your "
        "online assessment:\n\n"
        f"  {TEST_LINK}\n\n"
        "This link is valid for 48 hours. If you face any issues, reply to "
        "this email.\n\n"
        "Best regards,\nRecruitment Team\n"
    )
    msg.attach(MIMEText(body, "plain"))

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(SENDER_EMAIL, SENDER_PASSWORD)
                server.sendmail(SENDER_EMAIL, recipient, msg.as_string())
            return True
        except Exception:
            if attempt < max_retries:
                time.sleep(5)
    return False


def evaluate_single_candidate(row: dict, send_emails: bool) -> dict:
    name = row.get("name", "Unknown")
    email = row.get("email", "")
    resume_link = row.get("resume", "").strip()
    github_url = row.get("github", "").strip()
    best_ai_project = row.get("best_ai_project", "")
    research_work = row.get("research_work", "")

    result = {"name": name, "email": email}

    # Instant rejection if resume or GitHub missing
    if is_empty(resume_link) or is_empty(github_url):
        missing = []
        if is_empty(resume_link):
            missing.append("resume")
        if is_empty(github_url):
            missing.append("GitHub profile")
        result["verdict"] = "NO"
        result["reason"] = f"Missing: {', '.join(missing)}"
        return result

    best_ai_project = "" if is_empty(best_ai_project) else best_ai_project.strip()
    research_work = "" if is_empty(research_work) else research_work.strip()

    # Run resume and GitHub analysis in parallel
    analyses = {}

    def run_resume():
        analyses["resume"] = agent_resume(resume_link, row)

    def run_github():
        analyses["github"] = agent_github(github_url, best_ai_project, research_work)

    t1 = threading.Thread(target=run_resume)
    t2 = threading.Thread(target=run_github)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    result["resume_analysis"] = analyses.get("resume", "Error")
    result["github_analysis"] = analyses.get("github", "Error")

    # Final verdict
    verdict_response = agent_verdict(name, result["resume_analysis"], result["github_analysis"])
    result["verdict_raw"] = verdict_response

    selected = "verdict: yes" in verdict_response.lower()
    result["verdict"] = "YES" if selected else "NO"

    # Send email if selected and flag is set
    if selected and send_emails:
        result["email_sent"] = send_test_email(email)
    else:
        result["email_sent"] = False

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEDULE INTERVIEWS — helpers
# ══════════════════════════════════════════════════════════════════════════════

def get_calendar_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                raise RuntimeError(
                    "Google Calendar credentials not configured. "
                    "Set GOOGLE_CREDENTIALS_JSON and GOOGLE_TOKEN_JSON env vars."
                )
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def is_selected(test_la: float, test_code: float) -> bool:
    if test_la >= 60 and test_code >= 60:
        return True
    if (test_la >= 80 and test_code >= 50) or (test_code >= 80 and test_la >= 50):
        return True
    return False


def generate_password(length: int = 10) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))


def schedule_single_interview(service, candidate: dict, start_time, password: str) -> dict:
    end_time = start_time + datetime.timedelta(minutes=INTERVIEW_DURATION_MINUTES)

    description = (
        f"Dear {candidate['name']},\n\n"
        f"Congratulations! Based on your assessment scores, you have been "
        f"shortlisted for the Next Round of Interview.\n\n"
        f"Please join the Google Meet link at the scheduled time.\n"
        f"Best regards,\nRecruitment Team"
    )

    event_body = {
        "summary": f"Interview - {candidate['name']}",
        "description": description,
        "start": {
            "dateTime": start_time.isoformat(),
            "timeZone": TIMEZONE,
        },
        "end": {
            "dateTime": end_time.isoformat(),
            "timeZone": TIMEZONE,
        },
        "attendees": [{"email": candidate["email"]}] + INTERVIEWERS,
        "conferenceData": {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
        "reminders": {"useDefault": True},
    }

    event = (
        service.events()
        .insert(
            calendarId="primary",
            body=event_body,
            conferenceDataVersion=1,
            sendUpdates="all",
        )
        .execute()
    )
    return event


# ══════════════════════════════════════════════════════════════════════════════
#  ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    return {
        "service": "Candidate Recruitment API",
        "endpoints": {
            "/signup": "POST — Create a new account",
            "/login": "POST — Sign in and receive a token",
            "/evaluate": "POST — Upload candidate CSV to evaluate against JD",
            "/schedule": "POST — Upload marks CSV to schedule interviews",
            "/health": "GET  — Health check",
        },
    }


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Auth Endpoints ─────────────────────────────────────────────────────────────
@app.post("/signup")
def signup(body: AuthRequest):
    """Create a new user account via Supabase Auth."""
    try:
        res = supabase.auth.sign_up({"email": body.email, "password": body.password})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if res.user is None:
        raise HTTPException(status_code=400, detail="Signup failed. The email may already be registered.")

    # Return the access token so the frontend can store it immediately
    token = res.session.access_token if res.session else None
    return {"token": token, "email": res.user.email, "user_id": str(res.user.id)}


@app.post("/login")
def login(body: AuthRequest):
    """Sign in an existing user and return an access token."""
    try:
        res = supabase.auth.sign_in_with_password({"email": body.email, "password": body.password})
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

    if res.user is None or res.session is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    return {"token": res.session.access_token, "email": res.user.email, "user_id": str(res.user.id)}


@app.post("/evaluate")
def evaluate_candidates(
    file: UploadFile = File(..., description="CSV with columns: email, branch, cgpa, best_ai_project, research_work, github, resume"),
    send_emails: bool = Query(False, description="Send test-link emails to selected candidates"),
    user=Depends(get_current_user),
):
    """
    Evaluate each candidate's resume and GitHub profile against the job description.
    Returns per-candidate verdict (YES / NO) with analysis details.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    contents = file.file.read()
    rows = parse_csv_upload(contents)

    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty or has no data rows.")

    results = []
    # Process candidates sequentially (each candidate already uses internal parallelism)
    for row in rows:
        try:
            result = evaluate_single_candidate(row, send_emails)
        except Exception as e:
            result = {
                "name": row.get("name", "Unknown"),
                "email": row.get("email", ""),
                "verdict": "ERROR",
                "reason": str(e),
            }
        results.append(result)

    selected = [r for r in results if r["verdict"] == "YES"]
    rejected = [r for r in results if r["verdict"] == "NO"]
    errors = [r for r in results if r["verdict"] == "ERROR"]

    return JSONResponse(
        content={
            "total_candidates": len(results),
            "selected": len(selected),
            "rejected": len(rejected),
            "errors": len(errors),
            "results": results,
        }
    )


@app.post("/schedule")
def schedule_interviews(
    file: UploadFile = File(..., description="CSV with columns: name, email, test_la, test_code"),
    user=Depends(get_current_user),
):
    """
    Read candidate test scores from CSV, filter by selection criteria,
    and schedule Google Calendar interviews with Meet links for selected candidates.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    contents = file.file.read()
    rows = parse_csv_upload(contents)

    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty or has no data rows.")

    # Apply selection criteria
    selected_candidates = []
    rejected_candidates = []
    for row in rows:
        try:
            test_la = float(row.get("test_la", 0))
            test_code = float(row.get("test_code", 0))
        except (ValueError, TypeError):
            rejected_candidates.append({
                "name": row.get("name", "Unknown"),
                "email": row.get("email", ""),
                "reason": "Invalid test scores",
            })
            continue

        if is_selected(test_la, test_code):
            selected_candidates.append({
                "name": row.get("name", "Unknown"),
                "email": row.get("email", ""),
                "test_la": test_la,
                "test_code": test_code,
            })
        else:
            rejected_candidates.append({
                "name": row.get("name", "Unknown"),
                "email": row.get("email", ""),
                "test_la": test_la,
                "test_code": test_code,
                "reason": "Did not meet selection criteria",
            })

    if not selected_candidates:
        return JSONResponse(content={
            "total_candidates": len(rows),
            "selected": 0,
            "rejected": len(rejected_candidates),
            "message": "No candidates met the selection criteria.",
            "rejected_candidates": rejected_candidates,
            "scheduled": [],
        })

    # Authenticate with Google Calendar
    try:
        service = get_calendar_service()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google Calendar auth failed: {e}")

    # Schedule starting tomorrow at 11:30 AM IST (6:00 UTC)
    base_time = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(days=1)
    ).replace(hour=6, minute=0, second=0, microsecond=0)

    scheduled = []
    schedule_errors = []
    for idx, candidate in enumerate(selected_candidates):
        slot_start = base_time + datetime.timedelta(
            minutes=idx * (INTERVIEW_DURATION_MINUTES + INTERVIEW_GAP_MINUTES)
        )
        password = generate_password()
        try:
            event = schedule_single_interview(service, candidate, slot_start, password)
            meet_link = event.get("hangoutLink", "N/A")
            scheduled.append({
                "name": candidate["name"],
                "email": candidate["email"],
                "test_la": candidate["test_la"],
                "test_code": candidate["test_code"],
                "meet_link": meet_link,
                "event_link": event.get("htmlLink", ""),
                "scheduled_time": slot_start.isoformat(),
            })
        except Exception as e:
            schedule_errors.append({
                "name": candidate["name"],
                "email": candidate["email"],
                "error": str(e),
            })

    return JSONResponse(content={
        "total_candidates": len(rows),
        "selected": len(selected_candidates),
        "rejected": len(rejected_candidates),
        "interviews_scheduled": len(scheduled),
        "schedule_errors": len(schedule_errors),
        "scheduled": scheduled,
        "rejected_candidates": rejected_candidates,
        "errors": schedule_errors,
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
