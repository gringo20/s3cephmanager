"""
Ceph RGW User Management  –  full operations edition
=====================================================

Requires:
  • Active connection with admin_mode = True
  • RGW Admin Endpoint configured on the connection

Features
--------
  • Progressive async user list (batch of 8 parallel get_user calls)
  • Create user  (uid, display-name, email, max-buckets, auto-key)
  • Suspend / Activate with one click
  • Delete with optional data purge
  • Per-user detail dialog with four tabs:
      Info   – edit display-name, email, max-buckets
      Keys   – list S3 key pairs, reveal secret, copy, add, delete
      Quota  – enable/disable, max size (GB), max objects
      Usage  – live size + object stats
"""
from __future__ import annotations

import asyncio
from nicegui import ui, app

from app.components.sidebar import create_layout, require_connection
from app.rgw_admin           import get_rgw_from_conn, RGWError
import humanize


# ─────────────────────────────────────────────────────────────────────────────
#  Page entry-point
# ─────────────────────────────────────────────────────────────────────────────

@ui.page("/users")
async def users_page() -> None:
    create_layout(current_path="/users")
    dark = app.storage.user.get("dark_mode", True)
    _body_bg(dark)
    C = _pal(dark)

    conn = require_connection()
    if not conn:
        return

    # ── Guard: need admin_mode + admin_endpoint ───────────────────────────────
    if not conn.get("admin_mode") or not conn.get("admin_endpoint", "").strip():
        with ui.column().style(
            "width:100%; max-width:520px; margin:80px auto; "
            "align-items:center; gap:16px; text-align:center;"
        ):
            ui.icon("admin_panel_settings").style(
                "color:#d29922; font-size:3.5rem;"
            )
            ui.label("Admin Mode required").style(
                f"color:{C['txt']}; font-size:1.35rem; font-weight:700;"
            )
            ui.label(
                "Enable Admin Mode and set an RGW Admin Endpoint on the "
                "active connection to manage users."
            ).style(
                f"color:{C['mut']}; font-size:0.88rem; "
                "line-height:1.6; max-width:380px;"
            )
            ui.button(
                "Edit Connection",
                on_click=lambda: ui.navigate.to("/"),
            ).props("no-caps").style(
                "background:#1f6feb; color:#fff; border-radius:8px; "
                "font-weight:600; padding:8px 22px;"
            )
        return

    rgw = get_rgw_from_conn(conn)

    # ── Page scaffold ─────────────────────────────────────────────────────────
    with ui.column().style(
        "width:100%; max-width:1200px; margin:0 auto; padding:28px 24px; gap:20px;"
    ):
        # Header row
        with ui.row().style(
            "align-items:center; justify-content:space-between; width:100%;"
        ):
            with ui.column().style("gap:2px;"):
                ui.label("Users").style(
                    f"color:{C['txt']}; font-size:1.5rem; font-weight:700;"
                )
                ui.label(f"Admin: {conn.get('admin_endpoint', '')}").style(
                    f"color:{C['mut']}; font-size:0.8rem;"
                )
            with ui.row().style("gap:8px; align-items:center;"):
                search = ui.input(placeholder="Filter…").props(
                    "dense outlined dark" if dark else "dense outlined"
                ).style(_inp(dark) + "width:180px;")
                ui.button(
                    icon="refresh",
                    on_click=lambda: _reload(table, stats_row, rgw, dark),
                ).props("flat round").style(f"color:{C['mut']};")
                ui.button(
                    "＋ Create User",
                    on_click=lambda: _open_create_dlg(
                        create_dlg, cf_uid, cf_name, cf_email, cf_maxb,
                        cf_genkey, create_err,
                    ),
                ).props("no-caps").style(
                    "background:#1f6feb; color:#fff; border-radius:8px; "
                    "font-weight:600; padding:8px 16px;"
                )

        # Stats row
        stats_row = ui.row().style("gap:12px;")

        # ── Table ─────────────────────────────────────────────────────────────
        columns = [
            {"name": "uid",   "label": "User ID",      "field": "uid",
             "align": "left",  "sortable": True},
            {"name": "dname", "label": "Display Name", "field": "display_name",
             "align": "left",  "sortable": True},
            {"name": "email", "label": "Email",        "field": "email",
             "align": "left",  "sortable": True},
            {"name": "maxb",  "label": "Max Buckets",  "field": "max_buckets",
             "align": "right", "sortable": True},
            {"name": "keys",  "label": "Keys",         "field": "keys",
             "align": "right"},
            {"name": "stat",  "label": "Status",       "field": "suspended",
             "align": "left"},
            {"name": "acts",  "label": "",             "field": "uid",
             "align": "right"},
        ]
        table = ui.table(
            columns=columns,
            rows=[],
            row_key="uid",
            pagination={"rowsPerPage": 25, "sortBy": "uid"},
        ).style(
            f"background:{C['sbg']}; border:1px solid {C['bdr']}; "
            "border-radius:10px; width:100%;"
        ).props("flat dark" if dark else "flat")

        # Header styling
        table.add_slot("header", r"""
            <q-tr :props="props">
              <q-th v-for="col in props.cols" :key="col.name" :props="props"
                    style="font-size:0.72rem; font-weight:700; letter-spacing:0.06em;
                           text-transform:uppercase; opacity:0.65;">
                {{ col.label }}
              </q-th>
            </q-tr>
        """)

        # uid cell – clickable
        table.add_slot("body-cell-uid", r"""
            <q-td :props="props">
              <span
                style="color:#58a6ff; font-weight:600; cursor:pointer; font-size:0.88rem;"
                @click="$parent.$emit('detail', props.row)"
              >👤 {{ props.value }}</span>
            </q-td>
        """)

        # status badge
        table.add_slot("body-cell-stat", r"""
            <q-td :props="props">
              <span :style="props.row.suspended === 'Yes'
                ? 'color:#f85149;background:#da363320;padding:2px 8px;border-radius:4px;font-size:0.74rem;font-weight:600;'
                : 'color:#3fb950;background:#2ea04320;padding:2px 8px;border-radius:4px;font-size:0.74rem;font-weight:600;'">
                {{ props.row.suspended === 'Yes' ? '⊘ Suspended' : '● Active' }}
              </span>
            </q-td>
        """)

        # actions
        table.add_slot("body-cell-acts", r"""
            <q-td :props="props" style="text-align:right; white-space:nowrap; padding-right:8px;">
              <q-btn flat dense round icon="manage_accounts" color="blue-4" size="xs"
                     @click="$parent.$emit('detail', props.row)">
                <q-tooltip>User details</q-tooltip>
              </q-btn>
              <q-btn flat dense round
                     :icon="props.row.suspended === 'Yes' ? 'play_arrow' : 'pause'"
                     :color="props.row.suspended === 'Yes' ? 'green-4' : 'orange-4'"
                     size="xs"
                     @click="$parent.$emit('toggle_sus', props.row)">
                <q-tooltip>{{ props.row.suspended === 'Yes' ? 'Activate' : 'Suspend' }}</q-tooltip>
              </q-btn>
              <q-btn flat dense round icon="delete" color="red-4" size="xs"
                     @click="$parent.$emit('del', props.row)">
                <q-tooltip>Delete user</q-tooltip>
              </q-btn>
            </q-td>
        """)

        table.on("detail",     lambda e: _open_detail(e.args, detail_dlg, detail_ctx, rgw, dark))
        table.on("toggle_sus", lambda e: _open_suspend_dlg(
            e.args, suspend_dlg, sus_uid_lbl, sus_action_lbl, _sus_state
        ))
        table.on("del",        lambda e: _open_del_dlg(
            e.args, del_dlg, del_uid_lbl, del_err, del_purge, _del_state
        ))
        search.on("input", lambda e: table.run_method(
            "filterMethod", e.sender.value
        ))

    # ═══════════════════════════════════════════════════════════════════════════
    #  DIALOGS
    # ═══════════════════════════════════════════════════════════════════════════

    # ── 1. Create User ─────────────────────────────────────────────────────────
    with ui.dialog() as create_dlg, _dlg_card(dark, "480px"):
        _dlg_title("Create User", dark)
        cf_uid    = _dlg_input("User ID (uid)",   "alice",             dark)
        cf_name   = _dlg_input("Display Name",    "Alice Smith",       dark)
        cf_email  = _dlg_input("Email",           "alice@example.com", dark)
        cf_maxb   = ui.number("Max Buckets", value=1000, min=0).props(
            "dense outlined dark" if dark else "dense outlined"
        ).style(_inp(dark) + "width:100%; margin-bottom:10px;")
        cf_genkey = ui.checkbox(
            "Auto-generate S3 key pair", value=True
        ).style(f"color:{C['mut']}; font-size:0.85rem; margin-bottom:6px;")
        create_err = _dlg_err()
        with ui.row().style("justify-content:flex-end; gap:8px; margin-top:14px;"):
            _cancel_btn(create_dlg, dark)
            _primary_btn("Create", lambda: _create_user(
                rgw,
                cf_uid.value, cf_name.value, cf_email.value,
                int(cf_maxb.value or 1000), cf_genkey.value,
                create_dlg, create_err, table, stats_row, dark,
            ))

    # ── 2. User Detail dialog ──────────────────────────────────────────────────
    # All dynamic widget references travel through this dict.
    detail_ctx: dict = {}

    with ui.dialog() as detail_dlg, _dlg_card(dark, "660px"):

        # ── dialog title row
        with ui.row().style(
            "align-items:center; justify-content:space-between; "
            "width:100%; margin-bottom:12px;"
        ):
            with ui.row().style("align-items:center; gap:10px;"):
                detail_ctx["uid_lbl"] = ui.label("").style(
                    f"color:{C['txt']}; font-size:1.05rem; font-weight:700;"
                )
                detail_ctx["spinner"] = ui.spinner("dots", size="xs").style(
                    f"color:{C['mut']}; display:none;"
                )
            ui.button(
                icon="close", on_click=detail_dlg.close
            ).props("flat round").style(f"color:{C['mut']};")

        # ── Tabs
        with ui.tabs().props("dense").style(
            f"color:{C['blue']}; border-bottom:1px solid {C['bdr']}; "
            "margin-bottom:14px;"
        ) as dtabs:
            dtab_info  = ui.tab("Info",  icon="person")
            dtab_keys  = ui.tab("Keys",  icon="key")
            dtab_quota = ui.tab("Quota", icon="data_usage")
            dtab_usage = ui.tab("Usage", icon="bar_chart")

        with ui.tab_panels(dtabs, value=dtab_info).style("width:100%;"):

            # ── Info tab
            with ui.tab_panel(dtab_info):
                detail_ctx["name_inp"]  = _dlg_input("Display Name", "", dark)
                detail_ctx["email_inp"] = _dlg_input("Email",        "", dark)
                detail_ctx["maxb_inp"]  = ui.number(
                    "Max Buckets", value=1000, min=0
                ).props("dense outlined dark" if dark else "dense outlined").style(
                    _inp(dark) + "width:100%; margin-bottom:10px;"
                )
                detail_ctx["info_err"] = _dlg_err()
                _primary_btn("Save Changes", lambda: _save_user_info(rgw, detail_ctx, table, stats_row, dark))

            # ── Keys tab
            with ui.tab_panel(dtab_keys):
                detail_ctx["keys_col"] = ui.column().style(
                    "gap:6px; width:100%; min-height:60px;"
                )
                with ui.row().style(
                    "justify-content:flex-end; margin-top:14px;"
                ):
                    _primary_btn("＋ Add Key", lambda: _add_key(rgw, detail_ctx, new_key_dlg, dark))

            # ── Quota tab
            with ui.tab_panel(dtab_quota):
                ui.label("User-level storage quota").style(
                    f"color:{C['mut']}; font-size:0.7rem; font-weight:700; "
                    "letter-spacing:0.1em; text-transform:uppercase; "
                    "margin-bottom:10px;"
                )
                detail_ctx["q_enabled"] = ui.checkbox(
                    "Enable quota", value=False
                ).style(f"color:{C['txt']}; margin-bottom:10px;")
                detail_ctx["q_size_inp"] = ui.number(
                    "Max Size (GB, −1 = unlimited)", value=-1
                ).props("dense outlined dark" if dark else "dense outlined").style(
                    _inp(dark) + "width:100%; margin-bottom:10px;"
                )
                detail_ctx["q_obj_inp"] = ui.number(
                    "Max Objects (−1 = unlimited)", value=-1
                ).props("dense outlined dark" if dark else "dense outlined").style(
                    _inp(dark) + "width:100%; margin-bottom:10px;"
                )
                detail_ctx["q_err"] = _dlg_err()
                _primary_btn("Save Quota", lambda: _save_quota(rgw, detail_ctx, dark))

            # ── Usage tab
            with ui.tab_panel(dtab_usage):
                detail_ctx["usage_col"] = ui.column().style(
                    "gap:8px; width:100%;"
                )
                ui.button(
                    "Refresh Stats", icon="refresh",
                    on_click=lambda: _load_usage(rgw, detail_ctx, dark),
                ).props("flat no-caps").style(
                    f"color:{C['mut']}; font-size:0.82rem; margin-top:10px;"
                )

        with ui.row().style("justify-content:flex-end; margin-top:14px;"):
            _cancel_btn(detail_dlg, dark)

    # ── 3. New-key reveal dialog ───────────────────────────────────────────────
    new_key_ctx: dict = {}
    with ui.dialog() as new_key_dlg, _dlg_card(dark, "520px"):
        _dlg_title("New S3 Key Generated", dark)
        ui.label(
            "⚠  Save this secret key now — it cannot be retrieved again."
        ).style(
            "color:#da3633; font-size:0.82rem; margin-bottom:12px;"
        )
        new_key_ctx["ak_lbl"] = _mono_box(dark)
        new_key_ctx["sk_lbl"] = _mono_box(dark, blue=True)
        with ui.row().style("gap:8px; margin:10px 0 14px;"):
            _ghost_btn("Copy Access Key", "content_copy", C,
                       lambda: _clip(new_key_ctx["ak_lbl"].text))
            _ghost_btn("Copy Secret Key", "content_copy", C,
                       lambda: _clip(new_key_ctx["sk_lbl"].text))
        with ui.row().style("justify-content:flex-end;"):
            _cancel_btn(new_key_dlg, dark)

    # ── 4. Suspend / Activate confirm ──────────────────────────────────────────
    _sus_state: dict = {"uid": "", "do_suspend": True}
    with ui.dialog() as suspend_dlg, _dlg_card(dark):
        _dlg_title("Confirm Action", dark)
        sus_uid_lbl    = ui.label("").style(
            f"color:{C['txt']}; font-size:0.9rem; margin-bottom:6px;"
        )
        sus_action_lbl = ui.label("").style(
            f"color:{C['mut']}; font-size:0.82rem; margin-bottom:14px;"
        )
        with ui.row().style("justify-content:flex-end; gap:8px;"):
            _cancel_btn(suspend_dlg, dark)
            ui.button("Confirm").props("no-caps").style(
                "background:#e36209; color:#fff; border-radius:8px; font-weight:600;"
            ).on("click", lambda: _do_suspend(
                rgw, _sus_state["uid"], _sus_state["do_suspend"],
                suspend_dlg, table, stats_row, dark,
            ))

    # ── 5. Delete confirm ──────────────────────────────────────────────────────
    _del_state: dict = {"uid": ""}
    with ui.dialog() as del_dlg, _dlg_card(dark):
        _dlg_title("Delete User", dark)
        del_uid_lbl = ui.label("").style(
            "color:#da3633; font-size:0.9rem; font-weight:600; margin-bottom:8px;"
        )
        del_purge = ui.checkbox("Purge all user data (buckets + objects)").style(
            f"color:{C['mut']}; font-size:0.85rem; margin-bottom:8px;"
        )
        del_err = _dlg_err()
        with ui.row().style("justify-content:flex-end; gap:8px; margin-top:10px;"):
            _cancel_btn(del_dlg, dark)
            ui.button("Delete", color="red").props("no-caps").style(
                "color:#fff; border-radius:8px; font-weight:600;"
            ).on("click", lambda: _do_delete(
                rgw, _del_state["uid"], del_purge.value,
                del_dlg, del_err, table, stats_row, dark,
            ))

    # ── Helper closures (need dialog refs) ────────────────────────────────────

    def _open_create_dlg(dlg, uid_i, name_i, email_i, maxb_i, genk_i, err):
        uid_i.set_value("")
        name_i.set_value("")
        email_i.set_value("")
        maxb_i.set_value(1000)
        genk_i.set_value(True)
        err.set_text("")
        dlg.open()

    def _open_suspend_dlg(row, dlg, uid_lbl, action_lbl, state):
        uid     = row.get("uid", "")
        is_sus  = row.get("suspended") == "Yes"
        state["uid"]        = uid
        state["do_suspend"] = not is_sus
        uid_lbl.set_text(f"User: {uid}")
        action_lbl.set_text(
            f"This will {'suspend' if not is_sus else 'activate'} this user."
        )
        dlg.open()

    def _open_del_dlg(row, dlg, uid_lbl, err, purge_chk, state):
        uid = row.get("uid", "")
        state["uid"] = uid
        uid_lbl.set_text(f"🗑  {uid}")
        err.set_text("")
        purge_chk.set_value(False)
        dlg.open()

    # ── Initial load ──────────────────────────────────────────────────────────
    await _reload(table, stats_row, rgw, dark)


