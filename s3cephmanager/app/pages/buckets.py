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
from app.rgw_admin import get_rgw_from_conn as _get_rgw

# Human-readable labels for permission levels
_PERM_LABELS = {
    "read":       "Read only",
    "write":      "Write only",
    "read_write": "Read + Write",
    "full":       "Full Control",
}


# ─────────────────────────────────────────────────────────────────────────────
@ui.page("/buckets")
async def buckets_page() -> None:
    create_layout(current_path="/buckets")
    dark = app.storage.user.get("dark_mode", True)
    _body_bg(dark)

    conn = require_connection()
    if not conn:
        return

    s3  = get_s3_from_conn(conn)
    rgw = _get_rgw(conn)  # None if admin_mode / admin_endpoint not configured

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
        table.on("bucket_settings", lambda e: _open_bucket_settings(e.args, bucket_dlg, bkt_ctx, s3, rgw, dark))

        # Filter
        search.on("input", lambda e: table.run_method(
            "filterMethod", e.sender.value
        ))

    # ── Create dialog ─────────────────────────────────────────────────────────
    _cperms: dict = {}   # {uid: level} – permissions to apply after creation
    _cperm_rows: list = []  # list of (uid_inp, level_sel, row_el) widgets

    def _cperm_add_row(uid_val: str = "", level_val: str = "read_write") -> None:
        """Add one user-permission row inside the create dialog."""
        bg  = "#0d1117" if dark else "#f6f8fa"
        bdr = "#21262d" if dark else "#d0d7de"
        txt = "#e6edf3" if dark else "#1f2328"
        with cperm_col:
            with ui.row().style(
                "align-items:center; gap:6px; width:100%;"
            ) as row_el:
                uid_inp = ui.input(placeholder="username").props(
                    "dense outlined dark" if dark else "dense outlined"
                ).style(
                    f"background:{bg}; border:1px solid {bdr}; border-radius:6px; "
                    f"color:{txt}; flex:1; font-size:0.82rem;"
                )
                uid_inp.set_value(uid_val)
                lvl_sel = ui.select(
                    options=list(_PERM_LABELS.keys()),
                    value=level_val,
                ).props("dense outlined dark" if dark else "dense outlined").style(
                    f"background:{bg}; border:1px solid {bdr}; border-radius:6px; "
                    f"color:{txt}; width:130px; font-size:0.82rem;"
                )
                entry = (uid_inp, lvl_sel, row_el)
                _cperm_rows.append(entry)
                ui.button(
                    icon="remove_circle_outline",
                    on_click=lambda e=entry: _cperm_remove_row(e),
                ).props("flat round dense").style("color:#da3633; flex-shrink:0;")

    def _cperm_remove_row(entry) -> None:
        uid_inp, lvl_sel, row_el = entry
        if entry in _cperm_rows:
            _cperm_rows.remove(entry)
        row_el.delete()

    with ui.dialog() as create_dlg, _dialog_card(dark, "520px"):
        _dlg_title("Create Bucket", dark)
        f_name   = _dlg_input("Bucket Name", "my-new-bucket", dark)
        f_region = _dlg_input("Region", conn.get("region", "us-east-1"), dark)

        # ── Optional Permissions section ───────────────────────────────────
        mut = "#8b949e" if dark else "#57606a"
        bdr = "#21262d" if dark else "#d0d7de"
        with ui.expansion(
            "Access Permissions (optional)",
            icon="manage_accounts",
        ).props("dense").style(
            f"color:{mut}; font-size:0.82rem; "
            f"border:1px solid {bdr}; border-radius:8px; "
            "margin-bottom:10px; width:100%;"
        ):
            ui.label(
                "Grant users access to this bucket immediately after creation."
            ).style(f"color:{mut}; font-size:0.78rem; margin-bottom:8px;")
            cperm_col = ui.column().style("gap:6px; width:100%;")
            ui.button(
                "Add user", icon="add",
                on_click=_cperm_add_row,
            ).props("flat no-caps dense").style(
                "color:#58a6ff; font-size:0.8rem; margin-top:4px;"
            )

        err_create = _dlg_err()
        with ui.row().style("justify-content:flex-end; gap:8px; margin-top:16px;"):
            _cancel_btn(create_dlg, dark)
            _primary_btn(
                "Create",
                lambda: _create(
                    s3,
                    f_name.value,
                    f_region.value,
                    create_dlg,
                    table,
                    stats_row,
                    err_create,
                    dark,
                    permissions={
                        uid_inp.value.strip(): lvl_sel.value
                        for uid_inp, lvl_sel, _ in _cperm_rows
                        if uid_inp.value.strip()
                    },
                ),
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
            btab_pol  = ui.tab("Policy",      icon="policy")
            btab_cors = ui.tab("CORS",         icon="public")
            btab_ver  = ui.tab("Versioning",   icon="history")
            btab_perm = ui.tab("Permissions",  icon="manage_accounts")
            btab_lc   = ui.tab("Lifecycle",    icon="schedule")

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

            # ── Permissions tab ───────────────────────────────────────────
            with ui.tab_panel(btab_perm):
                _pmut = "#8b949e" if dark else "#57606a"
                _ptxt = "#e6edf3" if dark else "#1f2328"
                _pbdr = "#21262d" if dark else "#d0d7de"
                _pbg  = "#0d1117" if dark else "#f6f8fa"

                ui.label("User Access Control").style(
                    f"color:{_pmut}; font-size:0.7rem; font-weight:700; "
                    "text-transform:uppercase; letter-spacing:0.1em; margin-bottom:6px;"
                )
                if not rgw:
                    ui.label(
                        "Enable Admin Mode + Admin Endpoint in Connection Settings "
                        "to manage user permissions here."
                    ).style(f"color:{_pmut}; font-size:0.82rem;")
                else:
                    bkt_ctx["perm_col"] = ui.column().style(
                        "gap:6px; width:100%; min-height:40px;"
                    )
                    ui.separator().style(
                        f"border-color:{_pbdr}; margin:12px 0;"
                    )
                    ui.label("Add user access").style(
                        f"color:{_ptxt}; font-size:0.82rem; "
                        "font-weight:600; margin-bottom:6px;"
                    )
                    with ui.row().style("align-items:center; gap:8px; width:100%;"):
                        bkt_ctx["perm_uid"] = ui.select(
                            options=[], label="User",
                        ).props(
                            "dense outlined dark" if dark else "dense outlined"
                        ).style(
                            f"background:{_pbg}; border:1px solid {_pbdr}; "
                            f"border-radius:8px; color:{_ptxt}; flex:1;"
                        )
                        bkt_ctx["perm_lvl"] = ui.select(
                            options={k: v for k, v in _PERM_LABELS.items()},
                            value="read_write",
                            label="Permission",
                        ).props(
                            "dense outlined dark" if dark else "dense outlined"
                        ).style(
                            f"background:{_pbg}; border:1px solid {_pbdr}; "
                            f"border-radius:8px; color:{_ptxt}; width:150px;"
                        )
                        ui.button(
                            icon="add",
                            on_click=lambda: _add_perm(s3, bkt_ctx, dark),
                        ).props("no-caps").style(
                            "background:#1f6feb; color:#fff; border-radius:8px; "
                            "font-weight:600; flex-shrink:0;"
                        )
                    bkt_ctx["perm_err"] = ui.label("").style(
                        "color:#da3633; font-size:0.8rem; min-height:18px;"
                    )
                    with ui.row().style("margin-top:10px;"):
                        ui.button(
                            "Save Permissions", icon="save",
                            on_click=lambda: _save_perms(s3, bkt_ctx, dark),
                        ).props("no-caps").style(
                            "background:#1f6feb; color:#fff; border-radius:8px; "
                            "font-weight:600;"
                        )

            # ── Lifecycle tab ──────────────────────────────────────────────
            with ui.tab_panel(btab_lc):
                _lmut = "#8b949e" if dark else "#57606a"
                _ltxt = "#e6edf3" if dark else "#1f2328"
                _lbdr = "#21262d" if dark else "#d0d7de"
                _lbg  = "#0d1117" if dark else "#f6f8fa"

                ui.label("Lifecycle Rules").style(
                    f"color:{_lmut}; font-size:0.7rem; font-weight:700; "
                    "text-transform:uppercase; letter-spacing:0.1em; margin-bottom:6px;"
                )
                bkt_ctx["lc_col"] = ui.column().style(
                    "gap:8px; width:100%; min-height:40px;"
                )

                ui.separator().style(f"border-color:{_lbdr}; margin:12px 0;")
                ui.label("Add / Update Rule").style(
                    f"color:{_ltxt}; font-size:0.82rem; font-weight:600; margin-bottom:8px;"
                )
                with ui.row().style("gap:8px; width:100%; align-items:flex-start;"):
                    with ui.column().style("gap:4px; flex:1;"):
                        ui.label("Rule ID (optional)").style(
                            f"color:{_lmut}; font-size:0.72rem; font-weight:600; "
                            "text-transform:uppercase; letter-spacing:0.06em;"
                        )
                        bkt_ctx["lc_id"] = ui.input(
                            placeholder="auto-generated if blank"
                        ).props(
                            "dense outlined dark" if dark else "dense outlined"
                        ).style(_inp(dark))
                    with ui.column().style("gap:4px; flex:1;"):
                        ui.label("Prefix filter (blank = all objects)").style(
                            f"color:{_lmut}; font-size:0.72rem; font-weight:600; "
                            "text-transform:uppercase; letter-spacing:0.06em;"
                        )
                        bkt_ctx["lc_prefix"] = ui.input(
                            placeholder="e.g. uploads/"
                        ).props(
                            "dense outlined dark" if dark else "dense outlined"
                        ).style(_inp(dark))

                with ui.row().style(
                    "gap:8px; width:100%; margin-top:8px; align-items:flex-start;"
                ):
                    with ui.column().style("gap:4px; flex:1;"):
                        ui.label("Expire objects (days, 0 = off)").style(
                            f"color:{_lmut}; font-size:0.72rem; font-weight:600; "
                            "text-transform:uppercase; letter-spacing:0.06em;"
                        )
                        bkt_ctx["lc_exp_days"] = ui.number(
                            value=0, min=0, step=1, format="%.0f",
                        ).props(
                            "dense outlined dark" if dark else "dense outlined"
                        ).style(
                            f"background:{_lbg}; border:1px solid {_lbdr}; "
                            f"border-radius:8px; color:{_ltxt}; width:100%;"
                        )
                    with ui.column().style("gap:4px; flex:1;"):
                        ui.label("Old versions (days, 0 = off)").style(
                            f"color:{_lmut}; font-size:0.72rem; font-weight:600; "
                            "text-transform:uppercase; letter-spacing:0.06em;"
                        )
                        bkt_ctx["lc_noncur_days"] = ui.number(
                            value=0, min=0, step=1, format="%.0f",
                        ).props(
                            "dense outlined dark" if dark else "dense outlined"
                        ).style(
                            f"background:{_lbg}; border:1px solid {_lbdr}; "
                            f"border-radius:8px; color:{_ltxt}; width:100%;"
                        )
                    with ui.column().style("gap:4px; flex:1;"):
                        ui.label("Abort multipart (days, 0 = off)").style(
                            f"color:{_lmut}; font-size:0.72rem; font-weight:600; "
                            "text-transform:uppercase; letter-spacing:0.06em;"
                        )
                        bkt_ctx["lc_abort_days"] = ui.number(
                            value=0, min=0, step=1, format="%.0f",
                        ).props(
                            "dense outlined dark" if dark else "dense outlined"
                        ).style(
                            f"background:{_lbg}; border:1px solid {_lbdr}; "
                            f"border-radius:8px; color:{_ltxt}; width:100%;"
                        )

                bkt_ctx["lc_enabled"] = ui.checkbox("Rule enabled", value=True).style(
                    f"color:{_ltxt}; margin-top:8px;"
                )
                bkt_ctx["lc_err"] = ui.label("").style(
                    "color:#da3633; font-size:0.8rem; min-height:18px;"
                )
                with ui.row().style("gap:8px; margin-top:6px;"):
                    ui.button(
                        "Add / Update Rule", icon="add_circle",
                        on_click=lambda: _add_lifecycle_rule(s3, bkt_ctx, dark),
                    ).props("no-caps").style(
                        "background:#1f6feb; color:#fff; "
                        "border-radius:8px; font-weight:600;"
                    )
                    ui.button(
                        "Delete All Rules", icon="delete_sweep",
                        on_click=lambda: _delete_all_lifecycle(s3, bkt_ctx, dark),
                    ).props("no-caps flat").style("color:#da3633;")

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
                  err_lbl, dark: bool, permissions: dict | None = None) -> None:
    if not name.strip():
        err_lbl.set_text("Bucket name is required.")
        return
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: s3.create_bucket(name.strip(), region or "us-east-1")
        )
        # Apply initial user permissions if any were specified
        if permissions:
            try:
                await loop.run_in_executor(
                    None,
                    lambda: s3.set_bucket_user_permissions(name.strip(), permissions),
                )
            except Exception as perm_exc:
                ui.notify(
                    f"Bucket created but permissions error: {perm_exc}",
                    type="warning",
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

async def _open_bucket_settings(row: dict, dlg, ctx: dict, s3, rgw, dark: bool) -> None:
    bucket = row.get("name", "")
    if not bucket:
        return
    ctx["bucket"] = bucket
    ctx["title_lbl"].set_text(f"⚙  {bucket}")
    ctx["spinner"].style("display:inline-block;")
    ctx["pol_err"].set_text("")
    ctx["cors_err"].set_text("")
    ctx["ver_err"].set_text("")
    if "perm_err" in ctx:
        ctx["perm_err"].set_text("")
    dlg.open()

    loop = asyncio.get_event_loop()

    async def _safe(fn):
        try:
            return await loop.run_in_executor(None, fn)
        except Exception:
            return None

    async def _empty():
        return []

    pol, cors_rules, ver, perms, users_list, lc_rules = await asyncio.gather(
        _safe(lambda: s3.get_bucket_policy(bucket)),
        _safe(lambda: s3.get_bucket_cors(bucket)),
        _safe(lambda: s3.get_bucket_versioning(bucket)),
        _safe(lambda: s3.get_bucket_user_permissions(bucket)),
        _safe(lambda: rgw.list_users()) if rgw else _empty(),
        _safe(lambda: s3.get_bucket_lifecycle(bucket)),
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
        "● Enabled" if ver_str == "Enabled"
        else ("⊘ Suspended" if ver_str == "Suspended"
              else "— Never enabled")
    )
    ctx["ver_status_lbl"].style(
        f"color:{'#3fb950' if ver_str == 'Enabled' else ('#da3633' if ver_str == 'Suspended' else '#8b949e')}; "
        "font-size:1.1rem; font-weight:700; margin-bottom:12px;"
    )

    # Permissions (only if rgw is configured and panel exists)
    if rgw and "perm_uid" in ctx:
        cur_perms: dict = dict(perms or {})
        ctx["_cur_perms"] = cur_perms
        # Build user list for the dropdown (all users from RGW)
        all_users = [u for u in (users_list or []) if isinstance(u, str)]
        ctx["_all_users"] = all_users
        ctx["perm_uid"].set_options(all_users)
        if all_users:
            ctx["perm_uid"].set_value(all_users[0])
        _render_perms(ctx["perm_col"], cur_perms, ctx, s3, dark)

    # Lifecycle
    ctx["_lc_rules"] = list(lc_rules or [])
    if "lc_col" in ctx:
        if "lc_err" in ctx:
            ctx["lc_err"].set_text("")
        _render_lifecycle_rules(ctx["lc_col"], ctx["_lc_rules"], ctx, s3, dark)


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


def _render_perms(col, perms: dict, ctx: dict, s3, dark: bool) -> None:
    """Render current user-permission rows inside the Permissions tab panel."""
    col.clear()
    bg  = "#0d1117" if dark else "#f6f8fa"
    bdr = "#21262d" if dark else "#d0d7de"
    txt = "#e6edf3" if dark else "#1f2328"
    mut = "#8b949e" if dark else "#57606a"
    act = "#58a6ff" if dark else "#0969da"

    with col:
        if not perms:
            ui.label("No user-level access configured.").style(
                f"color:{mut}; font-size:0.82rem; padding:4px 0;"
            )
            return
        for uid, level in perms.items():
            with ui.card().style(
                f"background:{bg}; border:1px solid {bdr}; "
                "border-radius:8px; padding:8px 12px; width:100%;"
            ):
                with ui.row().style(
                    "align-items:center; justify-content:space-between; width:100%;"
                ):
                    with ui.row().style("align-items:center; gap:8px;"):
                        ui.icon("person").style(f"color:{act}; font-size:1.1rem;")
                        ui.label(uid).style(
                            f"color:{txt}; font-size:0.85rem; font-weight:600;"
                        )
                        ui.badge(_PERM_LABELS.get(level, level)).props(
                            "outline"
                        ).style(
                            f"color:{act}; border-color:{act}; "
                            "font-size:0.7rem; border-radius:4px; padding:2px 6px;"
                        )
                    ui.button(
                        icon="remove_circle_outline",
                        on_click=lambda _uid=uid: _remove_perm(_uid, ctx, s3, dark),
                    ).props("flat round dense").style(
                        "color:#da3633; flex-shrink:0;"
                    )


async def _remove_perm(uid: str, ctx: dict, s3, dark: bool) -> None:
    """Remove a single user's bucket permission and save immediately."""
    perms = dict(ctx.get("_cur_perms", {}))
    perms.pop(uid, None)
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            lambda: s3.set_bucket_user_permissions(ctx["bucket"], perms),
        )
        ctx["_cur_perms"] = perms
        if "perm_err" in ctx:
            ctx["perm_err"].set_text("")
        _render_perms(ctx["perm_col"], perms, ctx, s3, dark)
        ui.notify(f"Access removed for '{uid}'.", type="warning")
    except Exception as exc:
        if "perm_err" in ctx:
            ctx["perm_err"].set_text(str(exc))


