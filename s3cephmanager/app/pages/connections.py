"""
Connection Manager page.

Features:
  - List all saved connections as cards with last-used badge
  - Add  new connection (full form: name, endpoint, keys, region, admin, ssl)
  - Edit  existing connection (same dialog, pre-filled)
  - Delete with confirmation
  - Test  connectivity (spinner while testing)
  - Connect → stores in session, navigates to /buckets
"""
from __future__ import annotations
import asyncio
from nicegui import ui, app
from app.components.sidebar import create_layout
from app import models


# ─────────────────────────────────────────────────────────────────────────────
@ui.page("/")
async def connections_page() -> None:
    create_layout(current_path="/")
    dark: bool = app.storage.user.get("dark_mode", True)

    bg_page = "#0d1117" if dark else "#f6f8fa"
    ui.query("body").style(f"background:{bg_page};")

    conns = await models.list_connections()
    conns_ref = {"conns": conns}

    # ── Shared Add/Edit dialog (built FIRST so `dialog` & `form` are in scope) ─
    form: dict = {}

    dlg_bg  = "#161b22" if dark else "#ffffff"
    dlg_bdr = "#21262d" if dark else "#d0d7de"
    txt_col = "#e6edf3"  if dark else "#1f2328"
    inp_sty = (
        f"background:{'#0d1117' if dark else '#f6f8fa'}; "
        f"border:1px solid {dlg_bdr}; border-radius:8px; "
        f"color:{txt_col}; padding:8px 12px; font-size:0.85rem; width:100%;"
    )

    with ui.dialog() as dialog, ui.card().style(
        f"background:{dlg_bg}; border:1px solid {dlg_bdr}; "
        "border-radius:12px; padding:28px; width:520px; max-width:96vw; gap:0;"
    ):
        ui.label("New Connection").style(
            f"color:{txt_col}; font-size:1.1rem; font-weight:700; margin-bottom:16px;"
        )

        # Two-column grid for inputs
        with ui.grid(columns=2).style("gap:12px; width:100%;"):
            form["name"]  = _labeled_input("Connection Name", "my-ceph-cluster",
                                           inp_sty, dark, span=1)
            form["ep"]    = _labeled_input("S3 Endpoint URL", "https://s3.example.com",
                                           inp_sty, dark, span=1)
            form["ak"]    = _labeled_input("Access Key", "AKID…",
                                           inp_sty, dark, span=1)
            form["sk"]    = _labeled_input("Secret Key", "••••••••",
                                           inp_sty, dark, span=1, password=True)
            form["region"]= _labeled_input("Region", "us-east-1",
                                           inp_sty, dark, span=1)
            form["admin_ep"] = _labeled_input(
                "Admin Endpoint (optional)", "https://s3.example.com",
                inp_sty, dark, span=1
            )

        # Checkboxes row
        with ui.row().style("gap:20px; margin-top:12px; align-items:center;"):
            form["admin_mode"] = ui.checkbox("Admin Mode (RGW user management)").style(
                f"color:{txt_col}; font-size:0.85rem;"
            )
            form["verify_ssl"] = ui.checkbox("Verify SSL", value=True).style(
                f"color:{txt_col}; font-size:0.85rem;"
            )

        # Status / error message
        form["status"] = ui.label("").style(
            "font-size:0.82rem; min-height:20px; margin-top:4px;"
        )
        form["spinner"] = ui.spinner(size="sm").style("display:none;")

        # Action buttons
        with ui.row().style(
            "justify-content:flex-end; gap:8px; margin-top:16px; align-items:center;"
        ):
            form["edit_id"] = None   # None = create mode, int = edit mode

            ui.button("Cancel", on_click=dialog.close).props("flat no-caps").style(
                f"color:{'#8b949e' if dark else '#57606a'};"
            )
            ui.button(
                "Test Connection",
                on_click=lambda: _test_conn(form, dark),
            ).props("no-caps").style(
                f"background:{'#21262d' if dark else '#f6f8fa'}; "
                f"color:{txt_col}; border-radius:8px;"
            )
            ui.button(
                "Save",
                on_click=lambda: _save(dialog, cards, form, dark, conns_ref),
            ).props("no-caps").style(
                "background:#1f6feb; color:#fff; border-radius:8px; font-weight:600;"
            )

    # ── Page scaffold (dialog is now defined above) ────────────────────────────
    with ui.column().style(
        "width:100%; max-width:900px; margin:0 auto; padding:28px 24px; gap:20px;"
    ):
        # Header row
        with ui.row().style("align-items:center; justify-content:space-between; width:100%;"):
            with ui.column().style("gap:2px;"):
                ui.label("Connections").style(
                    f"color:{'#e6edf3' if dark else '#1f2328'}; "
                    "font-size:1.5rem; font-weight:700;"
                )
                ui.label("Manage your S3 / Ceph endpoints").style(
                    f"color:{'#8b949e' if dark else '#57606a'}; font-size:0.85rem;"
                )
            ui.button(
                "＋  New Connection",
                on_click=lambda: _open_add_dialog(dialog, form),
            ).style(
                "background:#1f6feb; color:#fff; border-radius:8px; "
                "font-weight:600; padding:8px 18px;"
            ).props("no-caps")

        # Cards container
        cards = ui.column().style("width:100%; gap:12px;")
        _render_cards(cards, conns, dark, dialog, form)


