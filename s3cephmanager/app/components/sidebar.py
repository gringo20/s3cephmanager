"""
CTk-inspired sidebar + top header with:
  - Dark/light mode toggle (persisted per user, reload-free via JS)
  - Live connection status pill
  - Active-route highlighting
  - Disconnect button
"""
from nicegui import ui, app

# ── Nav items (icon, label, path) ────────────────────────────────────────────
NAV = [
    ("cable",           "Connections", "/"),
    ("dns",             "Buckets",     "/buckets"),
    ("folder_open",     "Objects",     "/objects"),
    ("manage_accounts", "Users",       "/users"),
    ("settings",        "Settings",    "/settings"),
]

# ── Palette ───────────────────────────────────────────────────────────────────
_DARK = {
    "sidebar": "#0d1117",
    "header":  "#161b22",
    "border":  "#21262d",
    "text":    "#e6edf3",
    "muted":   "#8b949e",
    "active":  "#1f6feb",
    "act_bg":  "#1f6feb22",
    "hover":   "#21262d",
}
_LIGHT = {
    "sidebar": "#f6f8fa",
    "header":  "#ffffff",
    "border":  "#d0d7de",
    "text":    "#1f2328",
    "muted":   "#57606a",
    "active":  "#0969da",
    "act_bg":  "#0969da18",
    "hover":   "#eef1f4",
}


def _t(key: str, dark: bool) -> str:
    return (_DARK if dark else _LIGHT)[key]


# ── Public API ────────────────────────────────────────────────────────────────

def create_layout(current_path: str = "/") -> None:
    """Render header + left drawer. Call once at the top of every @ui.page."""
    dark: bool = app.storage.user.get("dark_mode", True)
    dm = ui.dark_mode()
    dm.enable() if dark else dm.disable()

    conn = app.storage.user.get("active_connection")
    _render_header(dark, dm, conn)
    _render_drawer(dark, conn, current_path)


def require_connection() -> dict | None:
    """Guard: return active connection dict or redirect to / and return None."""
    conn = app.storage.user.get("active_connection")
    if not conn:
        ui.navigate.to("/")
        return None
    return conn


# ── Internal renderers ────────────────────────────────────────────────────────

def _render_header(dark: bool, dm, conn: dict | None) -> None:
    hdr = _t("header", dark)
    bdr = _t("border", dark)
    txt = _t("text",   dark)
    mut = _t("muted",  dark)

    with ui.header(elevated=False).style(
        f"background:{hdr}; border-bottom:1px solid {bdr}; "
        "height:56px; padding:0 20px; display:flex; align-items:center; "
        "justify-content:space-between; z-index:200; gap:0;"
    ):
        # Left: logo + wordmark
        with ui.row().style("align-items:center; gap:8px; flex:0 0 auto;"):
            ui.icon("storage").style("color:#58a6ff; font-size:1.4rem;")
            ui.label("CephS3Manager").style(
                f"color:{txt}; font-size:0.95rem; font-weight:700; "
                "letter-spacing:-0.02em;"
            )
            ui.element("span").style(
                "color:#58a6ff; font-size:0.62rem; font-weight:600; "
                "background:#1f3a5f; padding:2px 7px; border-radius:20px; "
                "letter-spacing:0.04em;"
            ).text = "Web"

        # Center: connection status pill (flex:1 so it can centre itself)
        with ui.row().style(
            "flex:1; justify-content:center; align-items:center;"
        ):
            _conn_pill(dark, conn)

        # Right: actions
        with ui.row().style("align-items:center; gap:2px; flex:0 0 auto;"):
            # Dark mode toggle
            dm_icon = "dark_mode" if dark else "light_mode"
            dm_btn  = ui.button(icon=dm_icon).props("flat round").style(
                f"color:{mut};"
            )
            ui.tooltip("Toggle dark / light")
            dm_btn.on("click", lambda: _toggle_dark())

            if conn:
                disc_btn = ui.button(icon="logout").props("flat round").style(
                    f"color:{mut};"
                )
                ui.tooltip("Disconnect")
                disc_btn.on("click", _disconnect)


def _conn_pill(dark: bool, conn: dict | None) -> None:
    bdr = _t("border", dark)
    bg  = _t("hover",  dark)
    txt = _t("text",   dark)
    mut = _t("muted",  dark)

    dot_col  = "#2ea043" if conn else "#da3633"
    name     = conn["name"]     if conn else "Not connected"
    sublabel = conn.get("region", "us-east-1") if conn else "Select a connection →"

    with ui.element("div").style(
        f"display:flex; align-items:center; gap:10px; "
        f"background:{bg}; border:1px solid {bdr}; "
        "border-radius:20px; padding:5px 14px;"
    ):
        # Pulsing dot
        ui.element("div").style(
            f"width:8px; height:8px; border-radius:50%; background:{dot_col}; "
            f"box-shadow:0 0 0 3px {dot_col}33; flex-shrink:0;"
        )
        with ui.column().style("gap:0; line-height:1.2;"):
            ui.label(name).style(
                f"color:{txt}; font-size:0.78rem; font-weight:600;"
            )
            ui.label(sublabel).style(f"color:{mut}; font-size:0.67rem;")


