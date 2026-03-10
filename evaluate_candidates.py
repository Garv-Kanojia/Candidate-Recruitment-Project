import csv
import json
import os
import time
import smtplib
import tempfile
import threading
import requests
import gdown
import fitz
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────────
API_KEY         = os.getenv("API_KEY")
SENDER_EMAIL    = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
CSV_PATH        = "test.csv"
TEST_LINK       = "https://recruitment-test.example.com/start?token=ABC123XYZ"

# ── Hardcode your Job Description below ────────────────────────────────────────
JOB_DESCRIPTION = """
# **Job Title: Applied AI Engineer (Entry-Level / Fresher)**

**Department:** Engineering / Data Science
**Experience:** 0-1 Year (Includes Internships/Strong Project Portfolios)
**Location:** Hybrid / Remote 

## **About the Role**
We are looking for a passionate and builder-oriented Applied AI Engineer to join our growing team. In this role, you will bridge the gap between AI research and real-world software. You won’t just be analyzing data; you will be designing intelligent systems, integrating large language models (LLMs) into production environments, and building the backend infrastructure to support them. If you love tackling complex problems and turning AI concepts into functional, scalable products, we want you on our team.

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


# ── LLM Helper ─────────────────────────────────────────────────────────────────
def call_llm(prompt):
    """Send a prompt to the LLM and return the response text."""
    response = requests.post(
        url="https://lightning.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        data=json.dumps({
            "model": "openai/gpt-5-nano",
            "messages": [
            {
                "role": "user",
                "content": [{ "type": "text", "text": prompt }]
            },
            ],
        })
    )
    return json.loads(response.content)["choices"][0]["message"]["content"]


# ── Agent 1: Resume Analyser ──────────────────────────────────────────────────
def download_and_extract_resume(drive_link):
    """Download a resume PDF from Google Drive and return its text."""
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


def agent_resume(resume_link, candidate_info):
    """Agent that analyses the candidate's resume against the JD."""
    resume_text = download_and_extract_resume(resume_link)
    if not resume_text.strip():
        return "Could not extract text from resume."

    system_prompt = """
You are an expert technical recruiter. Analyse the candidate's resume against the provided Job Description. Evaluate their education, skills projects, and experience. Give a **brief and concise summary** of strengths and weaknesses.\n
"""
    user_prompt = f"""
Job Description:\n{JOB_DESCRIPTION}\n\n"
Candidate Info — Branch: {candidate_info['branch']}, CGPA: {candidate_info['cgpa']}\n\n"
Resume Text:\n{resume_text}"
"""
    return call_llm(system_prompt + user_prompt)


# ── Agent 2: GitHub Analyser ──────────────────────────────────────────────────
def fetch_github_repos(github_url):
    """Fetch public repo names and descriptions from a GitHub profile."""
    username = github_url.rstrip("/").split("/")[-1]
    api_url = f"https://api.github.com/users/{username}/repos"
    resp = requests.get(api_url, params={"per_page": 100, "sort": "updated"})
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


def agent_github(github_url, best_ai_project, research_work):
    """Agent that analyses the candidate's GitHub profile, AI project and research."""
    repo_info = fetch_github_repos(github_url)

    system_prompt = """
You are an expert technical recruiter. Analyse the candidate's GitHub profile, their best AI project description, and their research work against the provided Job Description. Evaluate technical depth, relevance, and quality. Give a concise summary.
"""
    user_prompt = f"""
Job Description:
{JOB_DESCRIPTION}

GitHub Repositories:
{repo_info}

Best AI Project:
{best_ai_project}

Research Work:
{research_work}
"""
    return call_llm(system_prompt + user_prompt)


# ── Agent 3: Final Verdict ────────────────────────────────────────────────────
def agent_verdict(candidate_name, resume_analysis, github_analysis):
    """Agent that combines both analyses and gives a final YES / NO verdict."""
    system_prompt = """
You are the hiring manager making the final decision. Based on the resume analysis and GitHub analysis provided, decide whether this candidate should proceed to the online test.
Reply STRICTLY in this format:
Verdict: YES or NO
Reason: (one-paragraph justification)
"""
    user_prompt = f"""
Candidate: {candidate_name}

Resume Analysis:
{resume_analysis}

GitHub Analysis:
{github_analysis}
"""
    return call_llm(system_prompt + user_prompt)


# ── Email Sender (from test_link.py) ──────────────────────────────────────────
def send_test_email(recipient):
    """Send the test link email to a candidate."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your Candidate Assessment Link"
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = recipient

    body = f"""\
Hello,

Thank you for applying. Please use the link below to complete your online assessment:

  {TEST_LINK}

This link is valid for 48 hours. If you face any issues, reply to this email.

Best regards,
Recruitment Team
"""
    msg.attach(MIMEText(body, "plain"))

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(SENDER_EMAIL, SENDER_PASSWORD)
                server.sendmail(SENDER_EMAIL, recipient, msg.as_string())
            print(f"  [OK]  Email sent to {recipient}")
            return True
        except Exception as e:
            print(f"  [FAIL] Attempt {attempt}/{max_retries} for {recipient} — {e}")
            if attempt < max_retries:
                time.sleep(60)

    print(f"  [ERROR] Could not send email to {recipient} after {max_retries} attempts.")
    return False


# ── Helpers ─────────────────────────────────────────────────────────────────────
def is_empty(value):
    """Return True if a CSV value is missing, empty, or NaN."""
    if value is None:
        return True
    v = str(value).strip().lower()
    return v in ("", "nan", "n/a", "none", "null")


# ── Main Pipeline ──────────────────────────────────────────────────────────────
def main():
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name  = row.get("name", "Unknown")
            email = row["email"]
            print(f"\n{'='*60}")
            print(f"Evaluating: {name} ({email})")
            print(f"{'='*60}")

            resume_link     = row.get("resume", "").strip()
            github_url      = row.get("github", "").strip()
            best_ai_project = row.get("best_ai_project", "")
            research_work   = row.get("research_work", "")

            # --- Instant rejection if resume or GitHub is missing ---
            if is_empty(resume_link) or is_empty(github_url):
                missing = []
                if is_empty(resume_link):
                    missing.append("resume")
                if is_empty(github_url):
                    missing.append("GitHub profile")
                print(f"  ❌ {name} is NOT selected — missing: {', '.join(missing)}.")
                continue

            # Clean NaN for optional text fields
            best_ai_project = "" if is_empty(best_ai_project) else best_ai_project.strip()
            research_work   = "" if is_empty(research_work)   else research_work.strip()

            # --- Agent 1 & 2: Run in parallel ---
            results = {}

            def run_resume():
                results["resume"] = agent_resume(resume_link, row)

            def run_github():
                results["github"] = agent_github(github_url, best_ai_project, research_work)

            print("  [Agent 1 & 2] Analysing resume and GitHub in parallel ...")
            t1 = threading.Thread(target=run_resume)
            t2 = threading.Thread(target=run_github)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            resume_analysis = results["resume"]
            github_analysis = results["github"]

            # --- Agent 3: Verdict ---
            print("  [Agent 3] Making final decision ...")
            verdict_response = agent_verdict(name, resume_analysis, github_analysis)
            print(f"  Verdict Response:\n  {verdict_response}\n")

            # --- Send email if YES ---
            if "verdict: yes" in verdict_response.lower():
                print(f"  ✅ {name} is SELECTED — sending test link ...")
                send_test_email(email)
            else:
                print(f"  ❌ {name} is NOT selected.")

    print("\n\nAll candidates processed.")


if __name__ == "__main__":
    main()