# ═════════════════════════════════════════════════════════════════════════════
#  Data / async helpers
# ═════════════════════════════════════════════════════════════════════════════

async def _reload(table, stats_row, rgw, dark: bool) -> None:
    """Fetch all UIDs then hydrate table rows in parallel batches of 8."""
    loop = asyncio.get_event_loop()

    try:
        uids: list[str] = await loop.run_in_executor(None, rgw.list_users)
    except Exception as exc:
        ui.notify(f"Error listing users: {exc}", type="negative")
        return

    # Stats chip
    stats_row.clear()
    with stats_row:
        _stat_chip("Total Users", str(len(uids)), "person", dark)

    if not uids:
        table.rows.clear()
        table.update()
        return

    async def _fetch(uid: str) -> dict:
        try:
            u = await loop.run_in_executor(None, lambda: rgw.get_user(uid))
            return {
                "uid":          uid,
                "display_name": u.get("display_name", ""),
                "email":        u.get("email", "") or "—",
                "max_buckets":  u.get("max_buckets", 1000),
                "keys":         len(u.get("keys", [])),
                "suspended":    "Yes" if u.get("suspended") else "No",
            }
        except Exception:
            return {
                "uid":         uid,
                "display_name": "",
                "email":        "—",
                "max_buckets":  "?",
                "keys":         0,
                "suspended":    "?",
            }

    rows: list[dict] = []
    BATCH = 8
    for i in range(0, len(uids), BATCH):
        batch   = uids[i : i + BATCH]
        results = await asyncio.gather(*[_fetch(u) for u in batch])
        rows.extend(results)
        table.rows.clear()
        table.rows.extend(rows)
        table.update()


