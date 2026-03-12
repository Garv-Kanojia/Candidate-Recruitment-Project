from urllib.parse import urlparse
from fastapi import FastAPI
from models import (
    CandidateInput, EvaluationRequest, EvaluationResponse, CandidateResponse,
)
from github_handler import parse_candidate_projects, select_repos, fetch_repo_data
from evaluator import evaluate_repo, score_candidate

app = FastAPI(title="Candidate Evaluation API")


# ── helpers ───────────────────────────────────────────────────────────────────

def _extract_github_username(link: str) -> str:
    """Extract username from a GitHub profile URL."""
    if not link or not link.strip():
        return ""
    link = link.strip().rstrip("/")
    if not link.startswith("http"):
        link = "https://" + link
    parsed = urlparse(link)
    parts = parsed.path.strip("/").split("/")
    return parts[0] if parts and parts[0] else ""


def _analyze_candidate(candidate: CandidateInput) -> dict:
    """Run the full evaluation pipeline for a single candidate."""
    repo_scores = []

    # GitHub analysis — only if a username was provided
    if candidate.github_username:
        print(f"\n  [1/4] Parsing resume projects for {candidate.github_username}...")
        parsed = parse_candidate_projects(
            candidate.resume_text,
            candidate.best_ai_project,
            candidate.research_work,
        )
        resume_projects    = parsed["projects"]
        ai_in_resume       = parsed["ai_in_resume"]
        research_in_resume = parsed["research_in_resume"]

        print("  [2/4] Selecting GitHub repos...")
        raw_repos = select_repos(
            candidate.github_username,
            resume_projects,
            candidate.best_ai_project,
            candidate.research_work,
            ai_in_resume,
            research_in_resume,
        )

        print(f"  [3/4] Evaluating {len(raw_repos)} repos...")
        for raw in raw_repos:
            repo_data = fetch_repo_data(raw)
            score     = evaluate_repo(repo_data, candidate.jd_text)
            repo_scores.append(score)
            print(f"        {raw['name']}  [{score.score:.0f}/100]")
    else:
        print("  [1-3/4] Skipped — no GitHub link provided.")

    print("  [4/4] Computing final score...")
    result = score_candidate(candidate, repo_scores)

    return {
        "final_score": result.final_score,
        "reasoning":   result.reasoning,
    }


# ── API endpoint ──────────────────────────────────────────────────────────────

@app.post("/evaluate", response_model=EvaluationResponse)
def evaluate_candidates(request: EvaluationRequest):
    results: list[CandidateResponse] = []

    for idx, cand in enumerate(request.candidates, 1):
        print(f"\n{'='*60}\nCandidate {idx}: {cand.name or '(no name)'}")

        # ── Mandatory-field rejection ────────────────────────────────
        if not cand.email or not cand.email.strip():
            results.append(CandidateResponse(
                Name=cand.name, email=cand.email, score=0,
                reason="Rejected: Email not provided.",
                resume_link=cand.resume_link, accepted=False,
            ))
            print("  -> Rejected (missing email)")
            continue

        if not cand.college or not cand.college.strip():
            results.append(CandidateResponse(
                Name=cand.name, email=cand.email, score=0,
                reason="Rejected: College information not provided.",
                resume_link=cand.resume_link, accepted=False,
            ))
            print("  -> Rejected (missing college)")
            continue

        if not cand.resume_data or not cand.resume_data.strip():
            results.append(CandidateResponse(
                Name=cand.name, email=cand.email, score=0,
                reason="Rejected: Resume data not provided.",
                resume_link=cand.resume_link, accepted=False,
            ))
            print("  -> Rejected (missing resume)")
            continue

        # ── Build internal model & run pipeline ──────────────────────
        candidate_input = CandidateInput(
            github_username = _extract_github_username(cand.github_link),
            resume_text     = cand.resume_data,
            best_ai_project = cand.best_ai_project or "",
            research_work   = cand.research_work or "",
            gpa             = cand.gpa if cand.gpa is not None else 0.0,
            college         = cand.college,
            jd_text         = request.jd,
        )

        result = _analyze_candidate(candidate_input)
        score  = result["final_score"]

        results.append(CandidateResponse(
            Name        = cand.name,
            email       = cand.email,
            score       = round(score, 1),
            reason      = result["reasoning"],
            resume_link = cand.resume_link,
            accepted    = score >= 70,
        ))
        print(f"  -> Score: {score:.1f}  |  Accepted: {score >= 70}")

    return EvaluationResponse(test_link=request.test_link, candidates=results)
