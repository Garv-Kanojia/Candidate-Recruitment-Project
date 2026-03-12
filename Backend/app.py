import csv
import datetime
import io
import json
import logging
import os
import random
import re
import smtplib
import string
import tempfile
import threading
import time
import uuid
import zoneinfo
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import fitz
import gdown
import requests
from dotenv import load_dotenv
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from supabase import create_client, Client

load_dotenv()

logger = logging.getLogger("recruitment")
logging.basicConfig(level=logging.INFO)

# ── Configuration ──────────────────────────────────────────────────────────────
API_KEY = os.getenv("API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")


SUPABASE_URL = os.getenv("SUPABASE_URL")           # e.g. https://xxxx.supabase.co
SUPABASE_KEY = os.getenv("SUPABASE_KEY")           # anon / public key
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # service-role key (for admin ops)
LAMBDA_SERVICE_URL = os.getenv("LAMBDA_SERVICE_URL")  # Base URL of the evaluation HF Space

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY or SUPABASE_KEY)

INTERVIEW_DURATION_MINUTES = 30
INTERVIEW_GAP_MINUTES = 5
TIMEZONE = "Asia/Kolkata"

INTERVIEWERS = [
    {"email": "rajesh.mehta@example.com", "displayName": "Rajesh Mehta"},
    {"email": "ananya.sharma@example.com", "displayName": "Ananya Sharma"},
]

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
# Auth uses Bearer token headers (not cookies), so allow_credentials=False is
# correct and lets us use allow_origins=["*"] to support localhost and GitHub Pages.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ────────────────────────────────────────────────────────────
class AuthRequest(BaseModel):
    email: EmailStr
    password: str

class VacancyUpdate(BaseModel):
    vacancy_count: int


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
def call_llm(prompt: str, model: str) -> str:
    response = requests.post(
        url="https://lightning.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
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

        # Run gdown in a thread with timeout to avoid hanging on Drive rate limits
        download_error = []

        def _download():
            try:
                gdown.download(drive_link, pdf_path, fuzzy=True, quiet=True)
            except Exception as e:
                download_error.append(e)

        dl_thread = threading.Thread(target=_download, daemon=True)
        dl_thread.start()
        dl_thread.join(timeout=120)

        if dl_thread.is_alive():
            logger.warning("gdown download timed out for %s", drive_link)
            return "Resume download timed out."
        if download_error:
            logger.warning("gdown download failed for %s: %s", drive_link, download_error[0])
            return f"Resume download failed: {download_error[0]}"
        if not os.path.exists(pdf_path):
            return "Resume download produced no file."

        text = ""
        with fitz.open(pdf_path) as pdf:
            for page in pdf:
                page_text = page.get_text()
                if page_text.strip():
                    text += page_text + "\n"
    return text


def agent_resume(resume_link: str, candidate_info: dict, jd: str) -> str:
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
        f"Job Description:\n{jd}\n\n"
        f"Candidate Info — Branch: {candidate_info.get('branch', 'N/A')}, "
        f"CGPA: {candidate_info.get('cgpa', 'N/A')}\n\n"
        f"Resume Text:\n{resume_text}"
    )
    return call_llm(system_prompt + user_prompt, "google/gemini-3-flash-preview")


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


def agent_github(github_url: str, best_ai_project: str, research_work: str, jd: str) -> str:
    repo_info = fetch_github_repos(github_url)

    system_prompt = (
        "You are an expert technical recruiter. Analyse the candidate's GitHub "
        "profile, their best AI project description, and their research work "
        "against the provided Job Description. Evaluate technical depth, "
        "relevance, and quality. Give a concise summary.\n"
    )
    user_prompt = (
        f"Job Description:\n{jd}\n\n"
        f"GitHub Repositories:\n{repo_info}\n\n"
        f"Best AI Project:\n{best_ai_project}\n\n"
        f"Research Work:\n{research_work}"
    )
    return call_llm(system_prompt + user_prompt, "openai/gpt-5")


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
    return call_llm(system_prompt + user_prompt, "openai/gpt-5-nano")


