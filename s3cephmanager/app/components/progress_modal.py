"""
Reusable ProgressModal for long-running S3 operations.

Usage (inside an @ui.page function):

    modal = ProgressModal(dark)          # build DOM once at page-init

    # later, from an async handler:
    modal.open("Uploading 5 files…")
    modal.update_total(0, 5)
    modal.update_current("bigfile.mp4", pct=0.0)
    ...
    modal.update_current("bigfile.mp4", pct=72.3, speed="3.1 MB/s", eta="12s")
    modal.update_total(1, 5)
    modal.add_log_entry("bigfile.mp4", "ok", "3.1 MB")
    ...
    modal.set_done(5, 0)                 # changes Cancel → Close
"""
from __future__ import annotations
from nicegui import ui


class ProgressModal:
    """Floating progress dialog.  Must be instantiated during page setup."""

    # ── Constructor ──────────────────────────────────────────────────────────
    def __init__(self, dark: bool) -> None:
        self.dark       = dark
        self._cancelled = False
        self._done      = False   # True after set_done() — makes button act as Close

        bg  = "#161b22" if dark else "#ffffff"
        bdr = "#21262d" if dark else "#d0d7de"
        txt = "#e6edf3" if dark else "#1f2328"
        mut = "#8b949e" if dark else "#57606a"
        lbg = "#0d1117" if dark else "#f6f8fa"

        with ui.dialog().props("persistent") as self._dlg:
            with ui.card().style(
                f"background:{bg}; border:1px solid {bdr}; border-radius:14px; "
                "padding:28px; width:540px; max-width:96vw; gap:0;"
            ):
                # ── Title ──────────────────────────────────────────────────
                with ui.row().style(
                    "align-items:center; justify-content:space-between; "
                    "width:100%; margin-bottom:20px;"
                ):
                    self._title = ui.label("").style(
                        f"color:{txt}; font-size:1.05rem; font-weight:700;"
                    )
                    self._status_icon = ui.label("").style(
                        "font-size:1.1rem;"
                    )

                # ── Overall progress ───────────────────────────────────────
                ui.label("OVERALL").style(
                    f"color:{mut}; font-size:0.62rem; font-weight:700; "
                    "letter-spacing:0.1em; margin-bottom:5px;"
                )
                self._total_bar = ui.linear_progress(value=0).props(
                    "rounded color=blue-4 track-color=blue-1"
                ).style("height:8px; margin-bottom:4px;")
                self._total_lbl = ui.label("").style(
                    f"color:{mut}; font-size:0.75rem; margin-bottom:16px;"
                )

                # ── Current-file progress ──────────────────────────────────
                self._cur_wrap = ui.column().style("width:100%; gap:4px; margin-bottom:4px;")
                with self._cur_wrap:
                    self._cur_name = ui.label("").style(
                        f"color:{txt}; font-size:0.85rem; font-weight:600; "
                        "overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
                    )
                    self._cur_bar = ui.linear_progress(value=0).props(
                        "rounded color=green-5 track-color=green-1"
                    ).style("height:6px;")
                    with ui.row().style(
                        "align-items:center; justify-content:space-between;"
                    ):
                        self._cur_pct   = ui.label("0%").style(
                            f"color:{mut}; font-size:0.72rem;"
                        )
                        self._speed_lbl = ui.label("").style(
                            f"color:{mut}; font-size:0.72rem;"
                        )

                ui.separator().style(f"border-color:{bdr}; margin:14px 0 10px;")

                # ── Log ───────────────────────────────────────────────────
                ui.label("LOG").style(
                    f"color:{mut}; font-size:0.62rem; font-weight:700; "
                    "letter-spacing:0.1em; margin-bottom:6px;"
                )
                self._log = ui.column().style(
                    f"gap:2px; max-height:200px; overflow-y:auto; width:100%; "
                    f"background:{lbg}; border:1px solid {bdr}; "
                    "border-radius:8px; padding:8px 10px;"
                )

                # ── Footer: cancel + close ────────────────────────────────
                with ui.row().style(
                    "justify-content:flex-end; gap:8px; margin-top:18px;"
                ):
                    self._extra_btn = ui.button("").props("flat no-caps").style(
                        "display:none;"   # hidden unless set_done is called
                    )
                    self._cancel_btn = ui.button(
                        "Cancel", on_click=self._do_cancel
                    ).props("no-caps").style(
                        "background:#da363322; color:#da3633; "
                        "border:1px solid #da363344; border-radius:8px;"
                    )

    # ── Public API ────────────────────────────────────────────────────────────

    def open(self, title: str) -> None:
        """Reset state and open the modal."""
        self._cancelled  = False
        self._done       = False
        self._title.set_text(title)
        self._status_icon.set_text("⏳")
        self._total_bar.set_value(0)
        self._total_lbl.set_text("")
        self._cur_bar.set_value(0)
        self._cur_name.set_text("")
        self._cur_pct.set_text("0%")
        self._speed_lbl.set_text("")
        self._log.clear()
        self._cancel_btn.set_text("Cancel")
        self._cancel_btn.style(
            "background:#da363322; color:#da3633; "
            "border:1px solid #da363344; border-radius:8px;"
        )
        self._extra_btn.style("display:none;")
        self._dlg.open()

    def close(self) -> None:
        self._dlg.close()

    def update_total(self, done: int, total: int) -> None:
        """Update the overall progress bar."""
        pct = done / total if total else 0.0
        self._total_bar.set_value(pct)
        self._total_lbl.set_text(
            f"{done} / {total} files  ({int(pct * 100)}%)"
        )

    def update_current(
        self,
        name:  str,
        pct:   float,
        speed: str = "",
        eta:   str = "",
    ) -> None:
        """Update the current-file progress row."""
        self._cur_name.set_text(name)
        self._cur_bar.set_value(max(0.0, min(pct / 100, 1.0)))
        self._cur_pct.set_text(f"{int(pct)}%")
        parts = []
        if speed:
            parts.append(speed)
        if eta and eta not in ("—", "done"):
            parts.append(f"ETA {eta}")
        self._speed_lbl.set_text("  ".join(parts))

    def add_log_entry(
        self,
        name:   str,
        status: str,          # "ok" | "error" | "skip" | "info"
        detail: str = "",
    ) -> None:
        """Append a single entry to the scrollable log."""
        _COL = {"ok": "#2ea043", "error": "#da3633",
                "skip": "#8b949e", "info": "#58a6ff"}
        _ICO = {"ok": "✓", "error": "✗", "skip": "—", "info": "ℹ"}
        col  = _COL.get(status, "#8b949e")
        ico  = _ICO.get(status, "•")
        txt  = "#e6edf3" if self.dark else "#1f2328"
        mut  = "#8b949e" if self.dark else "#57606a"

        with self._log:
            with ui.row().style(
                "align-items:baseline; gap:6px; width:100%; "
                "padding:2px 0; border-bottom:1px solid "
                + ("#21262d33" if self.dark else "#d0d7de44") + ";"
            ):
                ui.label(ico).style(
                    f"color:{col}; font-size:0.82rem; width:14px; flex-shrink:0;"
                )
                ui.label(name).style(
                    f"color:{txt}; font-size:0.78rem; flex:1; "
                    "overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
                )
                if detail:
                    ui.label(detail).style(
                        f"color:{mut}; font-size:0.72rem; flex-shrink:0;"
                    )

    def set_done(self, ok: int, errors: int) -> None:
        """Called when all work is finished — swap Cancel for Close."""
        total = ok + errors
        ico   = "✅" if not errors else "⚠️"
        self._status_icon.set_text(ico)
        # Final total bar
        self._total_bar.set_value(1.0)
        self._total_lbl.set_text(
            f"Done — {ok}/{total} succeeded"
            + (f", {errors} failed" if errors else "")
        )
        self._cur_name.set_text("")
        self._cur_bar.set_value(0)
        self._cur_pct.set_text("")
        self._speed_lbl.set_text("")
        # Change button to Close — _do_cancel checks _done and closes instead
        self._done = True
        self._cancel_btn.set_text("Close")
        self._cancel_btn.style(
            "background:#1f6feb22; color:#58a6ff; "
            "border:1px solid #1f6feb44; border-radius:8px;"
        )

    def set_title(self, title: str) -> None:
        self._title.set_text(title)

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    # ── Internal ──────────────────────────────────────────────────────────────

    def _do_cancel(self) -> None:
        # After upload is done this button acts as "Close"
        if self._done:
            self._dlg.close()
            return
        self._cancelled = True
        self._cancel_btn.set_text("Cancelling…")
        self._cancel_btn.style(
            "background:#8b949e22; color:#8b949e; "
            "border:1px solid #8b949e44; border-radius:8px;"
        )
        self.add_log_entry("User requested cancel", "info")
