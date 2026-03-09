"""
Object Explorer  –  full operations edition
============================================

Layout
──────
  Left  240 px  │  Folder-tree panel (collapsible prefixes)
  Right  flex   │  Breadcrumb + toolbar + object table

Object table features
─────────────────────
  • ".." row at the top when inside a sub-prefix  (go-up navigation)
  • Folder rows  → click to descend
  • File  rows   → checkbox multi-select
  • Per-row actions: Download · Copy · Rename · Presigned URL · Delete

Toolbar
───────
  Upload ▼ (menu: Files / Upload to Folder)
  Download Selected
  Copy Selected
  Delete Selected
  New Folder
  Search

Dialogs
───────
  1. Upload Files     – multi-file drop zone, per-file progress via ProgressModal
  2. Upload to Folder – same but with explicit sub-prefix input
  3. Download (multi) – presigned URLs, opened via JS window.open
  4. Copy             – copy selected objects to a destination prefix
  5. Rename           – rename/move a single object
  6. Presigned URL    – configurable expiry, clipboard copy
  7. New Folder       – creates a zero-byte placeholder key
  8. Delete (folder)  – confirm + recursive delete via ProgressModal
"""
from __future__ import annotations

import asyncio
import io
import uuid as _uuid
from fastapi import Response as _FastAPIResponse
from nicegui import ui, app, events

from app.components.sidebar       import create_layout, require_connection
from app.components.progress_modal import ProgressModal
from app.s3_client                 import get_s3_from_conn, ProgressCallback
import humanize


# ─────────────────────────────────────────────────────────────────────────────
#  Preview proxy – same-origin FastAPI endpoint to serve S3 content in iframes
#  (browsers block cross-origin S3 presigned URLs inside <iframe> / <object>)
# ─────────────────────────────────────────────────────────────────────────────

_preview_tokens: dict[str, dict] = {}   # token → {"url": str, "ct": str}
_MAX_PREVIEW_TOKENS = 200


def _register_preview_token(
    presigned_url: str,
    content_type: str = "application/octet-stream",
) -> str:
    """Store a presigned URL + forced content-type under a random token; return the token."""
    token = _uuid.uuid4().hex
    if len(_preview_tokens) >= _MAX_PREVIEW_TOKENS:
        # Evict oldest entry to keep memory bounded
        _preview_tokens.pop(next(iter(_preview_tokens)), None)
    _preview_tokens[token] = {"url": presigned_url, "ct": content_type}
    return token


@app.get("/api/preview/{token}")
async def _preview_proxy_route(token: str):
    """Proxy S3 presigned content through our server (same origin → no CORS / X-Frame issues).
    Uses the content-type stored at token-registration time so the browser always
    receives the correct MIME type even when Ceph/S3 returns 'application/octet-stream'.
    """
    import requests as _req
    entry = _preview_tokens.get(token)
    if not entry:
        return _FastAPIResponse(status_code=404, content=b"Preview not found or expired.")
    purl     = entry["url"]
    forced_ct = entry["ct"]
    loop = asyncio.get_event_loop()
    try:
        r = await loop.run_in_executor(
            None, lambda: _req.get(purl, timeout=60, verify=False)
        )
        r.raise_for_status()
        return _FastAPIResponse(
            content=r.content,
            media_type=forced_ct,          # ← always use our stored type, not Ceph's
            headers={"Content-Disposition": "inline", "Cache-Control": "no-store"},
        )
    except Exception as exc:
        return _FastAPIResponse(status_code=502, content=str(exc).encode())


# ─────────────────────────────────────────────────────────────────────────────
#  Page entry-point
# ─────────────────────────────────────────────────────────────────────────────