# ─────────────────────────────────────────────────────────────────────────────
# Card rendering
# ─────────────────────────────────────────────────────────────────────────────

def _render_cards(
    container: ui.column,
    conns: list[dict],
    dark: bool,
    dialog,
    form: dict,
) -> None:
    container.clear()
    with container:
        if not conns:
            _empty_state(dark)
            return
        for c in conns:
            _conn_card(c, dark, dialog, form, container)


def _empty_state(dark: bool) -> None:
    txt = "#e6edf3" if dark else "#1f2328"
    mut = "#8b949e" if dark else "#57606a"
    with ui.column().style(
        "align-items:center; padding:60px 0; gap:12px; width:100%;"
    ):
        ui.icon("cable").style("font-size:3.5rem; color:#21262d;")
        ui.label("No connections yet").style(
            f"color:{txt}; font-size:1.1rem; font-weight:600;"
        )
        ui.label(
            "Click '+ New Connection' to add your first S3 / Ceph endpoint."
        ).style(f"color:{mut}; font-size:0.85rem;")


def _conn_card(
    c: dict, dark: bool,
    dialog, form: dict,
    container: ui.column,
) -> None:
    bg  = "#161b22" if dark else "#ffffff"
    bdr = "#21262d" if dark else "#d0d7de"
    txt = "#e6edf3" if dark else "#1f2328"
    mut = "#8b949e" if dark else "#57606a"
    last_used = c.get("is_last_used", False)
    border_col = "#1f6feb" if last_used else bdr

    with ui.card().style(
        f"background:{bg}; border:1px solid {border_col}; "
        "border-radius:10px; padding:16px 20px; width:100%; "
        "transition:border-color 0.2s;"
    ):
        with ui.row().style("align-items:center; justify-content:space-between; width:100%;"):
            # Left: name + meta
            with ui.column().style("gap:4px; flex:1; min-width:0;"):
                with ui.row().style("align-items:center; gap:8px;"):
                    ui.label(c["name"]).style(
                        f"color:{txt}; font-size:0.95rem; font-weight:600;"
                    )
                    if last_used:
                        ui.element("span").style(
                            "background:#1f3a5f; color:#58a6ff; "
                            "border:1px solid #1f6feb44; border-radius:4px; "
                            "padding:1px 6px; font-size:0.62rem; font-weight:600;"
                        ).text = "LAST USED"
                    if c.get("admin_mode"):
                        ui.element("span").style(
                            "background:#1a3a1a; color:#2ea043; "
                            "border:1px solid #2ea04344; border-radius:4px; "
                            "padding:1px 6px; font-size:0.62rem; font-weight:600;"
                        ).text = "ADMIN"

                ui.label(c["endpoint"]).style(
                    f"color:{mut}; font-size:0.78rem; "
                    "overflow:hidden; text-overflow:ellipsis; white-space:nowrap; "
                    "max-width:400px;"
                )

                with ui.row().style("gap:6px; margin-top:4px;"):
                    _tag(c.get("region", "us-east-1"), mut, dark)
                    if not c.get("verify_ssl", True):
                        _tag("no-ssl", "#da3633", dark)

            # Right: action buttons
            with ui.row().style("gap:6px; flex-shrink:0; align-items:center;"):
                ui.button(
                    "Edit",
                    icon="edit",
                    on_click=lambda conn=c: _open_edit_dialog(conn, dialog, form),
                ).props("flat no-caps dense").style(f"color:{mut};")

                ui.button(
                    icon="delete",
                    on_click=lambda cid=c["id"]: _delete(cid, container, dark, dialog, form),
                ).props("flat round dense").style("color:#da3633;")

                ui.button(
                    "Connect →",
                    on_click=lambda conn=c: _connect(conn),
                ).props("no-caps").style(
                    "background:#1f6feb; color:#fff; border-radius:8px; "
                    "padding:6px 14px; font-weight:600; font-size:0.82rem;"
                )