def _render_drawer(dark: bool, conn: dict | None, current_path: str) -> None:
    sb  = _t("sidebar", dark)
    bdr = _t("border",  dark)
    mut = _t("muted",   dark)
    txt = _t("text",    dark)

    with ui.left_drawer(top_corner=True, bottom_corner=True).style(
        f"background:{sb}; border-right:1px solid {bdr}; width:220px;"
    ):
        # Logo block
        with ui.column().style(
            "align-items:center; padding:22px 0 14px; gap:3px;"
        ):
            ui.icon("storage").style("color:#58a6ff; font-size:2rem;")
            ui.label("S3 Manager").style(
                f"color:{mut}; font-size:0.68rem; font-weight:500; "
                "letter-spacing:0.1em; text-transform:uppercase;"
            )

        ui.separator().style(f"border-color:{bdr}; margin:0 16px 4px;")

        # Nav items
        with ui.column().style("padding:4px 8px; gap:1px;"):
            ui.label("NAVIGATION").style(
                f"color:{mut}; font-size:0.6rem; font-weight:700; "
                "letter-spacing:0.12em; padding:8px 8px 4px;"
            )
            for icon, label, path in NAV:
                _nav_item(icon, label, path, path == current_path, dark)

        ui.separator().style(f"border-color:{bdr}; margin:8px 16px;")

        # Active connection block
        if conn:
            with ui.column().style("padding:4px 16px 12px; gap:3px;"):
                ui.label("ACTIVE CONNECTION").style(
                    f"color:{mut}; font-size:0.6rem; font-weight:700; "
                    "letter-spacing:0.12em; margin-bottom:2px;"
                )
                ui.label(conn["name"]).style(
                    f"color:{txt}; font-size:0.82rem; font-weight:600;"
                )
                ui.label(conn["endpoint"]).style(
                    f"color:{mut}; font-size:0.68rem; "
                    "overflow:hidden; text-overflow:ellipsis; "
                    "white-space:nowrap; max-width:190px;"
                )
                with ui.row().style("gap:4px; margin-top:4px; flex-wrap:wrap;"):
                    _mini_badge(conn.get("region", "us-east-1"), "#1f3a5f", "#58a6ff")
                    if conn.get("admin_mode"):
                        _mini_badge("Admin", "#1a3a1a", "#2ea043")
                    if not conn.get("verify_ssl", True):
                        _mini_badge("No SSL", "#3a1a1a", "#da3633")

        # Bottom: version
        with ui.row().style(f"padding:12px 16px; margin-top:auto;"):
            ui.label("v1.0.0").style(f"color:{bdr}; font-size:0.68rem;")


def _nav_item(icon: str, label: str, path: str, active: bool, dark: bool) -> None:
    if active:
        bg  = _t("act_bg", dark)
        fg  = _t("active", dark)
        bdr = f"1px solid {_t('active', dark)}44"
        w   = "600"
    else:
        bg  = "transparent"
        fg  = _t("muted", dark)
        bdr = "1px solid transparent"
        w   = "400"

    with ui.button(
        on_click=lambda p=path: ui.navigate.to(p)
    ).props("flat no-caps").style(
        f"width:100%; justify-content:flex-start; background:{bg}; "
        f"border:{bdr}; border-radius:8px; padding:9px 12px; "
        f"color:{fg}; font-weight:{w}; transition:all 0.15s; "
        f"margin-bottom:1px;"
    ):
        ui.icon(icon).style(
            f"font-size:1.05rem; color:{fg}; margin-right:10px; min-width:20px;"
        )
        ui.label(label).style(f"font-size:0.85rem; color:{fg};")


def _mini_badge(text: str, bg: str, color: str) -> None:
    ui.element("div").style(
        f"background:{bg}; color:{color}; border:1px solid {color}55; "
        "border-radius:4px; padding:1px 6px; font-size:0.62rem; "
        "font-weight:600; white-space:nowrap;"
    ).text = text


def _toggle_dark() -> None:
    current = app.storage.user.get("dark_mode", True)
    app.storage.user["dark_mode"] = not current
    ui.navigate.reload()


def _disconnect() -> None:
    app.storage.user.pop("active_connection", None)
    ui.navigate.to("/")