@ui.page("/objects")
async def objects_page() -> None:
    create_layout(current_path="/objects")
    dark   = app.storage.user.get("dark_mode", True)
    _body_bg(dark)

    conn = require_connection()
    if not conn:
        return

    bucket = app.storage.user.get("active_bucket", "")
    if not bucket:
        ui.navigate.to("/buckets")
        return

    s3 = get_s3_from_conn(conn)
    settings = app.storage.user.get("settings") or {}
    page_size = int(settings.get("page_size", 200))
    state: dict = {
        "prefix":        app.storage.user.get("active_prefix", ""),
        "selected":      [],    # list[str] – currently selected object keys
        "next_token":    None,  # continuation token for pagination
        "load_more_ref": None,  # set after widget is created
        "page_size":     page_size,
        "all_rows":      [],    # full row snapshot used by live search
    }

    # Palette
    C = _pal(dark)

    # ── ProgressModal (created once, shared by all operations) ────────────────
    modal = ProgressModal(dark)

    # Mutable state for folder-tree toggle (captured by closures below)
    _ui_state: dict = {"tree_open": True}

    # ── Outer wrapper (fills viewport below header) ───────────────────────────
    with ui.row().style(
        f"width:100%; height:calc(100vh - 56px); gap:0; padding:0; "
        f"background:{C['bg']}; align-items:stretch; overflow:hidden;"
    ):

        # ── LEFT  Folder-tree panel ───────────────────────────────────────────
        # min-height:0 is required so that as a flex-child it can shrink below
        # its content height and let overflow-y:auto trigger a scrollbar.
        left_panel = ui.column().style(
            f"width:240px; min-width:240px; background:{C['sbg']}; "
            f"border-right:1px solid {C['bdr']}; padding:10px 0; "
            "overflow-y:auto; flex-shrink:0; min-height:0; gap:0;"
        )
        with left_panel:
            ui.label("FOLDERS").style(
                f"color:{C['mut']}; font-size:0.6rem; font-weight:700; "
                "letter-spacing:0.12em; padding:4px 16px 8px;"
            )
            tree_list = ui.column().style("gap:1px; width:100%;")

        # ── RIGHT  Main panel ─────────────────────────────────────────────────
        # min-height:0 + overflow-y:auto = the right column scrolls when
        # content exceeds the flex-container height (calc(100vh - 56px)).
        with ui.column().style(
            "flex:1; min-width:0; min-height:0; padding:18px 22px; gap:12px; "
            "overflow-y:auto;"
        ):

            # Top bar
            with ui.row().style(
                "align-items:center; justify-content:space-between; width:100%;"
            ):
                with ui.row().style("align-items:center; gap:8px;"):
                    ui.button(
                        icon="arrow_back",
                        on_click=lambda: ui.navigate.to("/buckets"),
                    ).props("flat round").style(f"color:{C['mut']};")
                    # ── Folder-tree toggle ─────────────────────────────────
                    # Clicking shows/hides the 240 px left panel, giving the
                    # table more horizontal space on smaller screens.
                    # _toggle_tree_panel() is defined below (helper closures).
                    tree_toggle = ui.button(
                        icon="menu_open",
                        on_click=lambda: _toggle_tree_panel(),
                    ).props("flat round").style(f"color:{C['mut']};")
                    ui.tooltip("Toggle folder tree")
                    # ───────────────────────────────────────────────────────
                    ui.icon("dns").style(
                        f"color:{C['blue']}; font-size:1.15rem;"
                    )
                    ui.label(bucket).style(
                        f"color:{C['txt']}; font-size:1.15rem; font-weight:700;"
                    )

                with ui.row().style("gap:6px; align-items:center;"):
                    search = ui.input(placeholder="Search…").props(
                        "dense outlined dark" if dark else "dense outlined"
                    ).style(_inp(dark) + "width:200px;")
                    search.on("input",
                              lambda e: _apply_search(table, state,
                                                      e.sender.value or ""))
                    ui.button(
                        icon="refresh",
                        on_click=lambda: _reload(table, tree_list, brow, s3, bucket, state, dark),
                    ).props("flat round").style(f"color:{C['mut']};")

            # Breadcrumb (re-rendered on every navigate)
            brow = ui.row().style("align-items:center; gap:2px; flex-wrap:wrap;")

            # ── Toolbar ───────────────────────────────────────────────────────
            with ui.row().style(
                f"align-items:center; gap:6px; flex-wrap:wrap; "
                f"background:{C['sbg']}; border:1px solid {C['bdr']}; "
                "border-radius:8px; padding:8px 12px;"
            ):
                # Upload split-button
                with ui.button_group().props("flat"):
                    ui.button(
                        "Upload", icon="upload",
                        on_click=lambda: upload_dlg.open(),
                    ).props("no-caps").style(
                        "background:#1f6feb; color:#fff; "
                        "border-radius:6px 0 0 6px; padding:5px 12px; "
                        "font-size:0.82rem;"
                    )
                    ui.button(icon="expand_more").props("no-caps").style(
                        "background:#1a5fd4; color:#fff; "
                        "border-radius:0 6px 6px 0; padding:5px 8px;"
                    ).on("click", lambda: folder_upload_dlg.open())

                _tb_btn("download", "Download",
                        lambda: _download_selected(s3, bucket, state, dark), C)
                _tb_btn("content_copy", "Copy",
                        lambda: _open_copy_dlg(
                            copy_dlg, copy_dst_inp, copy_err, state, C
                        ), C)
                _tb_btn("delete", "Delete Selected",
                        lambda: _bulk_delete(s3, bucket, state, modal,
                                             table, tree_list, brow, dark), C, danger=True)
                _tb_btn("create_new_folder", "New Folder",
                        lambda: folder_dlg.open(), C)
                _tb_btn("swap_horiz", "Copy to Bucket",
                        lambda: _open_xbucket_dlg(
                            xbucket_dlg, xb_bucket_sel, xb_prefix_inp,
                            xb_info, xb_err, state, s3, conn,
                        ), C)

            # ── Object table ──────────────────────────────────────────────────
            columns = [
                {"name": "icon",  "label": "",         "field": "type",  "align": "left"},
                {"name": "name",  "label": "Name",      "field": "name",
                 "align": "left",  "sortable": True},
                {"name": "size",  "label": "Size",      "field": "size",
                 "align": "right", "sortable": True},
                {"name": "mtime", "label": "Modified",  "field": "mtime",
                 "align": "left",  "sortable": True},
                {"name": "acts",  "label": "",          "field": "key",   "align": "right"},
            ]
            table = ui.table(
                columns=columns,
                rows=[],
                row_key="key",
                selection="multiple",
                pagination={"rowsPerPage": 25, "sortBy": "name"},
                # Keep Python-side pagination in sync so table.update() after
                # search/reload doesn't reset the user's chosen rows-per-page.
                # NiceGUI fires on_pagination_change as ValueChangeEventArguments
                # → new value is in e.value (not e.args).
                on_pagination_change=lambda e: (
                    table._props.update({"pagination": e.value})
                    if isinstance(e.value, dict) else None
                ),
            ).style(
                f"background:{C['tbg']}; border:1px solid {C['bdr']}; "
                "border-radius:10px; width:100%;"
            ).props(
                ('flat dark' if dark else 'flat') +
                ' :rows-per-page-options="[10,25,50,100]"'
            )

            # ── Slots ──────────────────────────────────────────────────────────

            # Icon column
            table.add_slot("body-cell-icon", r"""
                <q-td :props="props" style="width:30px; padding:0 0 0 12px;">
                  <q-icon
                    :name="props.row.type === 'up'     ? 'arrow_upward'       :
                           props.row.type === 'folder' ? 'folder'             :
                                                         'insert_drive_file'"
                    :style="props.row.type === 'up'     ? 'color:#58a6ff' :
                            props.row.type === 'folder' ? 'color:#d29922' :
                                                          'color:#8b949e'"
                    style="font-size:1.05rem;"
                  />
                </q-td>
            """)

            # Name column  (folder/.. = navigate link, file = plain text)
            table.add_slot("body-cell-name", r"""
                <q-td :props="props">
                  <span
                    :style="props.row.type !== 'file'
                      ? 'color:#58a6ff; font-weight:600; cursor:pointer; font-size:0.87rem;'
                      : 'color:#e6edf3; font-size:0.87rem;'"
                    @click="props.row.type !== 'file'
                      ? $parent.$emit('navigate', props.row)
                      : null"
                  >{{ props.value }}</span>
                </q-td>
            """)

            # Actions column  (hidden for ".." row)
            table.add_slot("body-cell-acts", r"""
                <q-td :props="props" style="text-align:right; white-space:nowrap; padding-right:8px;">
                  <template v-if="props.row.type === 'file'">
                    <q-btn flat dense round icon="visibility" color="green-4" size="xs"
                           @click="$parent.$emit('preview', props.row)"><q-tooltip>Preview</q-tooltip></q-btn>
                    <q-btn flat dense round icon="download" color="blue-4"   size="xs"
                           @click="$parent.$emit('dl',      props.row)"><q-tooltip>Download</q-tooltip></q-btn>
                    <q-btn flat dense round icon="content_copy" color="teal-4" size="xs"
                           @click="$parent.$emit('copy_one',props.row)"><q-tooltip>Copy</q-tooltip></q-btn>
                    <q-btn flat dense round icon="edit"     color="orange-4" size="xs"
                           @click="$parent.$emit('rename',  props.row)"><q-tooltip>Rename / Move</q-tooltip></q-btn>
                    <q-btn flat dense round icon="link"     color="purple-4" size="xs"
                           @click="$parent.$emit('presign', props.row)"><q-tooltip>Presigned URL</q-tooltip></q-btn>
                  </template>
                  <template v-if="props.row.type === 'folder'">
                    <q-btn flat dense round icon="content_copy" color="teal-4" size="xs"
                           @click="$parent.$emit('copy_folder', props.row)"><q-tooltip>Copy folder</q-tooltip></q-btn>
                  </template>
                  <template v-if="props.row.type !== 'up'">
                    <q-btn flat dense round icon="delete"   color="red-4"    size="xs"
                           @click="$parent.$emit('del_one', props.row)"><q-tooltip>Delete</q-tooltip></q-btn>
                  </template>
                </q-td>
            """)

            # Modified-date column – formatted client-side (browser local timezone)
            table.add_slot("body-cell-mtime", r"""
                <q-td :props="props" style="white-space:nowrap; font-size:0.83rem;">
                  {{ props.row.mtime > 0
                      ? new Date(props.row.mtime).toLocaleString([], {
                            year:'numeric', month:'2-digit', day:'2-digit',
                            hour:'2-digit', minute:'2-digit'})
                      : '—' }}
                </q-td>
            """)

            # Wire table events
            table.on("navigate",
                     lambda e: _navigate(e.args.get("key", ""),
                                         table, tree_list, brow, s3, bucket, state, dark))
            table.on("dl",
                     lambda e: _download_one(s3, bucket, e.args.get("key", "")))
            table.on("copy_one",
                     lambda e: _open_copy_dlg(copy_dlg, copy_dst_inp, copy_err,
                                              state, C, single_key=e.args.get("key", "")))
            table.on("copy_folder",
                     lambda e: _open_copy_dlg(copy_dlg, copy_dst_inp, copy_err,
                                              state, C, single_key=e.args.get("key", "")))
            table.on("rename",
                     lambda e: _pre_rename(e.args, rename_dlg, rename_src, rename_inp))
            table.on("presign",
                     lambda e: _pre_presign(e.args, presign_dlg, presign_key, presign_url))
            table.on("del_one",
                     lambda e: _delete_one(s3, bucket, e.args, modal,
                                           table, tree_list, brow, state, dark))
            table.on("preview",
                     lambda e: _pre_preview(e.args))
            table.on("selection",
                     lambda e: state.update(
                         {"selected": [r["key"] for r in e.args.get("rows", [])
                                       if r.get("type") == "file"]}
                     ))

            # ── Load More button (shown only when results are truncated) ───────
            # NOTE: .set_visibility() returns None in NiceGUI 3.x — must not chain
            load_more_row = ui.row().style(
                "justify-content:center; width:100%; padding:8px 0;"
            )
            load_more_row.set_visibility(False)
            state["load_more_ref"] = load_more_row
            with load_more_row:
                ui.button(
                    "Load More", icon="expand_more",
                    on_click=lambda: _load_more(table, tree_list, brow, load_more_row,
                                               s3, bucket, state, dark, state["page_size"]),
                ).props("no-caps flat").style(
                    f"color:{C['blue']}; border:1px solid {C['bdr']}; "
                    "border-radius:8px; font-size:0.82rem;"
                )

    # ═══════════════════════════════════════════════════════════════════════════
    #  DIALOGS
    # ═══════════════════════════════════════════════════════════════════════════

    # ── 1. Upload Files ────────────────────────────────────────────────────────
    with ui.dialog() as upload_dlg, _dlg_card(dark, width="560px"):
        _dlg_title("Upload Files", dark)
        ui.label(
            "Drag & drop or click to select — uploaded to the current folder."
        ).style(f"color:{C['mut']}; font-size:0.8rem; margin-bottom:10px;")

        # per-file status list (populated dynamically)
        up_list = ui.column().style(
            f"gap:4px; max-height:220px; overflow-y:auto; width:100%; "
            f"background:{C['tbg']}; border:1px solid {C['bdr']}; "
            "border-radius:8px; padding:8px; margin-bottom:8px;"
        )
        up_list_placeholder = ui.label("No files queued yet.").style(
            f"color:{C['mut']}; font-size:0.78rem;"
        )
        with up_list:
            pass   # populated on upload

        # NiceGUI 3.x: on_multi_upload fires once with ALL files in the correct
        # slot context – no need for debounce queue or asyncio.ensure_future.
        async def _on_multi_upload(e):
            await _handle_upload(e.files, s3, bucket, state, modal,
                                 up_list, up_list_placeholder,
                                 table, tree_list, brow, dark)

        upload_widget = ui.upload(
            multiple=True,
            auto_upload=True,
            on_multi_upload=_on_multi_upload,
        ).props(
            f"dark color={'blue-6' if dark else 'primary'} flat "
            "label='Drop files here or click to browse'"
        ).style("width:100%;")
        upload_widget.on("rejected", lambda _: ui.notify(
            "Some files were rejected (size limit?)", type="warning"
        ))

        with ui.row().style("justify-content:flex-end; margin-top:10px;"):
            ui.button("Close", on_click=upload_dlg.close).props("flat no-caps").style(
                f"color:{C['mut']};"
            )

    # ── 2. Upload to Folder  (with custom destination prefix) ─────────────────
    with ui.dialog() as folder_upload_dlg, _dlg_card(dark, width="560px"):
        _dlg_title("Upload to Folder", dark)
        ui.label(
            "Files will be placed inside the sub-folder you specify below."
        ).style(f"color:{C['mut']}; font-size:0.8rem; margin-bottom:12px;")

        fup_prefix_inp = _dlg_input("Destination sub-folder", "images/2025/", dark)
        fup_list = ui.column().style(
            f"gap:4px; max-height:180px; overflow-y:auto; width:100%; "
            f"background:{C['tbg']}; border:1px solid {C['bdr']}; "
            "border-radius:8px; padding:8px; margin-bottom:8px;"
        )
        fup_placeholder = ui.label("No files queued yet.").style(
            f"color:{C['mut']}; font-size:0.78rem;"
        )
        with fup_list:
            pass

        # NiceGUI 3.x: on_multi_upload fires once with ALL files in the correct
        # slot context – no need for debounce queue or asyncio.ensure_future.
        async def _on_fup_multi_upload(e):
            dst = {**state,
                   "prefix": state["prefix"] + (fup_prefix_inp.value or "")}
            await _handle_upload(e.files, s3, bucket, dst, modal,
                                 fup_list, fup_placeholder,
                                 table, tree_list, brow, dark)

        fup_widget = ui.upload(
            multiple=True,
            auto_upload=True,
            on_multi_upload=_on_fup_multi_upload,
        ).props(
            f"dark color={'blue-6' if dark else 'primary'} flat "
            "label='Drop files here or click to browse'"
        ).style("width:100%;")

        with ui.row().style("justify-content:flex-end; margin-top:10px;"):
            ui.button("Close", on_click=folder_upload_dlg.close).props("flat no-caps").style(
                f"color:{C['mut']};"
            )

    # ── 3. New Folder ──────────────────────────────────────────────────────────
    with ui.dialog() as folder_dlg, _dlg_card(dark):
        _dlg_title("New Folder", dark)
        folder_inp = _dlg_input("Folder name", "my-folder", dark)
        folder_err = _dlg_err()
        with ui.row().style("justify-content:flex-end; gap:8px; margin-top:12px;"):
            _cancel_btn(folder_dlg, dark)
            _primary_btn("Create", lambda: _create_folder(s3, bucket, state, folder_inp.value,
                                                           folder_dlg, folder_err,
                                                           table, tree_list, brow, dark))

    # ── 4. Rename / Move ───────────────────────────────────────────────────────
    with ui.dialog() as rename_dlg, _dlg_card(dark):
        _dlg_title("Rename / Move", dark)
        rename_src = ui.label("").style(
            f"color:{C['mut']}; font-size:0.78rem; margin-bottom:10px; "
            "word-break:break-all;"
        )
        rename_inp = _dlg_input("New key (full path)", "", dark)
        rename_err = _dlg_err()
        with ui.row().style("justify-content:flex-end; gap:8px; margin-top:12px;"):
            _cancel_btn(rename_dlg, dark)
            _primary_btn("Rename", lambda: _rename(s3, bucket, state, rename_src.text, rename_inp.value,
                                                    rename_dlg, rename_err, modal,
                                                    table, tree_list, brow, dark))

    # ── 5. Copy ────────────────────────────────────────────────────────────────
    _copy_keys: list[str] = []   # mutable cell for lambda capture

    with ui.dialog() as copy_dlg, _dlg_card(dark):
        _dlg_title("Copy Objects", dark)
        copy_info = ui.label("").style(
            f"color:{C['mut']}; font-size:0.8rem; margin-bottom:10px;"
        )
        copy_dst_inp = _dlg_input(
            "Destination prefix (within same bucket)",
            "backup/folder/", dark,
        )
        copy_err = _dlg_err()
        with ui.row().style("justify-content:flex-end; gap:8px; margin-top:12px;"):
            _cancel_btn(copy_dlg, dark)
            _primary_btn("Copy", lambda: _copy_objects(s3, bucket, _copy_keys,
                                                        copy_dst_inp.value, copy_dlg, copy_err,
                                                        modal, table, tree_list, brow, state, dark))

    # ── 6. Cross-bucket copy ───────────────────────────────────────────────────
    _xb_keys: list[str] = []

    with ui.dialog() as xbucket_dlg, _dlg_card(dark, width="520px"):
        _dlg_title("Copy to Another Bucket", dark)
        xb_info = ui.label("").style(
            f"color:{C['mut']}; font-size:0.8rem; margin-bottom:10px;"
        )
        xb_bucket_sel = ui.select(
            options=[], label="Destination Bucket",
        ).props("dense outlined dark" if dark else "dense outlined").style(
            f"background:{'#0d1117' if dark else '#f6f8fa'}; "
            f"color:{'#e6edf3' if dark else '#1f2328'}; width:100%; margin-bottom:10px;"
        )
        xb_prefix_inp = _dlg_input("Destination prefix (optional)", "", dark)
        xb_err = _dlg_err()
        with ui.row().style("justify-content:flex-end; gap:8px; margin-top:12px;"):
            _cancel_btn(xbucket_dlg, dark)
            _primary_btn("Copy", lambda: _xbucket_copy(
                s3, bucket, _xb_keys,
                xb_bucket_sel.value or "",
                xb_prefix_inp.value or "",
                xbucket_dlg, xb_err, modal, dark,
            ))

    # ── 7. Presigned URL ───────────────────────────────────────────────────────
    with ui.dialog() as presign_dlg, _dlg_card(dark, width="500px"):
        _dlg_title("Presigned URL", dark)
        presign_key = ui.label("").style(
            f"color:{C['mut']}; font-size:0.78rem; margin-bottom:10px; "
            "word-break:break-all;"
        )
        expiry_inp = ui.number(
            "Expiry (seconds)", value=3600, min=60, max=604800
        ).props("dense outlined dark" if dark else "dense outlined").style(
            _inp(dark) + "width:100%; margin-bottom:8px;"
        )
        presign_url = ui.label("").style(
            f"color:{C['blue']}; font-size:0.74rem; word-break:break-all; "
            f"background:{C['tbg']}; border:1px solid {C['bdr']}; "
            "border-radius:6px; padding:10px; min-height:42px; "
            "font-family:monospace;"
        )
        with ui.row().style(
            "justify-content:space-between; align-items:center; margin-top:12px;"
        ):
            with ui.row().style("gap:8px;"):
                _primary_btn("Generate", lambda: _gen_presign(
                    s3, bucket, presign_key.text,
                    int(expiry_inp.value or 3600), presign_url
                ))
                ui.button("Copy URL", icon="content_copy").props(
                    "no-caps"
                ).style(
                    f"background:{C['sbg']}; color:{C['txt']}; "
                    f"border:1px solid {C['bdr']}; border-radius:8px;"
                ).on("click", lambda: _clipboard_copy(presign_url.text))
            _cancel_btn(presign_dlg, dark)

    # ── 8. Preview ─────────────────────────────────────────────────────────────
    preview_ctx: dict = {"key": ""}   # mutable cell shared with _pre_preview

    with ui.dialog() as preview_dlg, _dlg_card(dark, width="900px"):
        with ui.row().style(
            "align-items:center; width:100%; gap:10px; margin-bottom:12px;"
        ):
            ui.icon("visibility").style(f"color:{C['blue']}; font-size:1.2rem;")
            preview_title_lbl = ui.label("Preview").style(
                f"color:{C['txt']}; font-size:1rem; font-weight:700; flex:1;"
            )
            ui.button(icon="close", on_click=preview_dlg.close).props(
                "flat round dense"
            ).style(f"color:{C['mut']};")

        preview_content_col = ui.column().style("width:100%; gap:4px; min-height:120px;")

        with ui.row().style(
            "justify-content:space-between; align-items:center; margin-top:14px;"
        ):
            ui.button("Download", icon="download").props("no-caps").style(
                "background:#1f6feb; color:#fff; border-radius:8px; font-weight:600;"
            ).on("click", lambda: _download_one(s3, bucket, preview_ctx["key"]))
            ui.button("Close", on_click=preview_dlg.close).props("flat no-caps").style(
                f"color:{C['mut']};"
            )

    # ═══════════════════════════════════════════════════════════════════════════
    #  Helper closures that need dialog references
    # ═══════════════════════════════════════════════════════════════════════════

    def _toggle_tree_panel() -> None:
        """Show / hide the left folder-tree panel to reclaim horizontal space."""
        _ui_state["tree_open"] = not _ui_state["tree_open"]
        is_open = _ui_state["tree_open"]
        left_panel.set_visibility(is_open)
        # Swap the button icon so it reflects current state
        tree_toggle._props["icon"] = "menu_open" if is_open else "menu"
        tree_toggle.update()

    def _open_copy_dlg(dlg, dst_inp, err, st, palette,
                       single_key: str = "") -> None:
        nonlocal _copy_keys
        if single_key:
            _copy_keys = [single_key]
        else:
            _copy_keys = list(st.get("selected", []))
        if not _copy_keys:
            ui.notify("Nothing selected to copy.", type="warning")
            return
        copy_info.set_text(
            f"{len(_copy_keys)} object(s) will be copied → new destination."
        )
        dst_inp.set_value(st["prefix"])
        err.set_text("")
        dlg.open()

    async def _open_xbucket_dlg(
        dlg, bucket_sel, prefix_inp, info_lbl, err_lbl, st, s3_ref, conn_ref,
    ) -> None:
        nonlocal _xb_keys
        _xb_keys = list(st.get("selected", []))
        if not _xb_keys:
            ui.notify("Select files first.", type="warning")
            return
        info_lbl.set_text(f"{len(_xb_keys)} object(s) → another bucket.")
        prefix_inp.set_value("")
        err_lbl.set_text("")
        # Populate bucket list
        loop = asyncio.get_event_loop()
        try:
            buckets = await loop.run_in_executor(None, s3_ref.list_buckets)
            bucket_names = [b["Name"] for b in buckets if b["Name"] != bucket]
            bucket_sel.set_options(bucket_names)
            if bucket_names:
                bucket_sel.set_value(bucket_names[0])
        except Exception as exc:
            err_lbl.set_text(f"Could not list buckets: {exc}")
        dlg.open()

    def _pre_preview(row: dict) -> None:
        """Open the preview dialog for the given file row."""
        key = row.get("key", "")
        if not key:
            return
        preview_ctx["key"] = key
        preview_title_lbl.set_text(key.rsplit("/", 1)[-1] or key)
        preview_content_col.clear()
        preview_dlg.open()
        asyncio.ensure_future(
            _show_preview(s3, bucket, key, preview_content_col, dark)
        )

    # ── Keyboard shortcuts ────────────────────────────────────────────────────
    def _on_key(e: events.KeyEventArguments) -> None:
        if e.action.keydown and not e.modifiers.ctrl and not e.modifiers.alt:
            key = e.key.name
            if key == "u" or key == "U":
                upload_dlg.open()
            elif key == "n" or key == "N":
                folder_dlg.open()
            elif key == "r" or key == "R":
                asyncio.ensure_future(
                    _reload(table, tree_list, brow, s3, bucket, state, dark)
                )
            elif key == "Escape":
                for dlg in (upload_dlg, folder_upload_dlg, copy_dlg,
                            rename_dlg, presign_dlg, folder_dlg, xbucket_dlg,
                            preview_dlg):
                    dlg.close()

    ui.keyboard(on_key=_on_key, ignore=[])

    # ── Initial load ──────────────────────────────────────────────────────────
    await _reload(table, tree_list, brow, s3, bucket, state, dark)