def _tag(text: str, color: str, dark: bool) -> None:
    bg = "#21262d" if dark else "#f6f8fa"
    ui.element("span").style(
        f"background:{bg}; color:{color}; border-radius:4px; "
        f"padding:1px 7px; font-size:0.67rem; font-weight:500;"
    ).text = text


# ─────────────────────────────────────────────────────────────────────────────
# Dialog helpers
# ─────────────────────────────────────────────────────────────────────────────

def _labeled_input(
    label: str, placeholder: str,
    inp_style: str, dark: bool,
    span: int = 1,
    password: bool = False,
) -> ui.input:
    lbl_col = "#8b949e" if dark else "#57606a"
    with ui.column().style(f"gap:4px; grid-column: span {span};"):
        ui.label(label).style(
            f"color:{lbl_col}; font-size:0.75rem; font-weight:600; "
            "text-transform:uppercase; letter-spacing:0.06em;"
        )
        inp = ui.input(placeholder=placeholder, password=password).props(
            "dense outlined dark" if dark else "dense outlined"
        ).style(inp_style)
    return inp


def _open_add_dialog(dialog, form: dict) -> None:
    """Clear form and open in Create mode."""
    form.get("name") and form["name"].set_value("")
    for key in ("ep", "ak", "sk", "admin_ep"):
        form.get(key) and form[key].set_value("")
    form.get("region")     and form["region"].set_value("us-east-1")
    form.get("admin_mode") and form["admin_mode"].set_value(False)
    form.get("verify_ssl") and form["verify_ssl"].set_value(True)
    form.get("status")     and form["status"].set_text("")
    form["edit_id"] = None
    dialog.open()


def _open_edit_dialog(conn: dict, dialog, form: dict) -> None:
    """Pre-fill form with existing values and open in Edit mode."""
    form["name"].set_value(conn["name"])
    form["ep"].set_value(conn["endpoint"])
    form["ak"].set_value(conn["access_key"])
    form["sk"].set_value(conn["secret_key"])
    form["region"].set_value(conn.get("region", "us-east-1"))
    form["admin_ep"].set_value(conn.get("admin_endpoint") or "")
    form["admin_mode"].set_value(bool(conn.get("admin_mode", False)))
    form["verify_ssl"].set_value(bool(conn.get("verify_ssl", True)))
    form.get("status") and form["status"].set_text("")
    form["edit_id"] = conn["id"]
    dialog.open()


