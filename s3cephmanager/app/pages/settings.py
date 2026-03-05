"""
Settings page
=============
Persists per-user preferences in app.storage.user["settings"].

Configurable options
--------------------
  • Default region          – used when creating new buckets / connections
  • Objects page size       – max keys per list_objects call  (50–5000)
  • Presigned URL expiry    – default seconds  (60 – 604800)
  • Upload chunk size (MB)  – multipart chunk size  (5 – 512)
  • Upload threshold (MB)   – file size above which multipart kicks in
  • Dark mode               – mirrors the global toggle (also in header)
"""
from __future__ import annotations

from nicegui import ui, app

from app.components.sidebar import create_layout

_DEFAULTS: dict = {
    "default_region":      "us-east-1",
    "page_size":           200,
    "presign_expiry":      3600,
    "upload_chunksize_mb": 8,
    "upload_threshold_mb": 8,
}


def _get() -> dict:
    s = app.storage.user.get("settings")
    if not isinstance(s, dict):
        app.storage.user["settings"] = dict(_DEFAULTS)
        return dict(_DEFAULTS)
    for k, v in _DEFAULTS.items():
        s.setdefault(k, v)
    return s


def _save(s: dict) -> None:
    app.storage.user["settings"] = s


# ─────────────────────────────────────────────────────────────────────────────

@ui.page("/settings")
async def settings_page() -> None:
    create_layout(current_path="/settings")
    dark = app.storage.user.get("dark_mode", True)
    _body_bg(dark)
    C = _pal(dark)

    cfg = _get()

    with ui.column().style(
        "width:100%; max-width:700px; margin:0 auto; padding:28px 24px; gap:24px;"
    ):
        # ── Header ──────────────────────────────────────────────────────────
        with ui.column().style("gap:2px;"):
            ui.label("Settings").style(
                f"color:{C['txt']}; font-size:1.5rem; font-weight:700;"
            )
            ui.label("Application preferences – saved per browser session.").style(
                f"color:{C['mut']}; font-size:0.82rem;"
            )

        # ── S3 Defaults ─────────────────────────────────────────────────────
        _section("S3 Defaults", C)
        with _card(C):
            _label("Default Region", C)
            r_region = ui.input(
                placeholder="us-east-1",
                value=cfg["default_region"],
            ).props("dense outlined dark" if dark else "dense outlined").style(
                _inp(dark) + "max-width:300px;"
            )
            ui.label(
                "Used as pre-fill when creating buckets and connections."
            ).style(f"color:{C['mut']}; font-size:0.75rem; margin-top:2px;")

        # ── Object Explorer ──────────────────────────────────────────────────
        _section("Object Explorer", C)
        with _card(C):
            _label("Page Size (objects per load)", C)
            r_page = ui.number(
                value=cfg["page_size"], min=50, max=5000, step=50,
            ).props("dense outlined dark" if dark else "dense outlined").style(
                _inp(dark) + "max-width:160px;"
            )
            ui.label(
                "Number of objects fetched per page (50–5000). "
                "Applies on next folder open."
            ).style(f"color:{C['mut']}; font-size:0.75rem; margin-top:2px;")

            ui.separator().style(f"border-color:{C['bdr']}; margin:12px 0;")

            _label("Presigned URL Default Expiry (seconds)", C)
            r_expiry = ui.number(
                value=cfg["presign_expiry"], min=60, max=604800, step=60,
            ).props("dense outlined dark" if dark else "dense outlined").style(
                _inp(dark) + "max-width:160px;"
            )
            ui.label(
                "Default value shown in the presigned URL dialog (60 – 604 800 s)."
            ).style(f"color:{C['mut']}; font-size:0.75rem; margin-top:2px;")

        # ── Upload ──────────────────────────────────────────────────────────
        _section("Upload", C)
        with _card(C):
            _label("Multipart Threshold (MB)", C)
            r_thresh = ui.number(
                value=cfg["upload_threshold_mb"], min=5, max=512, step=1,
            ).props("dense outlined dark" if dark else "dense outlined").style(
                _inp(dark) + "max-width:160px;"
            )
            ui.label(
                "Files larger than this are uploaded in multiple parts."
            ).style(f"color:{C['mut']}; font-size:0.75rem; margin-top:2px;")

            ui.separator().style(f"border-color:{C['bdr']}; margin:12px 0;")

            _label("Multipart Chunk Size (MB)", C)
            r_chunk = ui.number(
                value=cfg["upload_chunksize_mb"], min=5, max=512, step=1,
            ).props("dense outlined dark" if dark else "dense outlined").style(
                _inp(dark) + "max-width:160px;"
            )
            ui.label(
                "Size of each chunk when using multipart upload (5 – 512 MB)."
            ).style(f"color:{C['mut']}; font-size:0.75rem; margin-top:2px;")

        # ── Appearance ──────────────────────────────────────────────────────
        _section("Appearance", C)
        with _card(C):
            _label("Theme", C)
            with ui.row().style("gap:10px; align-items:center; margin-top:4px;"):
                ui.button(
                    "Dark Mode" if dark else "Light Mode",
                    icon="dark_mode" if dark else "light_mode",
                    on_click=_toggle_dark,
                ).props("no-caps").style(
                    f"background:{C['sbg']}; color:{C['txt']}; "
                    f"border:1px solid {C['bdr']}; border-radius:8px; "
                    "font-size:0.82rem;"
                )
                ui.label("Currently: " + ("Dark" if dark else "Light")).style(
                    f"color:{C['mut']}; font-size:0.8rem;"
                )

        # ── Save button ──────────────────────────────────────────────────────
        err_lbl = ui.label("").style("color:#da3633; font-size:0.82rem;")

        def _on_save() -> None:
            new: dict = {
                "default_region":      (r_region.value or "us-east-1").strip(),
                "page_size":           int(r_page.value or 200),
                "presign_expiry":      int(r_expiry.value or 3600),
                "upload_threshold_mb": int(r_thresh.value or 8),
                "upload_chunksize_mb": int(r_chunk.value or 8),
            }
            # Validate
            if not new["default_region"]:
                err_lbl.set_text("Default region cannot be empty.")
                return
            if not (50 <= new["page_size"] <= 5000):
                err_lbl.set_text("Page size must be between 50 and 5000.")
                return
            if not (60 <= new["presign_expiry"] <= 604800):
                err_lbl.set_text("Presigned URL expiry must be between 60 and 604800 seconds.")
                return
            if not (5 <= new["upload_threshold_mb"] <= 512):
                err_lbl.set_text("Multipart threshold must be between 5 and 512 MB.")
                return
            if not (5 <= new["upload_chunksize_mb"] <= 512):
                err_lbl.set_text("Chunk size must be between 5 and 512 MB.")
                return
            _save(new)
            err_lbl.set_text("")
            ui.notify("Settings saved.", type="positive")

        with ui.row().style("justify-content:flex-end; width:100%;"):
            ui.button("Save Settings", on_click=_on_save, icon="save").props(
                "no-caps"
            ).style(
                "background:#1f6feb; color:#fff; border-radius:8px; "
                "font-weight:600; padding:8px 20px;"
            )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _toggle_dark() -> None:
    current = app.storage.user.get("dark_mode", True)
    app.storage.user["dark_mode"] = not current
    ui.navigate.reload()


