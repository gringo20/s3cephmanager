"""
Buckets page.

Uses native NiceGUI ui.table (Quasar QTable) with slot-based action buttons.
Features:
  - Responsive table with sortable columns
  - Create bucket dialog (name + region)
  - Delete dialog (with force-empty option)
  - Click bucket name → navigate to Object Explorer
  - Bucket settings dialog: Policy / CORS / Versioning tabs
  - Stat chips: total buckets count
  - Dark / light theme-aware
"""
from __future__ import annotations
import asyncio
import json
from nicegui import ui, app
from app.components.sidebar import create_layout, require_connection
from app.s3_client import get_s3_from_conn


# ─────────────────────────────────────────────────────────────────────────────
@ui.page("/buckets")
async def buckets_page() -> None:
    create_layout(current_path="/buckets")
    dark = app.storage.user.get("dark_mode", True)
    _body_bg(dark)

    conn = require_connection()
    if not conn:
        return

    s3 = get_s3_from_conn(conn)

    # ── Page scaffold ─────────────────────────────────────────────────────────
    txt = "#e6edf3" if dark else "#1f2328"
    mut = "#8b949e" if dark else "#57606a"

    with ui.column().style(
        "width:100%; max-width:1200px; margin:0 auto; padding:28px 24px; gap:20px;"
    ):
        # Header
        with ui.row().style(
            "align-items:center; justify-content:space-between; width:100%;"
        ):
            with ui.column().style("gap:2px;"):
                ui.label("Buckets").style(
                    f"color:{txt}; font-size:1.5rem; font-weight:700;"
                )
                ui.label(f"Endpoint: {conn['endpoint']}").style(
                    f"color:{mut}; font-size:0.8rem;"
                )
            with ui.row().style("gap:8px; align-items:center;"):
                search = ui.input(placeholder="Filter…").props(
                    "dense outlined dark" if dark else "dense outlined"
                ).style(_inp(dark))
                ui.button(
                    icon="refresh",
                    on_click=lambda: _reload(table, stats_row, s3, dark),
                ).props("flat round").style(f"color:{mut};")
                ui.button(
                    "＋ Create Bucket",
                    on_click=lambda: _open_create(create_dlg, f_name, f_region,
                                                  err_create, conn),
                ).props("no-caps").style(
                    "background:#1f6feb; color:#fff; border-radius:8px; "
                    "font-weight:600; padding:8px 16px;"
                )

        # Stats row
        stats_row = ui.row().style("gap:12px;")

        # ── Table ─────────────────────────────────────────────────────────────
        tbl_bg  = "#161b22" if dark else "#ffffff"
        tbl_bdr = "#21262d" if dark else "#d0d7de"
        hdcol   = "#58a6ff" if dark else "#0969da"

        columns = [
            {"name": "name",    "label": "Bucket Name",  "field": "name",
             "align": "left",   "sortable": True},
            {"name": "created", "label": "Created",      "field": "created",
             "align": "left",   "sortable": True},
            {"name": "region",  "label": "Region",       "field": "region",
             "align": "left"},
            {"name": "actions", "label": "Actions",      "field": "name",
             "align": "right"},
        ]
        table = ui.table(
            columns=columns,
            rows=[],
            row_key="name",
            pagination={"rowsPerPage": 25, "sortBy": "name"},
        ).style(
            f"background:{tbl_bg}; border:1px solid {tbl_bdr}; "
            "border-radius:10px; width:100%;"
        ).props("flat dark" if dark else "flat")

        # Style header cells
        table.add_slot("header", r"""
            <q-tr :props="props">
              <q-th v-for="col in props.cols" :key="col.name" :props="props"
                    style="font-size:0.72rem; font-weight:700; letter-spacing:0.06em;
                           text-transform:uppercase; opacity:0.65;">
                {{ col.label }}
              </q-th>
            </q-tr>
        """)

        # Bucket name cell → clickable
        table.add_slot("body-cell-name", r"""
            <q-td :props="props">
              <span
                style="color:#58a6ff; font-weight:600; cursor:pointer;
                       font-size:0.9rem;"
                @click="() => $parent.$emit('browse', props.row)"
              >
                🪣 {{ props.value }}
              </span>
            </q-td>
        """)

        # Actions cell
        table.add_slot("body-cell-actions", r"""
            <q-td :props="props" style="text-align:right;">
              <q-btn flat dense round icon="folder_open" color="blue-4"
                     style="margin-right:4px;"
                     @click="() => $parent.$emit('browse', props.row)">
                <q-tooltip>Browse objects</q-tooltip>
              </q-btn>
              <q-btn flat dense round icon="settings" color="grey-5"
                     style="margin-right:4px;"
                     @click="() => $parent.$emit('bucket_settings', props.row)">
                <q-tooltip>Policy / CORS / Versioning</q-tooltip>
              </q-btn>
              <q-btn flat dense round icon="delete" color="red-4"
                     @click="() => $parent.$emit('delete', props.row)">
                <q-tooltip>Delete bucket</q-tooltip>
              </q-btn>
            </q-td>
        """)

        table.on("browse", lambda e: _browse(e.args))
        table.on("delete", lambda e: _open_delete(
            e.args, delete_dlg, del_name_lbl, del_err
        ))
        table.on("bucket_settings", lambda e: _open_bucket_settings(e.args, bucket_dlg, bkt_ctx, s3, dark))

        # Filter
        search.on("input", lambda e: table.run_method(
            "filterMethod", e.sender.value
        ))

    # ── Create dialog ─────────────────────────────────────────────────────────
    with ui.dialog() as create_dlg, _dialog_card(dark):
        _dlg_title("Create Bucket", dark)
        f_name   = _dlg_input("Bucket Name", "my-new-bucket", dark)
        f_region = _dlg_input("Region", conn.get("region", "us-east-1"), dark)
        err_create = _dlg_err()
        with ui.row().style("justify-content:flex-end; gap:8px; margin-top:16px;"):
            _cancel_btn(create_dlg, dark)
            _primary_btn(
                "Create",
                lambda: _create(s3, f_name.value, f_region.value,
                                create_dlg, table, stats_row, err_create, dark),
            )

    # ── Delete dialog ─────────────────────────────────────────────────────────
    _del_state: dict = {"name": ""}
    with ui.dialog() as delete_dlg, _dialog_card(dark):
        _dlg_title("Delete Bucket", dark)
        del_name_lbl = ui.label("").style(
            "color:#da3633; font-size:0.9rem; font-weight:600; margin-bottom:8px;"
        )
        del_force = ui.checkbox("Force empty before delete").style(
            f"color:{'#e6edf3' if dark else '#1f2328'};"
        )
        del_err = _dlg_err()
        with ui.row().style("justify-content:flex-end; gap:8px; margin-top:16px;"):
            _cancel_btn(delete_dlg, dark)
            ui.button("Delete", color="red").props("no-caps").style(
                "color:#fff; border-radius:8px; font-weight:600;"
            ).on("click", lambda: _delete(s3, _del_state["name"], del_force.value,
                                           delete_dlg, table, stats_row, del_err, dark))

    # ── Bucket Settings dialog (Policy / CORS / Versioning) ───────────────────
    bkt_ctx: dict = {}

    with ui.dialog() as bucket_dlg, _dialog_card(dark, "720px"):
        # Title row
        with ui.row().style(
            "align-items:center; justify-content:space-between; "
            "width:100%; margin-bottom:12px;"
        ):
            bkt_ctx["title_lbl"] = ui.label("Bucket Settings").style(
                f"color:{'#e6edf3' if dark else '#1f2328'}; "
                "font-size:1.05rem; font-weight:700;"
            )
            with ui.row().style("align-items:center; gap:6px;"):
                bkt_ctx["spinner"] = ui.spinner("dots", size="xs").style(
                    f"color:{'#8b949e' if dark else '#57606a'}; display:none;"
                )
                ui.button(icon="close", on_click=bucket_dlg.close).props(
                    "flat round"
                ).style(f"color:{'#8b949e' if dark else '#57606a'};")

        # Tabs
        with ui.tabs().props("dense").style(
            f"color:{'#58a6ff' if dark else '#0969da'}; "
            f"border-bottom:1px solid {'#21262d' if dark else '#d0d7de'}; "
            "margin-bottom:14px;"
        ) as btabs:
            btab_pol  = ui.tab("Policy",     icon="policy")
            btab_cors = ui.tab("CORS",        icon="public")
            btab_ver  = ui.tab("Versioning",  icon="history")

        with ui.tab_panels(btabs, value=btab_pol).style("width:100%;"):

            # ── Policy tab ────────────────────────────────────────────────
            with ui.tab_panel(btab_pol):
                ui.label("Bucket Policy (JSON)").style(
                    f"color:{'#8b949e' if dark else '#57606a'}; "
                    "font-size:0.7rem; font-weight:700; "
                    "text-transform:uppercase; letter-spacing:0.1em; "
                    "margin-bottom:6px;"
                )
                bkt_ctx["pol_area"] = ui.textarea(placeholder='{ "Version": "2012-10-17", ... }').props(
                    "dense outlined dark" if dark else "dense outlined"
                ).style(
                    f"background:{'#0d1117' if dark else '#f6f8fa'}; "
                    f"border:1px solid {'#21262d' if dark else '#d0d7de'}; "
                    "border-radius:8px; font-family:monospace; "
                    f"color:{'#e6edf3' if dark else '#1f2328'}; "
                    "width:100%; min-height:200px; font-size:0.78rem;"
                )
                bkt_ctx["pol_err"] = ui.label("").style(
                    "color:#da3633; font-size:0.8rem; min-height:18px;"
                )
                with ui.row().style("gap:8px; margin-top:10px;"):
                    ui.button("Save Policy", icon="save", on_click=lambda: _save_policy(s3, bkt_ctx, dark)).props("no-caps").style(
                        "background:#1f6feb; color:#fff; border-radius:8px; font-weight:600;"
                    )
                    ui.button("Delete Policy", icon="delete", on_click=lambda: _delete_policy(s3, bkt_ctx, dark)).props("no-caps flat").style(
                        f"color:#da3633;"
                    )

            # ── CORS tab ──────────────────────────────────────────────────
            with ui.tab_panel(btab_cors):
                ui.label("CORS Rules").style(
                    f"color:{'#8b949e' if dark else '#57606a'}; "
                    "font-size:0.7rem; font-weight:700; "
                    "text-transform:uppercase; letter-spacing:0.1em; "
                    "margin-bottom:6px;"
                )
                bkt_ctx["cors_col"] = ui.column().style(
                    "gap:8px; width:100%; min-height:60px;"
                )

                ui.separator().style(
                    f"border-color:{'#21262d' if dark else '#d0d7de'}; margin:12px 0;"
                )

                # Add rule form
                ui.label("Add Rule").style(
                    f"color:{'#e6edf3' if dark else '#1f2328'}; "
                    "font-size:0.82rem; font-weight:600; margin-bottom:6px;"
                )
                bkt_ctx["cors_origins"] = ui.input(
                    placeholder="Allowed Origins (comma-separated, e.g. *)"
                ).props("dense outlined dark" if dark else "dense outlined").style(
                    f"background:{'#0d1117' if dark else '#f6f8fa'}; "
                    f"border:1px solid {'#21262d' if dark else '#d0d7de'}; "
                    "border-radius:8px; "
                    f"color:{'#e6edf3' if dark else '#1f2328'}; "
                    "width:100%; margin-bottom:8px;"
                )
                bkt_ctx["cors_methods"] = ui.input(
                    placeholder="Allowed Methods (e.g. GET,PUT,POST)"
                ).props("dense outlined dark" if dark else "dense outlined").style(
                    f"background:{'#0d1117' if dark else '#f6f8fa'}; "
                    f"border:1px solid {'#21262d' if dark else '#d0d7de'}; "
                    "border-radius:8px; "
                    f"color:{'#e6edf3' if dark else '#1f2328'}; "
                    "width:100%; margin-bottom:8px;"
                )
                bkt_ctx["cors_headers"] = ui.input(
                    placeholder="Allowed Headers (optional, e.g. *)"
                ).props("dense outlined dark" if dark else "dense outlined").style(
                    f"background:{'#0d1117' if dark else '#f6f8fa'}; "
                    f"border:1px solid {'#21262d' if dark else '#d0d7de'}; "
                    "border-radius:8px; "
                    f"color:{'#e6edf3' if dark else '#1f2328'}; "
                    "width:100%; margin-bottom:8px;"
                )
                bkt_ctx["cors_err"] = ui.label("").style(
                    "color:#da3633; font-size:0.8rem; min-height:18px;"
                )
                with ui.row().style("gap:8px; margin-top:4px;"):
                    ui.button("Add Rule", icon="add", on_click=lambda: _add_cors_rule(s3, bkt_ctx, dark)).props("no-caps").style(
                        "background:#1f6feb; color:#fff; border-radius:8px; font-weight:600;"
                    )
                    ui.button("Delete All CORS", icon="delete", on_click=lambda: _delete_cors(s3, bkt_ctx, dark)).props("no-caps flat").style("color:#da3633;")

            # ── Versioning tab ────────────────────────────────────────────
            with ui.tab_panel(btab_ver):
                ui.label("Versioning Status").style(
                    f"color:{'#8b949e' if dark else '#57606a'}; "
                    "font-size:0.7rem; font-weight:700; "
                    "text-transform:uppercase; letter-spacing:0.1em; "
                    "margin-bottom:10px;"
                )
                bkt_ctx["ver_status_lbl"] = ui.label("Loading…").style(
                    f"color:{'#e6edf3' if dark else '#1f2328'}; "
                    "font-size:1.1rem; font-weight:700; margin-bottom:12px;"
                )
                ui.label(
                    "Once versioning is enabled on a bucket it can only be "
                    "suspended, not disabled entirely."
                ).style(
                    f"color:{'#8b949e' if dark else '#57606a'}; "
                    "font-size:0.78rem; margin-bottom:14px; line-height:1.5;"
                )
                bkt_ctx["ver_err"] = ui.label("").style(
                    "color:#da3633; font-size:0.8rem; min-height:18px;"
                )
                with ui.row().style("gap:8px;"):
                    ui.button("Enable Versioning", icon="check_circle",
                              on_click=lambda: _set_versioning(s3, bkt_ctx, "Enabled", dark)).props("no-caps").style(
                        "background:#2ea043; color:#fff; border-radius:8px; font-weight:600;"
                    )
                    ui.button("Suspend Versioning", icon="pause_circle",
                              on_click=lambda: _set_versioning(s3, bkt_ctx, "Suspended", dark)).props("no-caps flat").style(
                        "color:#e36209;"
                    )

        with ui.row().style("justify-content:flex-end; margin-top:14px;"):
            ui.button("Close", on_click=bucket_dlg.close).props("flat no-caps").style(
                f"color:{'#8b949e' if dark else '#57606a'};"
            )

    # Patch delete handler to capture bucket name
    def _open_delete(row: dict, dlg, name_lbl, err_lbl) -> None:
        _del_state["name"] = row.get("name", "")
        name_lbl.set_text(f"🗑  {_del_state['name']}")
        err_lbl.set_text("")
        del_force.set_value(False)
        dlg.open()

    # Initial load
    await _reload(table, stats_row, s3, dark)