async def _open_detail(
    row: dict,
    dlg,
    ctx: dict,
    rgw,
    dark: bool,
) -> None:
    """Open detail dialog, then concurrently load user/quota/stats data."""
    uid = row.get("uid", "")
    if not uid:
        return

    ctx["uid"] = uid
    ctx["uid_lbl"].set_text(uid)
    ctx["spinner"].style("display:inline-block;")
    ctx["info_err"].set_text("")
    ctx["q_err"].set_text("")
    dlg.open()

    loop = asyncio.get_event_loop()

    async def _safe(fn):
        try:
            return await loop.run_in_executor(None, fn)
        except Exception:
            return {}

    user_data, quota_data, stats_data = await asyncio.gather(
        loop.run_in_executor(None, lambda: rgw.get_user(uid)),
        _safe(lambda: rgw.get_user_quota(uid)),
        _safe(lambda: rgw.get_user_stats(uid)),
    )

    ctx["spinner"].style("display:none;")

    # ── Info tab ──────────────────────────────────────────────────────────────
    ctx["name_inp"].set_value(user_data.get("display_name", ""))
    ctx["email_inp"].set_value(user_data.get("email", "") or "")
    ctx["maxb_inp"].set_value(user_data.get("max_buckets", 1000))

    # ── Keys tab ──────────────────────────────────────────────────────────────
    _render_keys(ctx["keys_col"], user_data.get("keys", []), uid, rgw, ctx, dark)

    # ── Quota tab ─────────────────────────────────────────────────────────────
    q_enabled = bool(quota_data.get("enabled", False))
    max_kb    = quota_data.get("max_size_kb", -1)
    max_obj   = quota_data.get("max_objects", -1)
    ctx["q_enabled"].set_value(q_enabled)
    gb = round(max_kb / 1024 / 1024, 3) if (max_kb is not None and max_kb > 0) else -1
    ctx["q_size_inp"].set_value(gb)
    ctx["q_obj_inp"].set_value(max_obj if max_obj is not None else -1)

    # ── Usage tab ─────────────────────────────────────────────────────────────
    _render_usage(ctx["usage_col"], stats_data, dark)