def _section(title: str, C: dict) -> None:
    ui.label(title).style(
        f"color:{C['mut']}; font-size:0.7rem; font-weight:700; "
        "text-transform:uppercase; letter-spacing:0.1em; margin-top:4px;"
    )


def _label(text: str, C: dict) -> None:
    ui.label(text).style(
        f"color:{C['txt']}; font-size:0.88rem; font-weight:600; margin-bottom:6px;"
    )


def _card(C: dict):
    return ui.card().style(
        f"background:{C['sbg']}; border:1px solid {C['bdr']}; "
        "border-radius:10px; padding:18px 20px; width:100%; gap:0;"
    )


def _pal(dark: bool) -> dict:
    return {
        "sbg": "#161b22" if dark else "#ffffff",
        "bdr": "#21262d" if dark else "#d0d7de",
        "txt": "#e6edf3" if dark else "#1f2328",
        "mut": "#8b949e" if dark else "#57606a",
    }


def _inp(dark: bool) -> str:
    bg  = "#0d1117" if dark else "#f6f8fa"
    bdr = "#21262d" if dark else "#d0d7de"
    txt = "#e6edf3" if dark else "#1f2328"
    return (
        f"background:{bg}; border:1px solid {bdr}; border-radius:8px; "
        f"color:{txt}; width:100%;"
    )


def _body_bg(dark: bool) -> None:
    ui.query("body").style(
        f"background:{'#0d1117' if dark else '#f0f4f8'};"
    )