# ═════════════════════════════════════════════════════════════════════════════
#  Navigation + data loading
# ═════════════════════════════════════════════════════════════════════════════

def _apply_search(table, state: dict, query: str) -> None:
    """Filter table rows in-place by name query (live search, no network call)."""
    q = query.strip().lower()
    all_rows = state.get("all_rows", [])
    if q:
        # Always keep the ".." navigation row at the top; filter everything else
        nav   = [r for r in all_rows if r["type"] == "up"]
        rest  = [r for r in all_rows if r["type"] != "up"
                 and q in r["name"].lower()]
        visible = nav + rest
    else:
        visible = list(all_rows)
    table.rows.clear()
    table.rows.extend(visible)
    table.update()


async def _reload(
    table, tree_list, brow,
    s3, bucket: str, state: dict, dark: bool,
) -> None:
    state["next_token"] = None  # reset pagination on full reload
    page_size = state.get("page_size", 200)
    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(
            None, lambda: s3.list_objects(
                bucket, prefix=state["prefix"], max_keys=page_size,
            )
        )
    except Exception as exc:
        ui.notify(f"Error listing objects: {exc}", type="negative")
        return

    state["next_token"] = data.get("next_token")

    rows: list[dict] = []

    # ".." row when inside a sub-prefix
    if state["prefix"]:
        parent = "/".join(state["prefix"].rstrip("/").split("/")[:-1])
        if parent:
            parent += "/"
        rows.append({
            "key":   parent,
            "type":  "up",
            "name":  "..",
            "size":  "",
            "mtime": 0,
        })

    # Folder rows
    for pref in data["prefixes"]:
        name = pref[len(state["prefix"]):]
        rows.append({"key": pref, "type": "folder",
                     "name": name, "size": "—", "mtime": 0})

    # File rows
    for obj in data["objects"]:
        key  = obj["Key"]
        name = key[len(state["prefix"]):]
        if not name:           # skip empty placeholder for current prefix
            continue
        lm = obj.get("LastModified")
        rows.append({
            "key":   key,
            "type":  "file",
            "name":  name,
            "size":  humanize.naturalsize(obj.get("Size", 0)),
            # epoch-ms so the JS slot can convert to browser local timezone
            "mtime": int(lm.timestamp() * 1000) if lm else 0,
        })

    state["all_rows"] = list(rows)   # snapshot for live-search filtering
    table.rows.clear()
    table.rows.extend(rows)
    table.update()

    lmr = state.get("load_more_ref")
    if lmr is not None:
        lmr.set_visibility(bool(state["next_token"]))

    _render_breadcrumb(brow, bucket, state, table, tree_list, s3, dark)
    await _render_tree(tree_list, s3, bucket, state, table, brow, dark)