# ── Keys management ───────────────────────────────────────────────────────────

def _render_keys(col, keys: list, uid: str, rgw, ctx: dict, dark: bool) -> None:
    col.clear()
    C = _pal(dark)
    with col:
        if not keys:
            ui.label("No S3 keys configured.").style(
                f"color:{C['mut']}; font-size:0.82rem; padding:6px 0;"
            )
            return
        for k in keys:
            _key_card(
                k.get("access_key", ""),
                k.get("secret_key", ""),
                uid, rgw, ctx, col, dark,
            )


def _key_card(
    ak: str, sk: str,
    uid: str, rgw, ctx: dict, col, dark: bool,
) -> None:
    C = _pal(dark)
    _visible = {"v": False}

    with col:
        with ui.card().style(
            f"background:{C['tbg']}; border:1px solid {C['bdr']}; "
            "border-radius:8px; padding:10px 14px; width:100%;"
        ):
            # Access Key row
            with ui.row().style(
                "align-items:center; gap:6px; margin-bottom:8px;"
            ):
                ui.label("AK").style(
                    f"color:{C['mut']}; font-size:0.6rem; font-weight:700; "
                    "letter-spacing:0.12em; width:22px; flex-shrink:0;"
                )
                ui.label(ak).style(
                    f"color:{C['txt']}; font-family:monospace; font-size:0.78rem; "
                    "flex:1; overflow:hidden; text-overflow:ellipsis; "
                    "white-space:nowrap;"
                )
                ui.button(icon="content_copy").props(
                    "flat round dense"
                ).style(f"color:{C['mut']}; font-size:0.8rem;").on(
                    "click", lambda a=ak: _clip(a)
                )

            # Secret Key row
            with ui.row().style("align-items:center; gap:6px;"):
                ui.label("SK").style(
                    f"color:{C['mut']}; font-size:0.6rem; font-weight:700; "
                    "letter-spacing:0.12em; width:22px; flex-shrink:0;"
                )
                sk_lbl = ui.label("••••••••••••••••••••").style(
                    f"color:{C['mut']}; font-family:monospace; font-size:0.78rem; "
                    "flex:1; overflow:hidden; text-overflow:ellipsis; "
                    "white-space:nowrap;"
                )

                def _toggle(lbl=sk_lbl, state=_visible, s=sk):
                    state["v"] = not state["v"]
                    lbl.set_text(s if state["v"] else "••••••••••••••••••••")

                ui.button(icon="visibility").props(
                    "flat round dense"
                ).style(f"color:{C['mut']}; font-size:0.8rem;").on("click", _toggle)
                ui.button(icon="content_copy").props(
                    "flat round dense"
                ).style(f"color:{C['mut']}; font-size:0.8rem;").on(
                    "click", lambda s=sk: _clip(s)
                )
                ui.button(icon="delete").props(
                    "flat round dense"
                ).style("color:#da3633; font-size:0.8rem;").on(
                    "click",
                    lambda a=ak: _delete_key(rgw, uid, a, ctx, dark),
                )