async def _add_perm(s3, ctx: dict, dark: bool) -> None:
    """Add a user permission row and save immediately."""
    uid   = (ctx["perm_uid"].value or "").strip()
    level = ctx["perm_lvl"].value or "read_write"
    if not uid:
        if "perm_err" in ctx:
            ctx["perm_err"].set_text("Select a user.")
        return
    perms = dict(ctx.get("_cur_perms", {}))
    perms[uid] = level
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            lambda: s3.set_bucket_user_permissions(ctx["bucket"], perms),
        )
        ctx["_cur_perms"] = perms
        if "perm_err" in ctx:
            ctx["perm_err"].set_text("")
        _render_perms(ctx["perm_col"], perms, ctx, s3, dark)
        ui.notify(
            f"Access granted to '{uid}' ({_PERM_LABELS.get(level, level)}).",
            type="positive",
        )
    except Exception as exc:
        if "perm_err" in ctx:
            ctx["perm_err"].set_text(str(exc))


async def _save_perms(s3, ctx: dict, dark: bool) -> None:
    """Explicitly (re-)save the current permissions in _cur_perms."""
    perms  = dict(ctx.get("_cur_perms", {}))
    bucket = ctx.get("bucket", "")
    if not bucket:
        return
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            lambda: s3.set_bucket_user_permissions(bucket, perms),
        )
        if "perm_err" in ctx:
            ctx["perm_err"].set_text("")
        _render_perms(ctx["perm_col"], perms, ctx, s3, dark)
        ui.notify("Permissions saved.", type="positive")
    except Exception as exc:
        if "perm_err" in ctx:
            ctx["perm_err"].set_text(str(exc))