async def _load_more(
    table, tree_list, brow, load_more_row,
    s3, bucket: str, state: dict, dark: bool,
    page_size: int = 200,
) -> None:
    """Append the next page of objects to the table."""
    token = state.get("next_token")
    if not token:
        load_more_row.set_visibility(False)
        return

    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(
            None, lambda: s3.list_objects(
                bucket, prefix=state["prefix"],
                max_keys=page_size,
                continuation_token=token,
            )
        )
    except Exception as exc:
        ui.notify(f"Error loading more: {exc}", type="negative")
        return

    state["next_token"] = data.get("next_token")

    # Append file rows only (folders already shown from first page)
    new_rows: list[dict] = []
    for obj in data["objects"]:
        key  = obj["Key"]
        name = key[len(state["prefix"]):]
        if not name:
            continue
        lm = obj.get("LastModified")
        new_rows.append({
            "key":   key,
            "type":  "file",
            "name":  name,
            "size":  humanize.naturalsize(obj.get("Size", 0)),
            "mtime": int(lm.timestamp() * 1000) if lm else 0,
        })

    state.setdefault("all_rows", []).extend(new_rows)  # keep snapshot in sync
    table.rows.extend(new_rows)
    table.update()
    load_more_row.set_visibility(bool(state["next_token"]))