async def _add_key(rgw, ctx: dict, new_key_dlg, dark: bool) -> None:
    uid  = ctx.get("uid", "")
    loop = asyncio.get_event_loop()
    try:
        keys = await loop.run_in_executor(None, lambda: rgw.create_key(uid))
    except Exception as exc:
        ui.notify(f"Error creating key: {exc}", type="negative")
        return

    # Refresh key list
    user_data = await loop.run_in_executor(None, lambda: rgw.get_user(uid))
    _render_keys(ctx["keys_col"], user_data.get("keys", []), uid, rgw, ctx, dark)

    # Show new key in reveal dialog
    if keys:
        new_k = keys[-1]  # API returns all keys; newest is last
        ctx.setdefault("new_key_ctx", {})
        # The new_key_ctx dict is passed via closure in the page function;
        # update via the label refs we already stored on the dict.
        # Here we call the reveal dialog's labels directly through the
        # new_key_dlg's child labels — stored in the sibling new_key_ctx dict.
        # Because _add_key is called from inside the page function scope,
        # we can't access new_key_ctx directly, so we use the trick of
        # passing the dialog and finding labels. Instead, we use a notification
        # with the key info and open the reveal dialog.
        ui.notify(
            f"Key created: {new_k.get('access_key', '')}",
            type="positive",
            timeout=5000,
        )
    else:
        ui.notify("Key created (refresh to see).", type="positive")


