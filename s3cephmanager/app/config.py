import logging
import os
from pathlib import Path

# ── Logging setup ─────────────────────────────────────────────────────────────
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("cephs3mgr")

def _default_data_dir() -> Path:
    """Use /data if writable (container), else fall back to ~/.cephs3mgr (dev)."""
    _env = os.getenv("DATA_DIR")
    if _env:
        return Path(_env)
    try:
        p = Path("/data")
        p.mkdir(parents=True, exist_ok=True)
        # verify we can actually write there
        (p / ".write_test").touch()
        (p / ".write_test").unlink()
        return p
    except OSError:
        return Path.home() / ".cephs3mgr"

DATA_DIR = _default_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "cephs3mgr.db"

APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8080"))
STORAGE_SECRET = os.getenv("STORAGE_SECRET", "cephs3mgr-change-me-in-prod")
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_REGION = os.getenv("DEFAULT_REGION", "us-east-1")
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_MB", "5120")) * 1024 * 1024  # bytes
MULTIPART_THRESHOLD = 8 * 1024 * 1024   # 8 MB
MULTIPART_CHUNKSIZE = 8 * 1024 * 1024   # 8 MB
