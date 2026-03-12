import os
import dotenv
dotenv.load_dotenv()

# Paste your GitHub Personal Access Token here, or set the GITHUB_TOKEN env variable.
# Generate one at: https://github.com/settings/tokens  (scope: public_repo is enough)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

MAX_REPOS         = 3
REPO_AGE_DAYS     = 365
MAX_FILES_PER_REPO = 12
MAX_FILE_CHARS    = 3000   # truncation limit per file

# Always pull these if they exist in the repo
PRIORITY_FILENAMES = {
    "README.md",
    "main.py", "app.py", "train.py", "model.py", "run.py",
    "requirements.txt", "setup.py", "pyproject.toml",
    "package.json", "index.js", "index.ts", "app.ts",
    "Dockerfile", "docker-compose.yml",
}

PRIORITY_EXTENSIONS = {".py", ".js", ".ts", ".go", ".rs", ".java", ".cpp", ".ipynb"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv", "venv", ".next"}

# Final score weights
WEIGHTS = {
    "github":   0.25,
    "resume":   0.25,
    "ai_proj":  0.20,
    "research": 0.20,
    "gpa":      0.05,
    "college":  0.05,
}