# ─────────────────────────────────────────────────────────────────────────────
# Async actions
# ─────────────────────────────────────────────────────────────────────────────

async def _test_conn(form: dict, dark: bool) -> None:
    """Test S3 connectivity and update status label."""
    from app.s3_client import S3Manager
    ep    = form["ep"].value
    ak    = form["ak"].value
    sk    = form["sk"].value
    reg   = form["region"].value or "us-east-1"
    ssl   = form["verify_ssl"].value

    if not (ep and ak and sk):
        _set_status(form, "⚠ Endpoint and both keys are required.", "warning")
        return

    _set_status(form, "⏳ Testing…", "info")
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: S3Manager(ep, ak, sk, reg, ssl).list_buckets()
        )
        _set_status(form, "✓ Connection successful!", "ok")
    except Exception as exc:
        _set_status(form, f"✗ {exc}", "error")


async def _save(dialog, cards: ui.column, form: dict, dark: bool,
                conns_ref: dict) -> None:
    name    = form["name"].value.strip()
    ep      = form["ep"].value.strip()
    ak      = form["ak"].value.strip()
    sk      = form["sk"].value.strip()
    region  = form["region"].value.strip() or "us-east-1"
    adm_ep  = form["admin_ep"].value.strip() or None
    adm_mode = form["admin_mode"].value
    ssl     = form["verify_ssl"].value

    if not all([name, ep, ak, sk]):
        _set_status(form, "⚠ Name, endpoint and both keys are required.", "warning")
        return

    try:
        edit_id = form.get("edit_id")
        if edit_id is None:
            await models.save_connection({
                "name": name, "endpoint": ep, "access_key": ak, "secret_key": sk,
                "region": region, "admin_endpoint": adm_ep,
                "admin_mode": adm_mode, "verify_ssl": ssl,
            })
            ui.notify(f"'{name}' saved.", type="positive")
        else:
            await models.update_connection(edit_id, {
                "name": name, "endpoint": ep, "access_key": ak, "secret_key": sk,
                "region": region, "admin_endpoint": adm_ep,
                "admin_mode": adm_mode, "verify_ssl": ssl,
            })
            # Update active session if editing the current connection
            active = app.storage.user.get("active_connection")
            if active and active.get("id") == edit_id:
                updated = await models.get_connection(edit_id)
                app.storage.user["active_connection"] = updated
            ui.notify(f"'{name}' updated.", type="positive")

        dialog.close()
        conns = await models.list_connections()
        conns_ref["conns"] = conns
        _render_cards(cards, conns, dark, dialog, form)

    except Exception as exc:
        _set_status(form, f"✗ {exc}", "error")


async def _connect(conn: dict) -> None:
    from app.s3_client import get_s3_from_conn
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: get_s3_from_conn(conn).list_buckets()
        )
        app.storage.user["active_connection"] = conn
        await models.set_last_used(conn["id"])
        ui.navigate.to("/buckets")
    except Exception as exc:
        ui.notify(f"Connection failed: {exc}", type="negative", timeout=6000)


async def _delete(conn_id: int, cards: ui.column, dark: bool,
                  dialog, form: dict) -> None:
    await models.delete_connection(conn_id)
    conns = await models.list_connections()
    _render_cards(cards, conns, dark, dialog, form)
    ui.notify("Connection deleted.", type="warning")


# ─────────────────────────────────────────────────────────────────────────────
# Misc helpers
# ─────────────────────────────────────────────────────────────────────────────

def _set_status(form: dict, text: str, kind: str) -> None:
    colors = {
        "ok":      "#2ea043",
        "error":   "#da3633",
        "warning": "#d29922",
        "info":    "#8b949e",
    }
    color = colors.get(kind, "#8b949e")
    lbl = form.get("status")
    if lbl:
        lbl.set_text(text)
        lbl.style(f"color:{color};")