async def _render_tree(
    tree_list, s3, bucket: str, state: dict,
    table, brow, dark: bool,
) -> None:
    """Rebuild the left-panel folder tree: root + expanded active path."""
    tree_list.clear()
    C = _pal(dark)

    async def _add_level(prefix: str, indent: int) -> None:
        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None,
                lambda: s3.list_objects(bucket, prefix=prefix, delimiter="/"),
            )
        except Exception:
            return

        for pref in data["prefixes"]:
            label   = pref[len(prefix):]
            is_cur  = state["prefix"] == pref
            bg  = C["act_bg"] if is_cur else "transparent"
            fg  = C["active"] if is_cur else C["mut"]
            bdr = f"1px solid {C['active']}44" if is_cur else "1px solid transparent"
            pl  = 16 + indent * 14

            with tree_list:
                with ui.button(
                    on_click=lambda p=pref: _navigate(
                        p, table, tree_list, brow, s3, bucket, state, dark
                    )
                ).props("flat no-caps").style(
                    f"width:100%; justify-content:flex-start; background:{bg}; "
                    f"border:{bdr}; border-radius:6px; "
                    f"padding:6px 8px 6px {pl}px; "
                    f"color:{fg}; font-size:0.8rem; transition:all 0.1s;"
                ):
                    ui.icon("folder").style(
                        "font-size:0.92rem; color:#d29922; margin-right:5px;"
                    )
                    ui.label(label.rstrip("/")).style("font-size:0.8rem;")

    await _add_level("", 0)
    if state["prefix"]:
        parts = [p for p in state["prefix"].rstrip("/").split("/") if p]
        for i in range(len(parts)):
            await _add_level("/".join(parts[: i + 1]) + "/", i + 1)


def _navigate(
    prefix: str,
    table, tree_list, brow,
    s3, bucket: str, state: dict, dark: bool,
) -> None:
    state["prefix"] = prefix
    app.storage.user["active_prefix"] = prefix
    asyncio.ensure_future(
        _reload(table, tree_list, brow, s3, bucket, state, dark)
    )