# ─────────────────────────────────────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _reload(table, stats_row, s3, dark: bool) -> None:
    try:
        loop = asyncio.get_event_loop()
        buckets = await loop.run_in_executor(None, s3.list_buckets)
    except Exception as exc:
        ui.notify(f"Error loading buckets: {exc}", type="negative")
        return

    rows = []
    for b in buckets:
        rows.append({
            "name":    b["Name"],
            "created": (b["CreationDate"].strftime("%Y-%m-%d %H:%M")
                        if b.get("CreationDate") else "—"),
            "region":  "—",
        })
    table.rows.clear()
    table.rows.extend(rows)
    table.update()

    # Stats chips
    stats_row.clear()
    with stats_row:
        _stat_chip("Total Buckets", str(len(buckets)), "dns", dark)


def _browse(row: dict) -> None:
    name = row.get("name", "")
    if name:
        app.storage.user["active_bucket"] = name
        app.storage.user["active_prefix"] = ""
        ui.navigate.to("/objects")


async def _create(s3, name: str, region: str, dialog, table, stats_row,
                  err_lbl, dark: bool) -> None:
    if not name.strip():
        err_lbl.set_text("Bucket name is required.")
        return
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: s3.create_bucket(name.strip(), region or "us-east-1")
        )
        dialog.close()
        ui.notify(f"Bucket '{name}' created.", type="positive")
        await _reload(table, stats_row, s3, dark)
    except Exception as exc:
        err_lbl.set_text(str(exc))