def _render_lifecycle_rules(col, rules: list, ctx: dict, s3, dark: bool) -> None:
    """Render existing lifecycle rule cards inside the Lifecycle tab panel."""
    col.clear()
    bg  = "#0d1117" if dark else "#f6f8fa"
    bdr = "#21262d" if dark else "#d0d7de"
    txt = "#e6edf3" if dark else "#1f2328"
    mut = "#8b949e" if dark else "#57606a"

    with col:
        if not rules:
            ui.label("No lifecycle rules configured.").style(
                f"color:{mut}; font-size:0.82rem; padding:4px 0;"
            )
            return
        for rule in rules:
            rule_id = rule.get("ID", "—")
            status  = rule.get("Status", "Enabled")
            flt     = rule.get("Filter") or {}
            prefix  = flt.get("Prefix", "")
            exp     = (rule.get("Expiration") or {}).get("Days")
            noncur  = (rule.get("NoncurrentVersionExpiration") or {}).get("NoncurrentDays")
            abort   = (rule.get("AbortIncompleteMultipartUpload") or {}).get("DaysAfterInitiation")
            is_on   = (status == "Enabled")

            with ui.card().style(
                f"background:{bg}; border:1px solid {bdr}; "
                "border-radius:8px; padding:10px 14px; width:100%;"
            ):
                with ui.row().style(
                    "align-items:center; justify-content:space-between; "
                    "width:100%; margin-bottom:6px;"
                ):
                    with ui.row().style("align-items:center; gap:8px;"):
                        ui.icon("schedule").style("color:#58a6ff; font-size:1.1rem;")
                        ui.label(rule_id).style(
                            f"color:{txt}; font-size:0.85rem; font-weight:600;"
                        )
                        ui.badge(status).props("outline").style(
                            f"color:{'#3fb950' if is_on else mut}; "
                            f"border-color:{'#3fb950' if is_on else mut}; "
                            "font-size:0.7rem; border-radius:4px; padding:2px 6px;"
                        )
                    ui.button(
                        icon="delete",
                        on_click=lambda _id=rule_id: _delete_lifecycle_rule(
                            s3, ctx, _id, dark
                        ),
                    ).props("flat round dense").style("color:#da3633; flex-shrink:0;")
                with ui.column().style("gap:2px; padding-left:4px;"):
                    if prefix:
                        _lc_row(f"📂  Prefix: {prefix!r}", mut)
                    else:
                        _lc_row("📂  Applies to all objects", mut)
                    if exp:
                        _lc_row(f"🗑  Delete objects after {exp} day(s)", txt)
                    if noncur:
                        _lc_row(f"🗑  Delete old versions after {noncur} day(s)", txt)
                    if abort:
                        _lc_row(f"⏹  Abort incomplete uploads after {abort} day(s)", txt)


