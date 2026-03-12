import base64, json, re, requests, boto3
from datetime import datetime, timedelta
from config import *
from models import RepoData

_gh_headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}
_bedrock  = boto3.client('bedrock-runtime', region_name='us-east-1')
_model_id = 'us.meta.llama3-1-70b-instruct-v1:0'


# ── helpers ─────────────────────────────────────────────────────────────────

def _gh(url: str):
    r = requests.get(url, headers=_gh_headers, timeout=15)
    r.raise_for_status()
    return r.json()

def _ask(prompt: str, max_tokens=400) -> str:
    response = _bedrock.converse(
        modelId=_model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens},
    )
    return response['output']['message']['content'][0]['text']

def _parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        return json.loads(m.group()) if m else {}
    except json.JSONDecodeError:
        return {}

def _fuzzy_match(repo_name: str, project_names: list[str]) -> bool:
    """Word-overlap match between a repo name and a list of project names."""
    repo_words = set(repo_name.lower().replace("-", " ").replace("_", " ").split())
    for proj in project_names:
        proj_words = {w for w in proj.lower().replace("-", " ").replace("_", " ").split() if len(w) > 3}
        if proj_words and proj_words & repo_words:
            return True
    return False

def _file_priority(path: str) -> int:
    filename = path.split("/")[-1]
    if any(skip in path for skip in SKIP_DIRS):
        return 9999
    if filename in PRIORITY_FILENAMES:
        return 0
    ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
    if ext in PRIORITY_EXTENSIONS:
        return 1 + path.count("/")   # shallower = higher priority
    return 999


# ── project parsing (single LLM call) ───────────────────────────────────────

def parse_candidate_projects(resume_text: str, best_ai_project: str, research_work: str) -> dict:
    """
    One Claude call that:
      1. Extracts project names from the resume
      2. Tells us whether best_ai_project / research_work are already covered by those resume projects
    Returns: {"projects": [...], "ai_in_resume": bool, "research_in_resume": bool}
    """
    text = _ask(f"""Analyze this resume and return a JSON object with exactly these keys:
- "projects": list of project name strings found in the resume
- "ai_in_resume": true if the Best AI Project description refers to something already in the resume projects, else false
- "research_in_resume": true if the Research Work description refers to something already in the resume projects, else false

Resume:
{resume_text}

Best AI Project: {best_ai_project}
Research Work: {research_work}

Return ONLY valid JSON, nothing else.""")
    
    result = _parse_json(text)
    return {
        "projects":           result.get("projects", []),
        "ai_in_resume":       bool(result.get("ai_in_resume", False)),
        "research_in_resume": bool(result.get("research_in_resume", False)),
    }


# ── repo selection ───────────────────────────────────────────────────────────

def select_repos(
    username:        str,
    resume_projects: list[str],
    best_ai_project: str,
    research_work:   str,
    ai_in_resume:    bool,
    research_in_resume: bool,
) -> list[dict]:
    """
    Priority order (cap: MAX_REPOS = 3):
      1. Repo matching best_ai_project (highest priority)
      2. Repo matching research_work   (if NOT already in resume)
      3. Repos matching resume project names
      4. Recent (<12 months), non-fork repos sorted by stars to fill remaining slots
    """
    all_repos = _gh(f"https://api.github.com/users/{username}/repos?per_page=100&sort=updated")
    cutoff    = datetime.now() - timedelta(days=REPO_AGE_DAYS)
    selected, seen = [], set()

    def add(repo):
        if repo["name"] not in seen and len(selected) < MAX_REPOS:
            selected.append(repo)
            seen.add(repo["name"])

    # 1. Best AI project (highest priority — always try to include)
    for repo in all_repos:
        if _fuzzy_match(repo["name"], [best_ai_project]) and repo["name"] not in seen:
            add(repo)
            break

    # 2. Research work (if it's a different project)
    if not research_in_resume:
        for repo in all_repos:
            if _fuzzy_match(repo["name"], [research_work]) and repo["name"] not in seen:
                add(repo)
                break

    # 3. Resume project matches (no age restriction — they are explicitly listed)
    for repo in all_repos:
        if _fuzzy_match(repo["name"], resume_projects):
            add(repo)

    # 4. Recent non-fork repos to fill remaining slots
    if len(selected) < MAX_REPOS:
        recent = [
            r for r in all_repos
            if r["name"] not in seen
            and not r.get("fork", False)
            and datetime.strptime(r["pushed_at"], "%Y-%m-%dT%H:%M:%SZ") > cutoff
        ]
        recent.sort(key=lambda r: r.get("stargazers_count", 0), reverse=True)
        for repo in recent:
            add(repo)

    return selected


# ── repo data fetching ───────────────────────────────────────────────────────

def _fetch_key_files(full_name: str) -> dict[str, str]:
    """
    Knowledge tree strategy:
      1. Pull full recursive file tree from GitHub (one API call, no content yet)
      2. Score and rank every file path by priority
      3. Fetch actual content only for top MAX_FILES_PER_REPO files
    Returns {path: truncated_content}
    """
    try:
        tree_data = _gh(f"https://api.github.com/repos/{full_name}/git/trees/HEAD?recursive=1")
    except Exception:
        return {}

    blobs = [
        item["path"] for item in tree_data.get("tree", [])
        if item["type"] == "blob" and not any(s in item["path"] for s in SKIP_DIRS)
    ]
    blobs.sort(key=_file_priority)
    selected = blobs[:MAX_FILES_PER_REPO]

    files = {}
    for path in selected:
        try:
            data = _gh(f"https://api.github.com/repos/{full_name}/contents/{path}")
            if isinstance(data, dict) and data.get("encoding") == "base64":
                content = base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
                files[path] = content[:MAX_FILE_CHARS]
        except Exception:
            continue
    return files


def fetch_repo_data(repo: dict) -> RepoData:
    key_files = _fetch_key_files(repo["full_name"])
    return RepoData(
        name        = repo["name"],
        url         = repo["html_url"],
        language    = repo.get("language") or "Unknown",
        stars       = repo.get("stargazers_count", 0),
        last_commit = repo.get("pushed_at", ""),
        description = repo.get("description") or "",
        is_fork     = repo.get("fork", False),
        file_tree   = list(key_files.keys()),
        key_files   = key_files,
    )