async def _delete(s3, name: str, force: bool, dialog, table, stats_row,
                  err_lbl, dark: bool) -> None:
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: s3.delete_bucket(name, force=force)
        )
        dialog.close()
        ui.notify(f"Bucket '{name}' deleted.", type="warning")
        await _reload(table, stats_row, s3, dark)
    except Exception as exc:
        err_lbl.set_text(str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# UI building blocks
# ─────────────────────────────────────────────────────────────────────────────

def _stat_chip(label: str, value: str, icon: str, dark: bool) -> None:
    bg  = "#161b22" if dark else "#ffffff"
    bdr = "#21262d" if dark else "#d0d7de"
    txt = "#e6edf3" if dark else "#1f2328"
    mut = "#8b949e" if dark else "#57606a"
    with ui.card().style(
        f"background:{bg}; border:1px solid {bdr}; border-radius:8px; "
        "padding:10px 18px;"
    ):
        with ui.row().style("align-items:center; gap:10px;"):
            ui.icon(icon).style("color:#58a6ff; font-size:1.4rem;")
            with ui.column().style("gap:0;"):
                ui.label(value).style(
                    f"color:{txt}; font-size:1.4rem; font-weight:700; line-height:1;"
                )
                ui.label(label).style(f"color:{mut}; font-size:0.72rem;")


def _dialog_card(dark: bool, width: str = "440px"):
    bg  = "#161b22" if dark else "#ffffff"
    bdr = "#21262d" if dark else "#d0d7de"
    return ui.card().style(
        f"background:{bg}; border:1px solid {bdr}; "
        f"border-radius:12px; padding:24px; width:{width}; max-width:96vw;"
    )


def _dlg_title(text: str, dark: bool) -> None:
    txt = "#e6edf3" if dark else "#1f2328"
    ui.label(text).style(
        f"color:{txt}; font-size:1.05rem; font-weight:700; margin-bottom:16px;"
    )


def _dlg_input(label: str, placeholder: str, dark: bool) -> ui.input:
    mut = "#8b949e" if dark else "#57606a"
    with ui.column().style("gap:4px; width:100%; margin-bottom:10px;"):
        ui.label(label).style(
            f"color:{mut}; font-size:0.72rem; font-weight:600; "
            "text-transform:uppercase; letter-spacing:0.06em;"
        )
        return ui.input(placeholder=placeholder).props(
            "dense outlined dark" if dark else "dense outlined"
        ).style(_inp(dark))


def _dlg_err() -> ui.label:
    return ui.label("").style("color:#da3633; font-size:0.8rem; min-height:18px;")


def _cancel_btn(dialog, dark: bool) -> None:
    mut = "#8b949e" if dark else "#57606a"
    ui.button("Cancel", on_click=dialog.close).props("flat no-caps").style(f"color:{mut};")


def _primary_btn(text: str, handler) -> None:
    ui.button(text, on_click=handler).props("no-caps").style(
        "background:#1f6feb; color:#fff; border-radius:8px; font-weight:600;"
    )


def _inp(dark: bool) -> str:
    bg  = "#0d1117" if dark else "#f6f8fa"
    bdr = "#21262d" if dark else "#d0d7de"
    txt = "#e6edf3" if dark else "#1f2328"
    return (
        f"background:{bg}; border:1px solid {bdr}; border-radius:8px; "
        f"color:{txt}; width:100%;"
    )


def _body_bg(dark: bool) -> None:
    bg = "#0d1117" if dark else "#f0f4f8"
    ui.query("body").style(f"background:{bg};")


# ── Bucket settings dialog helpers ────────────────────────────────────────────

async def _open_bucket_settings(row: dict, dlg, ctx: dict, s3, dark: bool) -> None:
    bucket = row.get("name", "")
    if not bucket:
        return
    ctx["bucket"] = bucket
    ctx["title_lbl"].set_text(f"⚙  {bucket}")
    ctx["spinner"].style("display:inline-block;")
    ctx["pol_err"].set_text("")
    ctx["cors_err"].set_text("")
    ctx["ver_err"].set_text("")
    dlg.open()

    loop = asyncio.get_event_loop()

    async def _safe(fn):
        try:
            return await loop.run_in_executor(None, fn)
        except Exception:
            return None

    pol, cors_rules, ver = await asyncio.gather(
        _safe(lambda: s3.get_bucket_policy(bucket)),
        _safe(lambda: s3.get_bucket_cors(bucket)),
        _safe(lambda: s3.get_bucket_versioning(bucket)),
    )
    ctx["spinner"].style("display:none;")

    # Policy
    try:
        pretty = json.dumps(json.loads(pol), indent=2) if pol else ""
    except Exception:
        pretty = pol or ""
    ctx["pol_area"].set_value(pretty)

    # CORS
    ctx["_cors_rules"] = cors_rules or []
    _render_cors(ctx["cors_col"], cors_rules or [], dark)

    # Versioning
    ver_str = ver or ""
    ctx["ver_status_lbl"].set_text(
        f"● Enabled" if ver_str == "Enabled"
        else ("⊘ Suspended" if ver_str == "Suspended"
              else "— Never enabled")
    )
    ctx["ver_status_lbl"].style(
        f"color:{'#3fb950' if ver_str == 'Enabled' else ('#da3633' if ver_str == 'Suspended' else '#8b949e')}; "
        "font-size:1.1rem; font-weight:700; margin-bottom:12px;"
    )


async def _save_policy(s3, ctx: dict, dark: bool) -> None:
    bucket = ctx.get("bucket", "")
    raw    = (ctx["pol_area"].value or "").strip()
    if not raw:
        ctx["pol_err"].set_text("Policy JSON is empty.")
        return
    try:
        json.loads(raw)  # validate JSON
    except json.JSONDecodeError as e:
        ctx["pol_err"].set_text(f"Invalid JSON: {e}")
        return
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: s3.put_bucket_policy(bucket, raw))
        ctx["pol_err"].set_text("")
        ui.notify("Policy saved.", type="positive")
    except Exception as exc:
        ctx["pol_err"].set_text(str(exc))