def _lc_row(text: str, color: str) -> None:
    ui.label(text).style(
        f"color:{color}; font-size:0.78rem; font-family:monospace;"
    )


async def _add_lifecycle_rule(s3, ctx: dict, dark: bool) -> None:
    """Validate the form, build a lifecycle rule and save it to the bucket."""
    import uuid as _uuid
    rule_id     = (ctx["lc_id"].value or "").strip()
    prefix      = (ctx["lc_prefix"].value or "").strip()
    exp_days    = int(ctx["lc_exp_days"].value    or 0)
    noncur_days = int(ctx["lc_noncur_days"].value or 0)
    abort_days  = int(ctx["lc_abort_days"].value  or 0)
    enabled     = bool(ctx["lc_enabled"].value)

    if not (exp_days or noncur_days or abort_days):
        ctx["lc_err"].set_text(
            "Set at least one expiration condition (days > 0)."
        )
        return

    if not rule_id:
        rule_id = f"rule-{_uuid.uuid4().hex[:8]}"

    rule: dict = {
        "ID":     rule_id,
        "Status": "Enabled" if enabled else "Disabled",
        "Filter": {"Prefix": prefix},
    }
    if exp_days > 0:
        rule["Expiration"] = {"Days": exp_days}
    if noncur_days > 0:
        rule["NoncurrentVersionExpiration"] = {"NoncurrentDays": noncur_days}
    if abort_days > 0:
        rule["AbortIncompleteMultipartUpload"] = {"DaysAfterInitiation": abort_days}

    # Replace rule with same ID if it already exists; otherwise append
    rules = [r for r in ctx.get("_lc_rules", []) if r.get("ID") != rule_id]
    rules.append(rule)

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None, lambda: s3.put_bucket_lifecycle(ctx["bucket"], rules)
        )
        ctx["_lc_rules"] = rules
        ctx["lc_err"].set_text("")
        # Reset form fields
        ctx["lc_id"].set_value("")
        ctx["lc_prefix"].set_value("")
        ctx["lc_exp_days"].set_value(0)
        ctx["lc_noncur_days"].set_value(0)
        ctx["lc_abort_days"].set_value(0)
        ctx["lc_enabled"].set_value(True)
        _render_lifecycle_rules(ctx["lc_col"], rules, ctx, s3, dark)
        ui.notify(f"Lifecycle rule '{rule_id}' saved.", type="positive")
    except Exception as exc:
        ctx["lc_err"].set_text(str(exc))