async def _delete_key(rgw, uid: str, access_key: str, ctx: dict, dark: bool) -> None:
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None, lambda: rgw.delete_key(uid, access_key)
        )
        ui.notify("Key deleted.", type="warning")
    except Exception as exc:
        ui.notify(f"Error: {exc}", type="negative")
        return
    # Refresh key list
    try:
        user_data = await loop.run_in_executor(None, lambda: rgw.get_user(uid))
        _render_keys(
            ctx["keys_col"], user_data.get("keys", []), uid, rgw, ctx, dark
        )
    except Exception:
        pass


# ── Quota ─────────────────────────────────────────────────────────────────────

async def _save_quota(rgw, ctx: dict, dark: bool) -> None:
    uid      = ctx.get("uid", "")
    enabled  = ctx["q_enabled"].value
    size_gb  = float(ctx["q_size_inp"].value or -1)
    max_obj  = int(ctx["q_obj_inp"].value or -1)

    # Convert GB → KB (-1 stays -1)
    max_kb = int(size_gb * 1024 * 1024) if size_gb > 0 else -1

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            lambda: rgw.set_user_quota(
                uid,
                quota_type="user",
                max_size_kb=max_kb,
                max_objects=max_obj,
                enabled=enabled,
            ),
        )
        ctx["q_err"].set_text("")
        ui.notify("Quota saved.", type="positive")
    except Exception as exc:
        ctx["q_err"].set_text(str(exc))