async def _delete_policy(s3, ctx: dict, dark: bool) -> None:
    bucket = ctx.get("bucket", "")
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: s3.delete_bucket_policy(bucket))
        ctx["pol_area"].set_value("")
        ctx["pol_err"].set_text("")
        ui.notify("Policy deleted.", type="warning")
    except Exception as exc:
        ctx["pol_err"].set_text(str(exc))


def _render_cors(col, rules: list, dark: bool) -> None:
    col.clear()
    bg  = "#0d1117" if dark else "#f6f8fa"
    bdr = "#21262d" if dark else "#d0d7de"
    txt = "#e6edf3" if dark else "#1f2328"
    mut = "#8b949e" if dark else "#57606a"

    with col:
        if not rules:
            ui.label("No CORS rules configured.").style(
                f"color:{mut}; font-size:0.82rem; padding:4px 0;"
            )
            return
        for i, rule in enumerate(rules):
            with ui.card().style(
                f"background:{bg}; border:1px solid {bdr}; "
                "border-radius:8px; padding:10px 14px; width:100%;"
            ):
                def _row(label, value):
                    with ui.row().style("gap:8px; align-items:flex-start;"):
                        ui.label(label).style(
                            f"color:{mut}; font-size:0.7rem; font-weight:700; "
                            "text-transform:uppercase; letter-spacing:0.08em; "
                            "min-width:80px; flex-shrink:0; padding-top:2px;"
                        )
                        ui.label(", ".join(value) if isinstance(value, list) else str(value)).style(
                            f"color:{txt}; font-size:0.8rem; font-family:monospace; "
                            "word-break:break-all;"
                        )
                _row("Origins",  rule.get("AllowedOrigins", []))
                _row("Methods",  rule.get("AllowedMethods", []))
                if rule.get("AllowedHeaders"):
                    _row("Headers", rule["AllowedHeaders"])
                if rule.get("MaxAgeSeconds"):
                    _row("MaxAge",  str(rule["MaxAgeSeconds"]) + "s")