async def _delete_lifecycle_rule(s3, ctx: dict, rule_id: str, dark: bool) -> None:
    """Delete one lifecycle rule by ID and persist the remaining rules."""
    rules = [r for r in ctx.get("_lc_rules", []) if r.get("ID") != rule_id]
    loop  = asyncio.get_event_loop()
    try:
        if rules:
            await loop.run_in_executor(
                None, lambda: s3.put_bucket_lifecycle(ctx["bucket"], rules)
            )
        else:
            await loop.run_in_executor(
                None, lambda: s3.delete_bucket_lifecycle(ctx["bucket"])
            )
        ctx["_lc_rules"] = rules
        if "lc_err" in ctx:
            ctx["lc_err"].set_text("")
        _render_lifecycle_rules(ctx["lc_col"], rules, ctx, s3, dark)
        ui.notify(f"Lifecycle rule '{rule_id}' deleted.", type="warning")
    except Exception as exc:
        if "lc_err" in ctx:
            ctx["lc_err"].set_text(str(exc))


async def _delete_all_lifecycle(s3, ctx: dict, dark: bool) -> None:
    """Remove all lifecycle rules from the bucket."""
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None, lambda: s3.delete_bucket_lifecycle(ctx["bucket"])
        )
        ctx["_lc_rules"] = []
        if "lc_err" in ctx:
            ctx["lc_err"].set_text("")
        _render_lifecycle_rules(ctx["lc_col"], [], ctx, s3, dark)
        ui.notify("All lifecycle rules deleted.", type="warning")
    except Exception as exc:
        if "lc_err" in ctx:
            ctx["lc_err"].set_text(str(exc))


def _open_create(dlg, f_name, f_region, err, conn: dict) -> None:
    f_name.set_value("")
    f_region.set_value(conn.get("region", "us-east-1"))
    err.set_text("")
    dlg.open()