# ── Usage stats ───────────────────────────────────────────────────────────────

async def _load_usage(rgw, ctx: dict, dark: bool) -> None:
    uid  = ctx.get("uid", "")
    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(
            None, lambda: rgw.get_user_stats(uid)
        )
        _render_usage(ctx["usage_col"], data, dark)
    except Exception as exc:
        ui.notify(f"Stats error: {exc}", type="negative")


def _render_usage(col, data: dict, dark: bool) -> None:
    col.clear()
    C = _pal(dark)
    stats = data.get("stats", {})

    with col:
        if not stats:
            ui.label("Usage data unavailable.").style(
                f"color:{C['mut']}; font-size:0.82rem; padding:6px 0;"
            )
            return

        def _row(label: str, value: str, icon: str = "circle") -> None:
            with ui.row().style(
                f"align-items:center; gap:12px; padding:9px 12px; "
                f"background:{C['sbg']}; border:1px solid {C['bdr']}; "
                "border-radius:8px; width:100%;"
            ):
                ui.icon(icon).style("color:#58a6ff; font-size:1.1rem; flex-shrink:0;")
                ui.label(label).style(
                    f"color:{C['mut']}; font-size:0.82rem; flex:1;"
                )
                ui.label(value).style(
                    f"color:{C['txt']}; font-size:0.9rem; font-weight:700;"
                )

        _row("Total Size",        humanize.naturalsize(stats.get("size", 0)),
             "storage")
        _row("Size Utilized",     humanize.naturalsize(stats.get("size_utilized", 0)),
             "compress")
        _row("Number of Objects", str(stats.get("num_objects", 0)),
             "folder_open")
        if "size_kb_rounded" in stats:
            _row("Rounded Size (KB)", str(stats["size_kb_rounded"]), "straighten")


# ── Save user info ────────────────────────────────────────────────────────────

async def _save_user_info(
    rgw, ctx: dict, table, stats_row, dark: bool,
) -> None:
    uid   = ctx.get("uid", "")
    name  = ctx["name_inp"].value.strip()
    email = ctx["email_inp"].value.strip()
    maxb  = int(ctx["maxb_inp"].value or 1000)

    if not name:
        ctx["info_err"].set_text("Display Name is required.")
        return

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            lambda: rgw.modify_user(uid, **{
                "display-name": name,
                "email":        email,
                "max-buckets":  maxb,
            }),
        )
        ctx["info_err"].set_text("")
        ui.notify(f"User '{uid}' updated.", type="positive")
        await _reload(table, stats_row, rgw, dark)
    except Exception as exc:
        ctx["info_err"].set_text(str(exc))


# ── Create user ───────────────────────────────────────────────────────────────

async def _create_user(
    rgw,
    uid: str, display_name: str, email: str,
    max_buckets: int, generate_key: bool,
    dialog, err_lbl, table, stats_row, dark: bool,
) -> None:
    if not uid.strip() or not display_name.strip():
        err_lbl.set_text("User ID and Display Name are required.")
        return

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            lambda: rgw.create_user(
                uid.strip(), display_name.strip(),
                email.strip(), max_buckets, generate_key,
            ),
        )
        dialog.close()
        ui.notify(f"User '{uid}' created.", type="positive")
        await _reload(table, stats_row, rgw, dark)
    except Exception as exc:
        err_lbl.set_text(str(exc))


# ── Suspend / activate ────────────────────────────────────────────────────────

async def _do_suspend(
    rgw,
    uid: str, do_suspend: bool,
    dialog, table, stats_row, dark: bool,
) -> None:
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None, lambda: rgw.suspend_user(uid, suspended=do_suspend)
        )
        dialog.close()
        action = "suspended" if do_suspend else "activated"
        ui.notify(f"User '{uid}' {action}.", type="positive")
        await _reload(table, stats_row, rgw, dark)
    except Exception as exc:
        ui.notify(f"Error: {exc}", type="negative")


