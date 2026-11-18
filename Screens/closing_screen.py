from __future__ import annotations

import flet as ft

from Utils.formatting import euro
from .dialogs import form
from .settings_screen import deletion_dialog
from .ui_components import AMBER, MUTED, entry_row, panel


def closing(app):
    day = app.data["day"]
    totals = app.data["totals"]
    controls = [
        ft.Text(f"Heute · {day}", color=MUTED),
        ft.ResponsiveRow([
            panel(ft.Column([
                ft.Text(label, color=MUTED),
                ft.Text(euro(totals[key]), size=23, weight=ft.FontWeight.BOLD, color=AMBER),
            ]), col={"xs": 12, "sm": 6, "md": 4})
            for label, key in [("Verkäufe", "sales"), ("Bargeld-Soll", "cash"), ("Offene Deckel", "outstanding")]
        ], spacing=12, run_spacing=12),
    ]
    previous_days = [row for row in app.data.get("daily_totals", []) if row["day"] != day]
    if previous_days:
        controls.append(ft.Text("Vorherige Tage", size=20))
    for row in previous_days:
        controls.append(ft.ListTile(
            title=ft.Text(row["day"]),
            subtitle=ft.Text(f"Verkäufe {euro(row['sales'])} · Bargeld {euro(row['cash'])}"),
        ))
    controls.append(ft.Text("Letzte Buchungen", size=20))
    reversed_ids = {e["reversed_id"] for e in app.data["entries"] if e["reversed_id"]}
    for entry in app.data["entries"]:
        can_reverse = app.admin and entry["kind"] != "reversal" and entry["id"] not in reversed_ids
        buttons = []
        if can_reverse:
            buttons.append(ft.IconButton(ft.Icons.UNDO, tooltip="Stornieren",
                on_click=lambda _, e=entry: reverse(app, e)))
        if app.admin:
            buttons.append(ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="Buchung löschen",
                on_click=lambda _, e=entry: deletion_dialog(app, single=True, entry_id=e["id"])))
        actions = ft.Row(buttons, tight=True, spacing=0) if buttons else None
        controls.append(entry_row(entry, actions))
    return controls


def reverse(app, entry):
    reason = ft.TextField(label="Stornogrund", max_length=160)
    form(app, f"Storno zu #{entry['id']}", [reason],
              lambda: ("reversal", {"entry_id": entry["id"], "reason": reason.value}), booking=True)