def _render_breadcrumb(
    brow, bucket: str, state: dict,
    table, tree_list, s3, dark: bool,
) -> None:
    brow.clear()
    C = _pal(dark)
    with brow:
        ui.icon("dns").style(
            f"color:{C['mut']}; font-size:0.95rem; margin-right:2px;"
        )
        ui.button(
            bucket,
            on_click=lambda: _navigate(
                "", table, tree_list, brow, s3, bucket, state, dark
            ),
        ).props("flat dense no-caps").style(
            f"color:{C['blue']}; font-size:0.8rem; font-weight:600; padding:2px 6px;"
        )
        parts = [p for p in state["prefix"].split("/") if p]
        for i, part in enumerate(parts):
            ui.label("›").style(f"color:{C['mut']}; font-size:0.85rem;")
            pref = "/".join(parts[: i + 1]) + "/"
            ui.button(
                part,
                on_click=lambda p=pref: _navigate(
                    p, table, tree_list, brow, s3, bucket, state, dark
                ),
            ).props("flat dense no-caps").style(
                f"color:{C['blue']}; font-size:0.8rem; padding:2px 6px;"
            )


# ═════════════════════════════════════════════════════════════════════════════
#  Upload
# ═════════════════════════════════════════════════════════════════════════════

async def _handle_upload(
    upload_files: list,           # list of FileUpload (NiceGUI 3.x MultiUploadEventArguments.files)
    s3, bucket: str,
    state: dict,                  # may have overridden prefix
    modal:         ProgressModal,
    up_list,                      # ui.column for per-file rows
    placeholder,                  # label to hide on first file
    table, tree_list, brow, dark: bool,
) -> None:
    """Sequentially upload one or more files with per-file progress."""
    total = len(upload_files)
    if not total:
        return

    modal.open(f"Uploading {total} file{'s' if total > 1 else ''}…")
    modal.update_total(0, total)
    ok = err = 0

    # Hide placeholder
    placeholder.set_visibility(False)

    for idx, f in enumerate(upload_files):
        if modal.cancelled:
            break

        filename  = f.name
        raw       = await f.read()
        file_size = len(raw)
        dest_key  = state["prefix"] + filename

        # Add a row to the upload list inside the dialog
        C = _pal(dark)
        with up_list:
            with ui.row().style(
                "align-items:center; gap:8px; width:100%; padding:3px 0; "
                f"border-bottom:1px solid {C['bdr']}44;"
            ):
                file_ico  = ui.icon("hourglass_empty").style(
                    "color:#8b949e; font-size:0.95rem; flex-shrink:0;"
                )
                ui.label(filename).style(
                    f"color:{C['txt']}; font-size:0.78rem; flex:1; "
                    "overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
                )
                file_pct_lbl = ui.label("0%").style(
                    f"color:{C['mut']}; font-size:0.72rem; width:32px;"
                )
                file_bar = ui.linear_progress(value=0).props(
                    "rounded color=blue-4"
                ).style("width:80px; height:4px;")

        # shared dict for thread→UI bridge
        prog: dict = {"pct": 0.0, "speed": "", "eta": ""}
        done: dict = {"ok": False, "error": ""}

        modal.update_current(filename, 0.0)

        def _cb(pct, done_s, total_s, spd, eta):
            prog.update({"pct": pct, "speed": spd, "eta": eta,
                         "done_s": done_s, "total_s": total_s})

        def _poll_upload():
            pct = prog["pct"]
            file_bar.set_value(pct / 100)
            file_pct_lbl.set_text(f"{int(pct)}%")
            modal.update_current(filename, pct, prog.get("speed", ""), prog.get("eta", ""))

        timer = ui.timer(0.12, _poll_upload)

        def _do() -> None:
            try:
                buf = io.BytesIO(raw)
                s3.upload_fileobj(
                    bucket, dest_key, buf,
                    callback=ProgressCallback(file_size, _cb),
                )
            except Exception as exc:
                done["error"] = str(exc)
            finally:
                done["ok"] = True

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do)
        timer.active = False

        if done["error"]:
            file_ico.set_name("error")
            file_ico.style("color:#da3633;")
            file_pct_lbl.set_text("✗")
            modal.add_log_entry(filename, "error", done["error"])
            err += 1
        else:
            file_ico.set_name("check_circle")
            file_ico.style("color:#2ea043;")
            file_pct_lbl.set_text("✓")
            modal.add_log_entry(
                filename, "ok",
                f"{humanize.naturalsize(file_size)}"
            )
            ok += 1

        modal.update_total(idx + 1, total)

    modal.set_done(ok, err)
    await _reload(table, tree_list, brow, s3, bucket, state, dark)


# ═════════════════════════════════════════════════════════════════════════════
#  Download
# ═════════════════════════════════════════════════════════════════════════════

def _download_one(s3, bucket: str, key: str) -> None:
    try:
        url = s3.presigned_url(bucket, key, expiry=300)
        ui.run_javascript(f"window.open({repr(url)}, '_blank')")
    except Exception as exc:
        ui.notify(f"Download error: {exc}", type="negative")


async def _download_selected(
    s3, bucket: str, state: dict, dark: bool,
) -> None:
    keys = state.get("selected", [])
    if not keys:
        ui.notify("Select files to download.", type="warning")
        return

    loop = asyncio.get_event_loop()
    try:
        urls = await loop.run_in_executor(
            None,
            lambda: [s3.presigned_url(bucket, k, expiry=300) for k in keys],
        )
    except Exception as exc:
        ui.notify(f"Error generating URLs: {exc}", type="negative")
        return

    # Open each URL in a new tab (browser may block > 1 popup — notify user)
    js = "\n".join(f"window.open({repr(u)}, '_blank');" for u in urls)
    ui.run_javascript(js)
    if len(urls) > 1:
        ui.notify(
            f"{len(urls)} downloads triggered — allow popups if blocked.",
            type="positive",
        )


# ═════════════════════════════════════════════════════════════════════════════
#  Copy
# ═════════════════════════════════════════════════════════════════════════════

async def _copy_objects(
    s3, bucket: str, keys: list[str],
    dst_prefix: str,
    dialog, err_lbl,
    modal: ProgressModal,
    table, tree_list, brow, state: dict, dark: bool,
) -> None:
    if not dst_prefix.strip():
        err_lbl.set_text("Destination prefix is required.")
        return

    dst = dst_prefix.rstrip("/") + "/"
    dialog.close()
    modal.open(f"Copying {len(keys)} object(s)…")
    modal.update_total(0, len(keys))
    ok = err = 0
    loop = asyncio.get_event_loop()

    for i, key in enumerate(keys):
        if modal.cancelled:
            break
        filename = key.split("/")[-1]
        dst_key  = dst + filename
        modal.update_current(key, 0)
        try:
            await loop.run_in_executor(
                None, lambda k=key, d=dst_key: s3.copy_object(bucket, k, bucket, d)
            )
            modal.add_log_entry(f"{key}  →  {dst_key}", "ok")
            modal.update_current(key, 100)
            ok += 1
        except Exception as exc:
            modal.add_log_entry(key, "error", str(exc))
            err += 1
        modal.update_total(i + 1, len(keys))

    modal.set_done(ok, err)
    await _reload(table, tree_list, brow, s3, bucket, state, dark)