async def _add_cors_rule(s3, ctx: dict, dark: bool) -> None:
    bucket  = ctx.get("bucket", "")
    origins = [o.strip() for o in (ctx["cors_origins"].value or "").split(",") if o.strip()]
    methods = [m.strip().upper() for m in (ctx["cors_methods"].value or "").split(",") if m.strip()]
    headers = [h.strip() for h in (ctx["cors_headers"].value or "").split(",") if h.strip()]

    if not origins:
        ctx["cors_err"].set_text("At least one origin is required (use * for all).")
        return
    if not methods:
        ctx["cors_err"].set_text("At least one method is required.")
        return

    valid_methods = {"GET", "PUT", "POST", "DELETE", "HEAD"}
    bad = [m for m in methods if m not in valid_methods]
    if bad:
        ctx["cors_err"].set_text(f"Invalid method(s): {', '.join(bad)}")
        return

    new_rule: dict = {"AllowedOrigins": origins, "AllowedMethods": methods}
    if headers:
        new_rule["AllowedHeaders"] = headers

    existing = list(ctx.get("_cors_rules", []))
    existing.append(new_rule)

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: s3.put_bucket_cors(bucket, existing))
        ctx["_cors_rules"] = existing
        _render_cors(ctx["cors_col"], existing, dark)
        ctx["cors_origins"].set_value("")
        ctx["cors_methods"].set_value("")
        ctx["cors_headers"].set_value("")
        ctx["cors_err"].set_text("")
        ui.notify("CORS rule added.", type="positive")
    except Exception as exc:
        ctx["cors_err"].set_text(str(exc))