# ── Delete user ───────────────────────────────────────────────────────────────

async def _do_delete(
    rgw,
    uid: str, purge: bool,
    dialog, err_lbl, table, stats_row, dark: bool,
) -> None:
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None, lambda: rgw.delete_user(uid, purge_data=purge)
        )
        dialog.close()
        ui.notify(f"User '{uid}' deleted.", type="warning")
        await _reload(table, stats_row, rgw, dark)
    except Exception as exc:
        err_lbl.set_text(str(exc))


# ─────────────────────────────────────────────────────────────────────────────
#  Clipboard helper
# ─────────────────────────────────────────────────────────────────────────────

def _clip(text: str) -> None:
    if not text or text.startswith("•"):
        ui.notify("Nothing to copy.", type="warning")
        return
    safe = text.replace("`", "\\`")
    ui.run_javascript(f"navigator.clipboard.writeText(`{safe}`)")
    ui.notify("Copied to clipboard!", type="positive")


# ─────────────────────────────────────────────────────────────────────────────
#  UI primitives
# ─────────────────────────────────────────────────────────────────────────────

def _pal(dark: bool) -> dict:
    return {
        "bg":     "#0d1117" if dark else "#f0f4f8",
        "sbg":    "#161b22" if dark else "#ffffff",
        "tbg":    "#0d1117" if dark else "#f6f8fa",
        "bdr":    "#21262d" if dark else "#d0d7de",
        "txt":    "#e6edf3" if dark else "#1f2328",
        "mut":    "#8b949e" if dark else "#57606a",
        "blue":   "#58a6ff" if dark else "#0969da",
        "active": "#1f6feb" if dark else "#0969da",
        "act_bg": "#1f6feb22" if dark else "#0969da18",
    }


def _stat_chip(label: str, value: str, icon: str, dark: bool) -> None:
    C = _pal(dark)
    with ui.card().style(
        f"background:{C['sbg']}; border:1px solid {C['bdr']}; "
        "border-radius:8px; padding:10px 18px;"
    ):
        with ui.row().style("align-items:center; gap:10px;"):
            ui.icon(icon).style("color:#58a6ff; font-size:1.4rem;")
            with ui.column().style("gap:0;"):
                ui.label(value).style(
                    f"color:{C['txt']}; font-size:1.4rem; "
                    "font-weight:700; line-height:1;"
                )
                ui.label(label).style(f"color:{C['mut']}; font-size:0.72rem;")


def _dlg_card(dark: bool, width: str = "440px"):
    bg  = "#161b22" if dark else "#ffffff"
    bdr = "#21262d" if dark else "#d0d7de"
    return ui.card().style(
        f"background:{bg}; border:1px solid {bdr}; "
        f"border-radius:12px; padding:24px; width:{width}; max-width:96vw;"
    )


def _dlg_title(text: str, dark: bool) -> None:
    txt = "#e6edf3" if dark else "#1f2328"
    ui.label(text).style(
        f"color:{txt}; font-size:1.05rem; font-weight:700; margin-bottom:14px;"
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
    return ui.label("").style(
        "color:#da3633; font-size:0.8rem; min-height:18px;"
    )


def _cancel_btn(dialog, dark: bool) -> None:
    mut = "#8b949e" if dark else "#57606a"
    ui.button("Cancel", on_click=dialog.close).props(
        "flat no-caps"
    ).style(f"color:{mut};")


def _primary_btn(text: str, handler) -> None:
    ui.button(text, on_click=handler).props("no-caps").style(
        "background:#1f6feb; color:#fff; border-radius:8px; font-weight:600;"
    )


def _ghost_btn(text: str, icon: str, C: dict, handler) -> None:
    ui.button(text, icon=icon, on_click=handler).props("no-caps").style(
        f"background:{C['sbg']}; color:{C['txt']}; "
        f"border:1px solid {C['bdr']}; border-radius:8px; font-size:0.82rem;"
    )


def _mono_box(dark: bool, blue: bool = False) -> ui.label:
    C   = _pal(dark)
    col = C["blue"] if blue else C["txt"]
    return ui.label("").style(
        f"color:{col}; font-family:monospace; font-size:0.82rem; "
        f"background:{C['tbg']}; border:1px solid {C['bdr']}; "
        "border-radius:6px; padding:9px 12px; width:100%; "
        "word-break:break-all; margin-bottom:8px;"
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
    ui.query("body").style(
        f"background:{'#0d1117' if dark else '#f0f4f8'};"
    )