async def _xbucket_copy(
    s3, src_bucket: str, keys: list[str],
    dst_bucket: str, dst_prefix: str,
    dialog, err_lbl,
    modal: ProgressModal, dark: bool,
) -> None:
    if not dst_bucket:
        err_lbl.set_text("Select a destination bucket.")
        return
    if dst_bucket == src_bucket:
        err_lbl.set_text("Source and destination bucket are the same. Use Copy instead.")
        return

    dst_pfx = dst_prefix.rstrip("/") + "/" if dst_prefix.strip() else ""
    dialog.close()
    modal.open(f"Copying {len(keys)} object(s) → {dst_bucket}…")
    modal.update_total(0, len(keys))
    ok = err = 0
    loop = asyncio.get_event_loop()

    for i, key in enumerate(keys):
        if modal.cancelled:
            break
        filename = key.split("/")[-1]
        dst_key  = dst_pfx + filename
        modal.update_current(key, 0)
        try:
            await loop.run_in_executor(
                None, lambda k=key, d=dst_key: s3.copy_object(src_bucket, k, dst_bucket, d)
            )
            modal.add_log_entry(f"{src_bucket}/{key}  →  {dst_bucket}/{dst_key}", "ok")
            modal.update_current(key, 100)
            ok += 1
        except Exception as exc:
            modal.add_log_entry(key, "error", str(exc))
            err += 1
        modal.update_total(i + 1, len(keys))

    modal.set_done(ok, err)


# ═════════════════════════════════════════════════════════════════════════════
#  Rename / Move
# ═════════════════════════════════════════════════════════════════════════════

async def _rename(
    s3, bucket: str, state: dict,
    old_key: str, new_key_raw: str,
    dialog, err_lbl,
    modal: ProgressModal,
    table, tree_list, brow, dark: bool,
) -> None:
    new_key = new_key_raw.strip().lstrip("/")
    if not new_key:
        err_lbl.set_text("New key is required.")
        return
    if new_key == old_key:
        err_lbl.set_text("Source and destination are identical.")
        return

    dialog.close()
    modal.open(f"Renaming…")
    modal.update_total(0, 1)
    modal.update_current(old_key, 0)

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            lambda: (
                s3.copy_object(bucket, old_key, bucket, new_key),
                s3.delete_object(bucket, old_key),
            ),
        )
        modal.update_current(old_key, 100)
        modal.add_log_entry(f"{old_key}  →  {new_key}", "ok")
        modal.update_total(1, 1)
        modal.set_done(1, 0)
    except Exception as exc:
        modal.add_log_entry(old_key, "error", str(exc))
        modal.set_done(0, 1)

    await _reload(table, tree_list, brow, s3, bucket, state, dark)


def _pre_rename(row: dict, dlg, src_lbl, inp) -> None:
    key = row.get("key", "")
    src_lbl.set_text(key)
    inp.set_value(key)
    dlg.open()


# ═════════════════════════════════════════════════════════════════════════════
#  Delete
# ═════════════════════════════════════════════════════════════════════════════

async def _delete_one(
    s3, bucket: str, row: dict,
    modal: ProgressModal,
    table, tree_list, brow, state: dict, dark: bool,
) -> None:
    key  = row.get("key", "")
    typ  = row.get("type", "file")
    loop = asyncio.get_event_loop()

    if typ == "folder":
        # Recursive folder delete with progress
        modal.open(f"Deleting folder  {key}")
        prog: dict = {"deleted": 0, "total": 0}

        def _on_prog(deleted: int, total: int) -> None:
            prog.update({"deleted": deleted, "total": total})

        def _poll_del():
            d, t = prog["deleted"], max(prog["total"], 1)
            modal.update_total(d, t)
            modal.update_current(key, d / t * 100)

        timer = ui.timer(0.2, _poll_del)
        try:
            n = await loop.run_in_executor(
                None,
                lambda: s3.delete_prefix_objects(bucket, key, on_progress=_on_prog),
            )
            timer.active = False
            modal.add_log_entry(f"{key}  ({n} objects)", "ok")
            modal.set_done(1, 0)
        except Exception as exc:
            timer.active = False
            modal.add_log_entry(key, "error", str(exc))
            modal.set_done(0, 1)
    else:
        modal.open("Deleting…")
        modal.update_total(0, 1)
        modal.update_current(key, 0)
        try:
            await loop.run_in_executor(
                None, lambda: s3.delete_object(bucket, key)
            )
            modal.add_log_entry(key, "ok")
            modal.update_total(1, 1)
            modal.set_done(1, 0)
        except Exception as exc:
            modal.add_log_entry(key, "error", str(exc))
            modal.set_done(0, 1)

    await _reload(table, tree_list, brow, s3, bucket, state, dark)


async def _bulk_delete(
    s3, bucket: str, state: dict,
    modal: ProgressModal,
    table, tree_list, brow, dark: bool,
) -> None:
    keys = state.get("selected", [])
    if not keys:
        ui.notify("No files selected.", type="warning")
        return

    modal.open(f"Deleting {len(keys)} object(s)…")
    modal.update_total(0, len(keys))
    loop = asyncio.get_event_loop()
    ok = err = 0

    # Batch in groups of 1000 (S3 delete_objects limit)
    for i in range(0, len(keys), 1000):
        if modal.cancelled:
            break
        batch = keys[i : i + 1000]
        try:
            await loop.run_in_executor(
                None, lambda b=batch: s3.delete_objects(bucket, b)
            )
            for k in batch:
                modal.add_log_entry(k.split("/")[-1], "ok")
            ok += len(batch)
        except Exception as exc:
            for k in batch:
                modal.add_log_entry(k.split("/")[-1], "error", str(exc))
            err += len(batch)
        modal.update_total(ok + err, len(keys))

    state["selected"] = []
    modal.set_done(ok, err)
    await _reload(table, tree_list, brow, s3, bucket, state, dark)


# ═════════════════════════════════════════════════════════════════════════════
#  Folder create
# ═════════════════════════════════════════════════════════════════════════════

async def _create_folder(
    s3, bucket: str, state: dict,
    name: str, dialog, err_lbl,
    table, tree_list, brow, dark: bool,
) -> None:
    if not name.strip():
        err_lbl.set_text("Folder name is required.")
        return
    key = state["prefix"] + name.strip().rstrip("/") + "/"
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: s3.upload_fileobj(bucket, key, io.BytesIO(b""))
        )
        dialog.close()
        ui.notify(f"Folder '{name}' created.", type="positive")
        await _reload(table, tree_list, brow, s3, bucket, state, dark)
    except Exception as exc:
        err_lbl.set_text(str(exc))


# ═════════════════════════════════════════════════════════════════════════════
#  Presigned URL
# ═════════════════════════════════════════════════════════════════════════════

def _pre_presign(row: dict, dlg, key_lbl, url_lbl) -> None:
    key_lbl.set_text(row.get("key", ""))
    url_lbl.set_text("")
    dlg.open()


def _gen_presign(s3, bucket: str, key: str, expiry: int, url_lbl) -> None:
    if not key:
        ui.notify("No key selected.", type="warning")
        return
    try:
        url = s3.presigned_url(bucket, key, expiry=expiry)
        url_lbl.set_text(url)
    except Exception as exc:
        ui.notify(f"Error: {exc}", type="negative")


def _clipboard_copy(text: str) -> None:
    if not text:
        ui.notify("Generate a URL first.", type="warning")
        return
    safe = text.replace("`", "\\`")
    ui.run_javascript(f"navigator.clipboard.writeText(`{safe}`)")
    ui.notify("URL copied to clipboard!", type="positive")