async def _delete_cors(s3, ctx: dict, dark: bool) -> None:
    bucket = ctx.get("bucket", "")
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: s3.delete_bucket_cors(bucket))
        ctx["_cors_rules"] = []
        _render_cors(ctx["cors_col"], [], dark)
        ctx["cors_err"].set_text("")
        ui.notify("All CORS rules deleted.", type="warning")
    except Exception as exc:
        ctx["cors_err"].set_text(str(exc))


async def _set_versioning(s3, ctx: dict, status: str, dark: bool) -> None:
    bucket = ctx.get("bucket", "")
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: s3.put_bucket_versioning(bucket, status))
        ctx["ver_status_lbl"].set_text(
            "● Enabled" if status == "Enabled" else "⊘ Suspended"
        )
        ctx["ver_status_lbl"].style(
            f"color:{'#3fb950' if status == 'Enabled' else '#da3633'}; "
            "font-size:1.1rem; font-weight:700; margin-bottom:12px;"
        )
        ctx["ver_err"].set_text("")
        ui.notify(f"Versioning {status.lower()}.", type="positive")
    except Exception as exc:
        ctx["ver_err"].set_text(str(exc))


def _open_create(dlg, f_name, f_region, err, conn: dict) -> None:
    f_name.set_value("")
    f_region.set_value(conn.get("region", "us-east-1"))
    err.set_text("")
    dlg.open()
