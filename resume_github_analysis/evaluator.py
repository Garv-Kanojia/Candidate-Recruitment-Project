import json, re, boto3
from config import WEIGHTS
from models import CandidateInput, RepoData, RepoScore, CandidateResult

_bedrock  = boto3.client('bedrock-runtime', region_name='us-east-1')
_model_id = 'us.meta.llama3-1-70b-instruct-v1:0'


def _ask(prompt: str, max_tokens=1200) -> str:
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


# ── per-repo evaluation ──────────────────────────────────────────────────────

def evaluate_repo(repo: RepoData, jd_text: str) -> RepoScore:
    """
    Sends the repo's knowledge tree (file tree + file contents) to the LLM.
    Answers 4 fixed questions, produces a 0-100 score and a one-line judgement.
    """
    files_block = "\n\n".join(
        f"=== {path} ===\n{content}" for path, content in repo.key_files.items()
    )

    prompt = f"""You are a senior technical interviewer evaluating a GitHub repository for this role.

JOB DESCRIPTION:
{jd_text}

REPOSITORY: {repo.name} | Language: {repo.language} | Stars: {repo.stars} | Fork: {repo.is_fork}
Description: {repo.description}
Last commit: {repo.last_commit}

FILE TREE (selected files only):
{chr(10).join(repo.file_tree)}

FILE CONTENTS:
{files_block}

Answer each question in 2 sentences max, then score the repo:

Q1 [Relevance]    — Which specific skills from the JD are demonstrated here, if any?
Q2 [Code Quality] — What does the code structure and style reveal about this developer?
Q3 [Maturity]     — How production-ready is this? Consider: tests, docs, CI, error handling.
Q4 [Standout]     — What is the single most technically impressive thing in this repo?

Score out of 100 = weighted combination of relevance to JD + code quality + originality.

Respond ONLY in this JSON (no extra text):
{{
  "q1": "...", "q2": "...", "q3": "...", "q4": "...",
  "score": <0-100>,
  "summary": "<one-line judgement for a recruiter>"
}}"""

    data = _parse_json(_ask(prompt))
    return RepoScore(
        name     = repo.name,
        language = repo.language,
        stars    = repo.stars,
        is_fork  = repo.is_fork,
        score    = float(data.get("score", 50)),
        summary  = data.get("summary", "Could not evaluate."),
        qa       = {k: data.get(k, "") for k in ["q1", "q2", "q3", "q4"]},
    )


# ── final candidate scoring ──────────────────────────────────────────────────

def score_candidate(candidate: CandidateInput, repo_scores: list[RepoScore]) -> CandidateResult:
    """
    Gives the LLM all candidate signals and the GitHub repo analysis.
    Returns per-dimension scores (0-100), a weighted final score, and 3-line reasoning.
    """
    github_avg = sum(r.score for r in repo_scores) / len(repo_scores) if repo_scores else 0

    repo_block = "\n".join(
        f"  - {r.name} | Language: {r.language} | Stars: {r.stars} | Fork: {r.is_fork} "
        f"| Score: {r.score:.0f}/100 | Judgement: {r.summary}"
        for r in repo_scores
    ) if repo_scores else "  No GitHub data available (candidate did not provide a GitHub link)."

    ai_project_text = candidate.best_ai_project.strip() if candidate.best_ai_project.strip() else "Not provided."
    research_text   = candidate.research_work.strip() if candidate.research_work.strip() else "Not provided."
    gpa_text        = str(candidate.gpa) if candidate.gpa else "Not provided"

    w = WEIGHTS
    prompt = f"""You are a lead technical recruiter making a final candidate recommendation.

JOB DESCRIPTION:
{candidate.jd_text}

CANDIDATE PROFILE:
  College : {candidate.college}
  GPA     : {candidate.gpa}

  Best AI Project:
  {ai_project_text}

  Research Work:
  {research_text}

RESUME:
{candidate.resume_text[:2000]}

GITHUB ANALYSIS (avg repo score: {github_avg:.1f}/100):
{repo_block}

Score the candidate on EACH of these dimensions (0-100):
  1. github_score    — Quality and relevance of their GitHub repos (use the repo scores above as reference; the average is {github_avg:.1f}).
  2. resume_score    — Overall resume strength: experience, skills, structure, relevance to JD.
  3. ai_project_score — Depth, originality, and technical sophistication of their best AI project.
  4. research_score  — Quality and impact of their research work.
  5. gpa_score       — Academic performance (GPA {gpa_text} on a 10-point scale → map to 0-100; if not provided, score 0).
  6. college_score   — Reputation and ranking of {candidate.college} for this field.

Then compute the final weighted score:
  final_score = github_score × {w['github']} + resume_score × {w['resume']} + ai_project_score × {w['ai_proj']} + research_score × {w['research']} + gpa_score × {w['gpa']} + college_score × {w['college']}

Finally write EXACTLY 3 lines of plain English reasoning for a non-technical recruiter.
Be specific, honest, and direct. No bullet points.

Respond ONLY in this JSON (no extra text):
{{
  "github_score": <0-100>,
  "resume_score": <0-100>,
  "ai_project_score": <0-100>,
  "research_score": <0-100>,
  "gpa_score": <0-100>,
  "college_score": <0-100>,
  "final_score": <0-100>,
  "reasoning": "<line 1>\\n<line 2>\\n<line 3>"
}}"""

    data = _parse_json(_ask(prompt, max_tokens=600))

    github_s  = float(data.get("github_score", github_avg))
    resume_s  = float(data.get("resume_score", 50))
    ai_proj_s = float(data.get("ai_project_score", 50))
    research_s = float(data.get("research_score", 50))
    gpa_s     = float(data.get("gpa_score", (candidate.gpa or 0) * 10))
    college_s = float(data.get("college_score", 50))

    # Deterministic weighted score — never trust the LLM's arithmetic
    computed_final = (
        github_s  * w["github"]
      + resume_s  * w["resume"]
      + ai_proj_s * w["ai_proj"]
      + research_s * w["research"]
      + gpa_s     * w["gpa"]
      + college_s * w["college"]
    )

    return CandidateResult(
        final_score      = round(computed_final, 1),
        reasoning        = data.get("reasoning", "Analysis complete."),
        github_score     = round(github_s, 1),
        resume_score     = round(resume_s, 1),
        ai_project_score = round(ai_proj_s, 1),
        research_score   = round(research_s, 1),
        gpa_score        = round(gpa_s, 1),
        college_score    = round(college_s, 1),
        repo_scores      = repo_scores,
    )