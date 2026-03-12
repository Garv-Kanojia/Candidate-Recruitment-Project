# Candidate Recruitment System

An automated recruitment platform that evaluates candidates based on their resumes, GitHub profiles, and test scores, and schedules interviews for selected candidates.

## Architecture

The project is divided into three main components:

1.  **Frontend (`frontend/`)**: A static web application built with HTML, CSS, and JavaScript. It provides a recruiter dashboard for uploading candidate CSVs, viewing live evaluation progress via Supabase Realtime, and scheduling interviews.
2.  **Main Backend (`Backend/`)**: A FastAPI application that serves as the primary API gateway. It handles user authentication (via Supabase), parses uploaded CSV files, coordinates background evaluations, sends automated emails using SMTP, and schedules Google Meet interviews via the Google Calendar API.
3.  **Evaluation Service (`resume_github_analysis/`)**: A microservice built with FastAPI that acts as the analysis engine. It leverages AWS Bedrock (Llama 3 70B) and the GitHub API to evaluate candidate resumes, assess GitHub repository code quality and relevance, and compute a final weighted score based on custom criteria.

## Detailed Evaluation Pipeline

### 1. Resume Parsing & Project Extraction
- **Text Extraction:** Candidate resumes are downloaded via Google Drive links and converted into raw text using the `PyMuPDF` (`fitz`) library in the main backend.
- **Entity Extraction (LLM):** The evaluation microservice sends the raw resume text, alongside the candidate's self-reported "Best AI Project" and "Research Work", to AWS Bedrock (Llama 3 70B). A single LLM call extracts a definitive list of project names from the resume and maps whether the external AI/Research projects are already represented within the document.

### 2. GitHub Profile Analysis
The system employs a targeted, token-efficient approach to evaluate a candidate's coding abilities without overwhelming the LLM context window:
- **Repository Selection:** The system selects a maximum of 3 repositories from the candidate's profile based on a strict priority hierarchy:
  1. Repositories fuzzy-matching the name of the "Best AI Project".
  2. Repositories fuzzy-matching the "Research Work" (if not already covered in the resume).
  3. Repositories fuzzy-matching any extracted resume projects.
  4. Remaining slots are filled by recent (updated within the last 365 days), non-forked repositories, sorted by star count.
- **Smart File Fetching (Knowledge Tree Strategy):** For each selected repository, the system fetches the entire recursive file tree via the GitHub API and ranks files by importance. 
  - Absolute priority (Priority 0) is given to core structural files and entry points (e.g., `README.md`, `main.py`, `requirements.txt`, `package.json`, `Dockerfile`).
  - Standard source code extensions (`.py`, `.ts`, `.cpp`) are ranked by their directory depth, prioritizing shallower files (Priority 1 + depth).
  - Common build and environment directories are explicitly ignored (e.g., `node_modules`, `.venv`, `__pycache__`).
  - Only the top 12 prioritized files are fetched, with their contents truncated to a maximum of 3,000 characters each.
- **Code-Level LLM Evaluation:** The selected file contents are sent to the LLM, which grades the repository on a 0-100 scale by answering four fixed questions:
  - **Relevance:** Which specific skills from the Job Description (JD) are demonstrated?
  - **Code Quality:** What does the structure and style reveal about the developer?
  - **Maturity:** How production-ready is the codebase (tests, docs, CI, error handling)?
  - **Standout:** What is the single most technically impressive aspect?

### 3. Final Candidate Scoring
The system aggregates all signals and provides the LLM with the complete context: the JD, candidate demographics (GPA, College), project descriptions, raw resume text, and the aggregated GitHub repository evaluations. The LLM assigns a 0-100 score for six distinct dimensions, which are then deterministically weighted by the backend to prevent LLM arithmetic errors:
- **GitHub Score (25%)**: Averaged repository scores based on code quality and JD relevance.
- **Resume Score (25%)**: Overall experience, skill match, and structure against the JD.
- **Best AI Project (20%)**: Depth, originality, and technical sophistication.
- **Research Work (20%)**: Quality and impact of research.
- **GPA (5%)**: Academic performance mapped to a 100-point scale.
- **College (5%)**: Reputation and ranking of the institution for the field.

The system calculates the final weighted score out of 100. The LLM also generates a concise, 3-line plain-English justification for the recruiter. Candidates achieving a final score of 70 or higher are flagged as `accepted` for the next stage of the pipeline.

## Prerequisites

- **Supabase**: A Supabase project is required for authentication, real-time database updates, and storing evaluation/scheduling results.
- **Google Cloud Console**: OAuth credentials (`credentials.json` and `token.json`) with Google Calendar API enabled for scheduling interviews.
- **AWS**: AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`) with access to AWS Bedrock for the LLM evaluation.
- **GitHub**: A Personal Access Token (`GITHUB_TOKEN`) to fetch candidate repository data and file structures.

## Environment Variables

### Main Backend (`Backend/.env`)
- `API_KEY`: API key for external LLM API (if using default wrappers).
- `SENDER_EMAIL`: Email address for sending assessment links.
- `SENDER_PASSWORD`: App password for the sender email.
- `SUPABASE_URL`: Your Supabase project URL.
- `SUPABASE_KEY`: Supabase Anon/Public Key.
- `SUPABASE_SERVICE_KEY`: Supabase Service Role Key.
- `LAMBDA_SERVICE_URL`: URL of the deployed `resume_github_analysis` service.
- `GOOGLE_CREDENTIALS_JSON`: Stringified Google Calendar credentials (optional, can use file).
- `GOOGLE_TOKEN_JSON`: Stringified Google Calendar token (optional, can use file).

### Evaluation Service (`resume_github_analysis/.env`)
- `GITHUB_TOKEN`: GitHub personal access token.
- `AWS_ACCESS_KEY_ID`: AWS Access Key.
- `AWS_SECRET_ACCESS_KEY`: AWS Secret Key.
- `AWS_DEFAULT_REGION`: AWS Region (e.g., `us-east-1`).

### Frontend (`frontend/app.js` & `frontend/auth.js`)
Update the constants at the top of the JS files:
- `API_BASE`: URL of the Main Backend.
- `SUPABASE_URL`: Your Supabase project URL.
- `SUPABASE_ANON_KEY`: Your Supabase Anon Key.
