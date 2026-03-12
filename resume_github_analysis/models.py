from dataclasses import dataclass, field
from typing import Optional
from pydantic import BaseModel


# ── Pydantic models for API request / response ──────────────────────────────

class CandidatePayload(BaseModel):
    email: str = ""
    name: str = ""
    gpa: Optional[float] = None
    college: str = ""
    best_ai_project: str = ""
    research_work: str = ""
    resume_data: str = ""
    github_link: str = ""
    resume_link: str = ""

class EvaluationRequest(BaseModel):
    jd: str
    test_link: str
    candidates: list[CandidatePayload]

class CandidateResponse(BaseModel):
    Name: str
    email: str
    score: float
    reason: str
    resume_link: str
    accepted: bool

class EvaluationResponse(BaseModel):
    test_link: str
    candidates: list[CandidateResponse]


# ── Internal dataclasses ─────────────────────────────────────────────────────

@dataclass
class CandidateInput:
    github_username: str
    resume_text:     str
    best_ai_project: str   # free-text description
    research_work:   str   # free-text description
    gpa:             float
    college:         str
    jd_text:         str

@dataclass
class RepoData:
    name:        str
    url:         str
    language:    str
    stars:       int
    last_commit: str
    description: str
    is_fork:     bool
    file_tree:   list[str]
    key_files:   dict[str, str]   # path → truncated content

@dataclass
class RepoScore:
    name:      str
    language:  str
    stars:     int
    is_fork:   bool
    score:     float            # 0–100
    summary:   str              # one-line judgement
    qa:        dict[str, str] = field(default_factory=dict)  # Q1–Q4 answers

@dataclass
class CandidateResult:
    final_score:    float        # 0–100  (overall candidate score)
    reasoning:      str          # ≤3 lines plain English
    github_score:   float        # 0–100  (aggregated GitHub score)
    resume_score:   float        # 0–100
    ai_project_score: float      # 0–100
    research_score: float        # 0–100
    gpa_score:      float        # 0–100
    college_score:  float        # 0–100
    repo_scores:    list[RepoScore]