def send_test_email(recipient: str, test_link: str) -> bool:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your Candidate Assessment Link"
    msg["From"] = SENDER_EMAIL
    msg["To"] = recipient

    body = (
        "Hello,\n\n"
        "Thank you for applying. Please use the link below to complete your "
        "online assessment:\n\n"
        f"  {test_link}\n\n"
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
            logger.info("Email sent to %s", recipient)
            return True
        except Exception as e:
            logger.warning("Email attempt %d/%d for %s failed: %s", attempt, max_retries, recipient, e)
            if attempt < max_retries:
                time.sleep(5)
    logger.error("Could not send email to %s after %d attempts", recipient, max_retries)
    return False


def evaluate_single_candidate(row: dict, send_emails: bool, jd: str, test_link: str) -> dict:
    name = row.get("name", row.get("email", "Unknown"))
    email = row.get("email", "")
    resume_link = row.get("resume", "").strip()
    github_url = row.get("github", "").strip()
    best_ai_project = row.get("best_ai_project", "")
    research_work = row.get("research_work", "")

    result = {"name": name, "email": email, "resume_link": resume_link}
    logger.info("[%s] Starting evaluation for %s", email, name)

    # Instant rejection if resume or GitHub missing
    if is_empty(resume_link) or is_empty(github_url):
        missing = []
        if is_empty(resume_link):
            missing.append("resume")
        if is_empty(github_url):
            missing.append("GitHub profile")
        result["verdict"] = "NO"
        result["reason"] = f"Missing: {', '.join(missing)}"
        result["email_sent"] = False
        logger.info("[%s] Rejected — missing: %s", email, ', '.join(missing))
        return result

    best_ai_project = "" if is_empty(best_ai_project) else best_ai_project.strip()
    research_work = "" if is_empty(research_work) else research_work.strip()

    # Run resume and GitHub analysis in parallel with timeout
    analyses = {}
    ANALYSIS_TIMEOUT = 180  # seconds

    def run_resume():
        try:
            analyses["resume"] = agent_resume(resume_link, row, jd)
        except Exception as e:
            logger.error("[%s] Resume analysis failed: %s", email, e)
            analyses["resume"] = f"Error during resume analysis: {e}"

    def run_github():
        try:
            analyses["github"] = agent_github(github_url, best_ai_project, research_work, jd)
        except Exception as e:
            logger.error("[%s] GitHub analysis failed: %s", email, e)
            analyses["github"] = f"Error during GitHub analysis: {e}"

    t1 = threading.Thread(target=run_resume, daemon=True)
    t2 = threading.Thread(target=run_github, daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=ANALYSIS_TIMEOUT)
    t2.join(timeout=ANALYSIS_TIMEOUT)

    if t1.is_alive():
        logger.warning("[%s] Resume analysis timed out after %ds", email, ANALYSIS_TIMEOUT)
    if t2.is_alive():
        logger.warning("[%s] GitHub analysis timed out after %ds", email, ANALYSIS_TIMEOUT)

    result["resume_analysis"] = analyses.get("resume", "Analysis timed out or failed")
    result["github_analysis"] = analyses.get("github", "Analysis timed out or failed")

    # Final verdict
    try:
        verdict_response = agent_verdict(name, result["resume_analysis"], result["github_analysis"])
    except Exception as e:
        logger.error("[%s] Verdict LLM call failed: %s", email, e)
        result["verdict"] = "ERROR"
        result["reason"] = f"Verdict generation failed: {e}"
        result["email_sent"] = False
        return result

    result["verdict_raw"] = verdict_response
    logger.info("[%s] Verdict for %s: %s", email, name, verdict_response)

    # Strip markdown formatting (e.g. **Verdict:** YES) and normalize whitespace
    cleaned = re.sub(r"[*_#`]", "", verdict_response).lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    selected = "verdict: yes" in cleaned or "verdict : yes" in cleaned
    result["verdict"] = "YES" if selected else "NO"

    # Extract reason from the LLM response
    reason_match = re.search(r"[Rr]eason\s*:\s*(.+)", verdict_response, re.DOTALL)
    if reason_match:
        result["reason"] = reason_match.group(1).strip()

    # Send email if selected and flag is set
    if selected and send_emails:
        logger.info("[%s] Candidate selected — sending test link email", email)
        result["email_sent"] = send_test_email(email, test_link)
    else:
        result["email_sent"] = False
        if selected:
            logger.info("[%s] Candidate selected but send_emails is disabled", email)

    logger.info("[%s] Evaluation complete — verdict: %s", email, result["verdict"])
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  EVALUATE CANDIDATES — background pipeline (delegates to Lambda service)
# ══════════════════════════════════════════════════════════════════════════════

def _prepare_candidate(row: dict) -> dict | None:
    """Download resume and build a candidate dict matching the Lambda API schema."""
    email = row.get("email", "").strip()
    name = row.get("name", row.get("email", "Unknown"))
    college = row.get("college", row.get("branch", "")).strip()
    gpa_raw = row.get("cgpa", row.get("gpa", None))
    resume_link = row.get("resume", "").strip()
    github_link = row.get("github", "").strip()
    best_ai_project = row.get("best_ai_project", "")
    research_work = row.get("research_work", "")

    gpa = None
    if gpa_raw and not is_empty(gpa_raw):
        try:
            gpa = float(gpa_raw)
        except (ValueError, TypeError):
            gpa = None

    # Download and extract resume text
    resume_data = ""
    if not is_empty(resume_link):
        try:
            resume_data = download_and_extract_resume(resume_link)
        except Exception as e:
            logger.error("[%s] Resume download failed: %s", email, e)

    return {
        "email": email,
        "name": name,
        "gpa": gpa,
        "college": college,
        "best_ai_project": best_ai_project.strip() if not is_empty(best_ai_project) else "",
        "research_work": research_work.strip() if not is_empty(research_work) else "",
        "resume_data": resume_data,
        "github_link": github_link if not is_empty(github_link) else "",
        "resume_link": resume_link,
    }


def background_evaluate(rows: list[dict], jd: str, test_link: str, send_emails: bool, uid: str, callback_url: str = ""):
    """Background task: download resumes, call Lambda service, email accepted candidates."""
    logger.info("Background evaluation started for %d candidates (user: %s)", len(rows), uid)

    # Step 1: Download / parse resumes in parallel and build payload
    candidates_payload = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(_prepare_candidate, rows))
    candidates_payload = [c for c in results if c is not None]

    if not candidates_payload:
        logger.error("No candidates prepared — aborting background evaluation")
        return

    # Step 2: POST to the Lambda evaluation service
    payload = {
        "jd": jd,
        "test_link": test_link,
        "candidates": candidates_payload,
    }

    lambda_url = LAMBDA_SERVICE_URL.rstrip("/") + "/evaluate"
    try:
        logger.info("Sending %d candidates to Lambda service at %s", len(candidates_payload), lambda_url)
        resp = requests.post(lambda_url, json=payload, timeout=600)
        resp.raise_for_status()
        result = resp.json()
        resp.close()  # Immediately close connection to the Lambda service
    except Exception as e:
        logger.error("Lambda service call failed: %s", e)
        # Persist error state so the dashboard reflects the failure
        try:
            supabase.table("evaluation_results").update(
                {"is_latest_batch": False}
            ).eq("user_id", uid).eq("is_latest_batch", True).execute()
        except Exception:
            pass
        error_rows = [
            {
                "user_id": uid,
                "candidate_name": c.get("name", ""),
                "candidate_email": c.get("email", ""),
                "verdict": "ERROR",
                "reason": f"Lambda service call failed: {e}",
                "email_sent": False,
                "resume_link": c.get("resume_link", ""),
                "is_latest_batch": True,
            }
            for c in candidates_payload
        ]
        try:
            supabase.table("evaluation_results").insert(error_rows).execute()
        except Exception:
            pass
        return

    # Step 3: Parse response (connection already closed above)
    test_link_resp = result.get("test_link", test_link)
    candidates_results = result.get("candidates", [])
    logger.info("Lambda service returned %d candidates — connection closed", len(candidates_results))

    # Step 4: Send test-link emails to accepted candidates
    email_results = {}  # email -> bool
    for c in candidates_results:
        accepted = c.get("accepted", False)
        c_email = c.get("email", "")
        score = c.get("score", 0)

        if accepted and send_emails and c_email:
            logger.info("[%s] Accepted (score: %.1f) — sending test link email", c_email, score)
            email_results[c_email] = send_test_email(c_email, test_link_resp)
        elif accepted:
            logger.info("[%s] Accepted (score: %.1f) — emails disabled or no email", c_email, score)
        else:
            logger.info("[%s] Rejected (score: %.1f)", c_email, score)

    # Step 5: Persist results to Supabase (triggers Realtime → frontend receives JSON)
    results_for_db = []
    for c in candidates_results:
        accepted = c.get("accepted", False)
        c_email = c.get("email", "")
        c_name = c.get("Name", "")
        score = c.get("score", 0)
        reason = c.get("reason", "")
        c_resume_link = c.get("resume_link", "")

        results_for_db.append({
            "user_id": uid,
            "candidate_name": c_name,
            "candidate_email": c_email,
            "verdict": "YES" if accepted else "NO",
            "reason": reason,
            "email_sent": email_results.get(c_email, False),
            "resume_link": c_resume_link,
            "is_latest_batch": True,
        })

    try:
        supabase.table("evaluation_results").update(
            {"is_latest_batch": False}
        ).eq("user_id", uid).eq("is_latest_batch", True).execute()
    except Exception as e:
        logger.warning("Failed to clear previous evaluation batch flag: %s", e)

    if results_for_db:
        try:
            supabase.table("evaluation_results").insert(results_for_db).execute()
        except Exception as e:
            logger.warning("Failed to persist evaluation results: %s", e)

    # Step 6: POST only accepted candidates to the frontend callback URL
    if callback_url:
        accepted_for_callback = [
            {
                "name": r["candidate_name"],
                "email": r["candidate_email"],
                "reason": r["reason"],
                "resume_link": r["resume_link"],
                "email_sent": r["email_sent"],
            }
            for r in results_for_db if r["verdict"] == "YES"
        ]
        callback_payload = {
            "event": "evaluation_complete",
            "total_processed": len(results_for_db),
            "total_accepted": len(accepted_for_callback),
            "accepted_candidates": accepted_for_callback,
        }
        try:
            cb_resp = requests.post(callback_url, json=callback_payload, timeout=30)
            logger.info("Callback POST to %s returned %d", callback_url, cb_resp.status_code)
        except Exception as e:
            logger.warning("Callback POST to %s failed: %s", callback_url, e)

    logger.info("Background evaluation completed for user %s", uid)


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

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def is_selected(test_la: float, test_code: float) -> bool:
    if test_la >= 60 and test_code >= 60:
        return True
    if (test_la >= 80 and test_code >= 50) or (test_code >= 80 and test_la >= 50):
        return True
    return False


