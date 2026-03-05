"""CephS3Manager-Web – entry point."""
import logging
import os
from pathlib import Path
from nicegui import app as ng_app, ui

# Ensure DATA_DIR exists before any imports that reference it
# (actual resolution happens in app.config; this just guarantees /data or fallback exists)
_data_env = os.getenv("DATA_DIR")
if _data_env:
    Path(_data_env).mkdir(parents=True, exist_ok=True)

# Import pages – decorators register routes automatically
import app.pages.connections  # noqa: F401
import app.pages.buckets       # noqa: F401
import app.pages.objects       # noqa: F401
import app.pages.users         # noqa: F401
import app.pages.settings      # noqa: F401

from app.database import init_db
from app.config import APP_HOST, APP_PORT, STORAGE_SECRET

log = logging.getLogger("cephs3mgr.main")


@ng_app.on_startup
async def startup():
    log.info("Starting CephS3Manager-Web on %s:%s", APP_HOST, APP_PORT)
    await init_db()
    log.info("Database initialised")


# ── Global CSS ────────────────────────────────────────────────────────────────
ui.add_head_html("""<style>
  /* ── Scrollbars ──────────────────────────────────────────────── */
  ::-webkit-scrollbar             { width:6px; height:6px; }
  ::-webkit-scrollbar-track       { background:#0d1117; }
  ::-webkit-scrollbar-thumb       { background:#30363d; border-radius:3px; }
  ::-webkit-scrollbar-thumb:hover { background:#484f58; }

  /* ── Quasar card reset ───────────────────────────────────────── */
  .q-card { box-shadow: none !important; }

  /* ── Input autofill (dark) ───────────────────────────────────── */
  input:-webkit-autofill,
  input:-webkit-autofill:hover,
  input:-webkit-autofill:focus {
    -webkit-text-fill-color: #e6edf3;
    -webkit-box-shadow: 0 0 0px 1000px #0d1117 inset;
    transition: background-color 5000s ease-in-out 0s;
  }

  /* ── Table row hover ─────────────────────────────────────────── */
  .q-table tbody tr:hover { background: #21262d44 !important; }

  /* ── Dialog backdrop ─────────────────────────────────────────── */
  .q-dialog__backdrop { background: rgba(0,0,0,0.75) !important; }

  /* ── Upload drop zone ────────────────────────────────────────── */
  .q-uploader { border-radius: 8px !important; }

  /* ── Notifications ───────────────────────────────────────────── */
  .q-notification { border-radius: 8px !important; font-size:0.85rem; }

  /* ── Tooltips ────────────────────────────────────────────────── */
  .q-tooltip { font-size: 0.75rem !important; }

  /* ── Progress bars ───────────────────────────────────────────── */
  .q-linear-progress { border-radius: 4px; }

  /* ── Checkbox label ──────────────────────────────────────────── */
  .q-checkbox__label { font-size: 0.85rem; }

  /* ── Button transition ───────────────────────────────────────── */
  .q-btn { transition: background 0.15s, border-color 0.15s, color 0.15s; }

  /* ── Remove NiceGUI content padding ─────────────────────────── */
  .nicegui-content { padding: 0 !important; }
</style>
""", shared=True)

# ── Run ───────────────────────────────────────────────────────────────────────
ui.run(
    title="CephS3Manager",
    dark=True,
    host=APP_HOST,
    port=APP_PORT,
    storage_secret=STORAGE_SECRET,
    favicon="🪣",
    tailwind=True,
    reload=os.getenv("DEV_RELOAD", "false").lower() == "true",
    show=False,
)
