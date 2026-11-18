"""Central configuration. Values come from the .env file (auto-created on first run)."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


def _ensure_env_file() -> None:
    """Create / complete .env so the project runs with zero manual setup."""
    existing = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    missing = []
    if "JWT_SECRET_KEY" not in existing:
        missing.append(f"JWT_SECRET_KEY={secrets.token_hex(32)}")
    if "TEACHER_SIGNUP_CODE" not in existing:
        missing.append("TEACHER_SIGNUP_CODE=TEACHER123")
    if missing:
        with open(ENV_FILE, "a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write("\n".join(missing) + "\n")


_ensure_env_file()
load_dotenv(ENV_FILE)

JWT_SECRET_KEY = os.environ["JWT_SECRET_KEY"]
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "480"))

# Teachers must type this code on the sign-up page. Change it in .env!
TEACHER_SIGNUP_CODE = os.environ["TEACHER_SIGNUP_CODE"]

_default_db = f"sqlite:///{(BASE_DIR / 'attendance.db').as_posix()}"
DATABASE_URL = os.getenv("DATABASE_URL") or _default_db
if DATABASE_URL.startswith("postgres://"):  # some cloud hosts use the old scheme
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# "opencv" = real engine (YuNet + SFace). "dev" = crude Haar engine, for testing only.
FACE_ENGINE = (os.getenv("FACE_ENGINE") or "opencv").lower()
# Cosine similarity needed to accept a face match (SFace recommends 0.363).
COSINE_THRESHOLD = float(os.getenv("COSINE_THRESHOLD", "0.40"))
MAX_FACES_PER_STUDENT = 10