def generate_password(length: int = 10) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))


def schedule_single_interview(service, candidate: dict, start_time, password: str, duration_minutes: int = 30) -> dict:
    end_time = start_time + datetime.timedelta(minutes=duration_minutes)

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
            "/stats": "GET  — Get dashboard statistics",
            "/settings": "GET/PUT — Read or update user settings (vacancy)",
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


# ── Stats & Settings Endpoints ─────────────────────────────────────────────────
@app.get("/stats")
def get_stats(user=Depends(get_current_user)):
    """Return aggregated dashboard statistics for the authenticated user."""
    uid = str(user.id)

    # Evaluation stats
    eval_rows = supabase.table("evaluation_results").select("verdict").eq("user_id", uid).execute().data
    eval_total = len(eval_rows)
    eval_accepted = sum(1 for r in eval_rows if r["verdict"] == "YES")
    eval_rejected = sum(1 for r in eval_rows if r["verdict"] == "NO")
    eval_errors = sum(1 for r in eval_rows if r["verdict"] == "ERROR")
    eval_pct = round((eval_accepted / eval_total * 100), 1) if eval_total else 0

    # Evaluation last batch (all candidates from most recent run)
    eval_last = (
        supabase.table("evaluation_results")
        .select("candidate_name, candidate_email, verdict, reason, resume_link")
        .eq("user_id", uid)
        .eq("is_latest_batch", True)
        .execute()
        .data
    )
    eval_last_batch = [
        {
            "name": r["candidate_name"],
            "email": r["candidate_email"],
            "verdict": r.get("verdict", ""),
            "reason": r.get("reason", ""),
            "resume_link": r.get("resume_link", ""),
        }
        for r in eval_last
    ]

    # Schedule stats
    sched_rows = supabase.table("schedule_results").select("status").eq("user_id", uid).execute().data
    sched_total = len(sched_rows)
    sched_scheduled = sum(1 for r in sched_rows if r["status"] == "SCHEDULED")
    sched_rejected = sum(1 for r in sched_rows if r["status"] == "REJECTED")
    sched_errors = sum(1 for r in sched_rows if r["status"] == "ERROR")
    sched_pct = round((sched_scheduled / sched_total * 100), 1) if sched_total else 0

    # Schedule last batch (all candidates from most recent run)
    sched_last = (
        supabase.table("schedule_results")
        .select("candidate_name, candidate_email, test_la, test_code, meet_link, status")
        .eq("user_id", uid)
        .eq("is_latest_batch", True)
        .execute()
        .data
    )
    sched_last_batch = [
        {
            "name": r["candidate_name"],
            "email": r["candidate_email"],
            "test_la": r.get("test_la", ""),
            "test_code": r.get("test_code", ""),
            "meet_link": r.get("meet_link", ""),
            "status": r.get("status", ""),
        }
        for r in sched_last
    ]

    return {
        "evaluation": {
            "total": eval_total,
            "accepted": eval_accepted,
            "rejected": eval_rejected,
            "errors": eval_errors,
            "acceptance_pct": eval_pct,
            "last_batch": eval_last_batch,
        },
        "scheduling": {
            "total": sched_total,
            "scheduled": sched_scheduled,
            "rejected": sched_rejected,
            "errors": sched_errors,
            "acceptance_pct": sched_pct,
            "last_batch": sched_last_batch,
        },
    }