# ═════════════════════════════════════════════════════════════════════════════
#  Preview
# ═════════════════════════════════════════════════════════════════════════════

_PREVIEW_IMAGE_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico",
})
_PREVIEW_PDF_EXTS   = frozenset({".pdf"})
_PREVIEW_VIDEO_EXTS = frozenset({".mp4", ".webm", ".ogv", ".mov"})
_PREVIEW_AUDIO_EXTS = frozenset({".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a"})
_PREVIEW_TEXT_EXTS  = frozenset({
    ".txt", ".md", ".json", ".yaml", ".yml", ".xml", ".html", ".htm",
    ".css", ".js", ".ts", ".jsx", ".tsx", ".py", ".sh", ".bash",
    ".go", ".rs", ".java", ".c", ".cpp", ".h", ".hpp", ".rb", ".php",
    ".env", ".toml", ".ini", ".cfg", ".conf", ".log", ".csv", ".sql",
    ".tf", ".hcl", ".dockerfile", ".makefile", ".gitignore",
})


def _ext_to_lang(ext: str) -> str:
    return {
        ".py": "python",   ".js": "javascript", ".ts": "typescript",
        ".jsx": "javascript", ".tsx": "typescript",
        ".json": "json",   ".yaml": "yaml",     ".yml": "yaml",
        ".xml": "xml",     ".html": "html",     ".htm": "html",
        ".css": "css",     ".sh": "bash",       ".bash": "bash",
        ".md": "markdown", ".sql": "sql",       ".go": "go",
        ".rs": "rust",     ".java": "java",     ".c": "c",
        ".cpp": "cpp",     ".h": "c",           ".rb": "ruby",
        ".php": "php",     ".tf": "hcl",        ".toml": "toml",
    }.get(ext, "text")


async def _show_preview(
    s3, bucket: str, key: str,
    content_col, dark: bool,
) -> None:
    """Fetch and render file preview inside *content_col*."""
    import html as _html_mod
    import requests as _requests

    filename = key.rsplit("/", 1)[-1] or key
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    C   = _pal(dark)
    loop = asyncio.get_event_loop()

    # Generate an *inline* presigned URL (no Content-Disposition: attachment)
    try:
        url = await loop.run_in_executor(
            None, lambda: s3.presigned_url_inline(bucket, key, expiry=600)
        )
    except Exception as exc:
        content_col.clear()
        with content_col:
            ui.label(f"⚠ Error generating preview URL: {exc}").style(
                "color:#da3633; font-size:0.82rem;"
            )
        return

    content_col.clear()
    with content_col:

        # ── Images ────────────────────────────────────────────────────────────
        if ext in _PREVIEW_IMAGE_EXTS:
            ui.html(
                f'<div style="text-align:center; padding:8px 0;">'
                f'<img src="{url}" style="max-width:100%; max-height:66vh; '
                f'object-fit:contain; border-radius:8px; display:inline-block;">'
                f'</div>'
            )

        # ── PDF ───────────────────────────────────────────────────────────────
        elif ext in _PREVIEW_PDF_EXTS:
            # Route the presigned URL through our own FastAPI proxy so the
            # browser treats it as same-origin — avoids X-Frame-Options /
            # CSP blocks that Ceph RGW / S3 backends typically set.
            # Pass "application/pdf" explicitly so the proxy always returns the
            # correct MIME type even when Ceph responds with application/octet-stream.
            token = _register_preview_token(url, "application/pdf")
            ui.html(
                f'<iframe src="/api/preview/{token}" '
                f'style="width:100%; height:68vh; border:none; '
                f'border-radius:8px;" type="application/pdf"></iframe>'
            )

        # ── Video ─────────────────────────────────────────────────────────────
        elif ext in _PREVIEW_VIDEO_EXTS:
            ui.html(
                f'<video controls '
                f'style="width:100%; max-height:66vh; border-radius:8px; display:block;">'
                f'<source src="{url}">'
                f'Browser does not support this video format.'
                f'</video>'
            )

        # ── Audio ─────────────────────────────────────────────────────────────
        elif ext in _PREVIEW_AUDIO_EXTS:
            ui.html(
                f'<div style="padding:52px 0; text-align:center;">'
                f'<audio controls style="width:88%;">'
                f'<source src="{url}">'
                f'Browser does not support this audio format.'
                f'</audio></div>'
            )

        # ── Text / Code ───────────────────────────────────────────────────────
        elif ext in _PREVIEW_TEXT_EXTS:
            # Show spinner while fetching content server-side
            status_col = ui.column().style(
                "width:100%; align-items:center; padding:52px 0; gap:10px;"
            )
            with status_col:
                ui.spinner("dots", size="xl").style(
                    f"color:{'#58a6ff' if dark else '#0969da'};"
                )
                ui.label("Loading…").style(f"color:{C['mut']}; font-size:0.82rem;")

            try:
                resp = await loop.run_in_executor(
                    None,
                    lambda: _requests.get(url, timeout=20, verify=False),
                )
                resp.raise_for_status()
                text = resp.text
                truncated = len(text) > 300_000
                if truncated:
                    text = text[:300_000]
                status_col.clear()
                with status_col:
                    if truncated:
                        ui.label("⚠ Preview limited to first 300 KB").style(
                            "color:#d29922; font-size:0.73rem; margin-bottom:2px;"
                        )
                    # Escape HTML entities for safe rendering
                    safe = _html_mod.escape(text)
                    bdr  = "#21262d" if dark else "#d0d7de"
                    bg   = "#0d1117" if dark else "#f6f8fa"
                    txt  = "#e6edf3" if dark else "#1f2328"
                    ui.html(
                        f'<pre style="white-space:pre-wrap; word-break:break-all; '
                        f'font-family:\'JetBrains Mono\',monospace; font-size:0.76rem; '
                        f'line-height:1.5; color:{txt}; background:{bg}; '
                        f'border:1px solid {bdr}; border-radius:8px; '
                        f'padding:14px 16px; margin:0; max-height:65vh; '
                        f'overflow:auto;">{safe}</pre>'
                    )
            except Exception as exc:
                status_col.clear()
                with status_col:
                    ui.label(f"⚠ Could not fetch preview: {exc}").style(
                        "color:#da3633; font-size:0.82rem;"
                    )

        # ── Unsupported ───────────────────────────────────────────────────────
        else:
            with ui.column().style(
                "width:100%; align-items:center; padding:52px 0; gap:12px;"
            ):
                ui.icon("insert_drive_file").style(
                    f"font-size:3.5rem; color:{C['mut']};"
                )
                ui.label(
                    f"Preview not available for '{ext or 'this file type'}'"
                ).style(f"color:{C['mut']}; font-size:0.9rem;")
                ui.label("Use the Download button to open this file.").style(
                    f"color:{C['mut']}; font-size:0.78rem;"
                )


# ═════════════════════════════════════════════════════════════════════════════
#  UI primitives
# ═════════════════════════════════════════════════════════════════════════════

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


def _tb_btn(icon: str, label: str, handler,
            C: dict, danger: bool = False) -> None:
    color = "#da3633" if danger else C["txt"]
    ui.button(label, icon=icon, on_click=handler).props(
        "no-caps dense flat"
    ).style(f"color:{color}; font-size:0.82rem;")


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