@app.get("/settings")
def get_settings(user=Depends(get_current_user)):
    """Return user settings (vacancy count)."""
    uid = str(user.id)
    rows = supabase.table("user_settings").select("*").eq("user_id", uid).execute().data
    if rows:
        return {"vacancy_count": rows[0]["vacancy_count"]}
    return {"vacancy_count": 10}


@app.put("/settings")
def update_settings(body: VacancyUpdate, user=Depends(get_current_user)):
    """Update user settings (vacancy count). Creates row if not exists."""
    uid = str(user.id)
    vacancy = max(1, body.vacancy_count)  # at least 1
    supabase.table("user_settings").upsert({
        "user_id": uid,
        "vacancy_count": vacancy,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }).execute()
    return {"vacancy_count": vacancy}


@app.post("/evaluate")
def evaluate_candidates(
    file: UploadFile = File(..., description="CSV with columns: email, name, branch/college, cgpa, best_ai_project, research_work, github, resume"),
    jd: str = Form(..., description="Job description to evaluate candidates against"),
    test_link: str = Form(..., description="Assessment test link sent to selected candidates"),
    send_emails: bool = Query(False, description="Send test-link emails to selected candidates"),
    callback_url: str = Form("", description="Optional URL the backend will POST accepted candidates to when evaluation finishes"),
    user=Depends(get_current_user),
):
    """
    Accept a candidate CSV and immediately return 202 Accepted.
    Processing (resume download, Lambda evaluation, emailing) happens in the background.
    Results are persisted to the database and can be retrieved via GET /stats.
    If callback_url is provided, the backend will POST only the accepted candidates to it when done.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    contents = file.file.read()
    rows = parse_csv_upload(contents)

    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty or has no data rows.")

    if not LAMBDA_SERVICE_URL:
        raise HTTPException(status_code=500, detail="Evaluation service URL is not configured.")

    uid = str(user.id)

    # Spawn background thread — the frontend gets an immediate response
    thread = threading.Thread(
        target=background_evaluate,
        args=(rows, jd, test_link, send_emails, uid, callback_url),
        daemon=True,
    )
    thread.start()

    return JSONResponse(
        content={
            "message": "Evaluation started. Candidates are being processed in the background.",
            "total_candidates": len(rows),
        },
        status_code=202,
    )


@app.post("/schedule")
def schedule_interviews(
    file: UploadFile = File(..., description="CSV with columns: name, email, test_la, test_code"),
    start_date: str = Form("", description="Interview date (YYYY-MM-DD). Defaults to tomorrow."),
    start_time: str = Form("11:30", description="Interview start time (HH:MM, 24h). Defaults to 11:30."),
    duration: int = Form(30, description="Interview duration in minutes. Defaults to 30."),
    gap: int = Form(5, description="Gap between interviews in minutes. Defaults to 5."),
    callback_url: str = Form("", description="Optional URL the backend will POST scheduled candidates to when done"),
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

    # Clear previous latest-batch flag for this user's schedule results
    uid = str(user.id)
    try:
        supabase.table("schedule_results").update(
            {"is_latest_batch": False}
        ).eq("user_id", uid).eq("is_latest_batch", True).execute()
    except Exception as e:
        logger.warning("Failed to clear previous schedule batch flag: %s", e)

    # Persist rejected candidates to Supabase
    if rejected_candidates:
        rej_db_rows = [
            {
                "user_id": uid,
                "candidate_name": r.get("name", ""),
                "candidate_email": r.get("email", ""),
                "test_la": r.get("test_la"),
                "test_code": r.get("test_code"),
                "status": "REJECTED",
                "reason": r.get("reason", "Did not meet selection criteria"),
                "is_latest_batch": True,
            }
            for r in rejected_candidates
        ]
        try:
            supabase.table("schedule_results").insert(rej_db_rows).execute()
        except Exception as e:
            logger.warning("Failed to persist rejected schedule results: %s", e)

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

    # Compute base time from user-supplied date/time or defaults
    duration = max(10, min(duration, 120))  # clamp 10-120 minutes
    gap = max(0, min(gap, 60))              # clamp 0-60 minutes

    if start_date.strip():
        try:
            date_obj = datetime.date.fromisoformat(start_date.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD.")
    else:
        date_obj = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).date()

    try:
        hour, minute = map(int, start_time.strip().split(":"))
    except (ValueError, AttributeError):
        hour, minute = 11, 30

    # Convert IST (UTC+5:30) input to UTC
    ist = zoneinfo.ZoneInfo("Asia/Kolkata")
    local_start = datetime.datetime(date_obj.year, date_obj.month, date_obj.day, hour, minute, tzinfo=ist)
    base_time = local_start.astimezone(datetime.timezone.utc)

    scheduled = []
    schedule_errors = []
    for idx, candidate in enumerate(selected_candidates):
        slot_start = base_time + datetime.timedelta(
            minutes=idx * (duration + gap)
        )
        password = generate_password()
        try:
            event = schedule_single_interview(service, candidate, slot_start, password, duration_minutes=duration)
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

    # Persist scheduled + error rows to Supabase
    sched_db_rows = [
        {
            "user_id": uid,
            "candidate_name": s["name"],
            "candidate_email": s["email"],
            "test_la": s["test_la"],
            "test_code": s["test_code"],
            "status": "SCHEDULED",
            "meet_link": s.get("meet_link"),
            "scheduled_time": s.get("scheduled_time"),
            "is_latest_batch": True,
        }
        for s in scheduled
    ] + [
        {
            "user_id": uid,
            "candidate_name": e["name"],
            "candidate_email": e["email"],
            "status": "ERROR",
            "reason": e.get("error", ""),
            "is_latest_batch": True,
        }
        for e in schedule_errors
    ]
    if sched_db_rows:
        try:
            supabase.table("schedule_results").insert(sched_db_rows).execute()
        except Exception as exc:
            logger.warning("Failed to persist schedule results: %s", exc)

    # POST only scheduled (accepted) candidates to the frontend callback URL
    if callback_url and scheduled:
        scheduled_for_callback = [
            {
                "name": s["name"],
                "email": s["email"],
                "test_la": s["test_la"],
                "test_code": s["test_code"],
                "meet_link": s.get("meet_link", ""),
                "scheduled_time": s.get("scheduled_time", ""),
            }
            for s in scheduled
        ]
        callback_payload = {
            "event": "scheduling_complete",
            "total_processed": len(rows),
            "total_scheduled": len(scheduled),
            "scheduled_candidates": scheduled_for_callback,
        }
        try:
            cb_resp = requests.post(callback_url, json=callback_payload, timeout=30)
            logger.info("Callback POST to %s returned %d", callback_url, cb_resp.status_code)
        except Exception as e:
            logger.warning("Callback POST to %s failed: %s", callback_url, e)

    response = {
        "total_candidates": len(rows),
        "interviews_scheduled": len(scheduled),
        "scheduled": scheduled,
    }

    return JSONResponse(content=response)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
