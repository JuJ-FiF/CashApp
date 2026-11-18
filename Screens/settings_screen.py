from datetime import date

import flet as ft

from Utils.api import ApiError
from Utils.formatting import euro, local_time
from Utils.settings import load_settings, save_settings
from .connection_screen import server_settings
from .dialogs import form
from .onboarding_screen import onboarding
from .update_screen import AppUpdates
from .ui_components import LABELS, MUTED, panel, show_dialog


def settings(app):
    def update(key, value):
        try:
            save_settings({**load_settings(), key: value})
        except OSError:
            app.notify("Die Einstellung konnte lokal nicht gespeichert werden.")
            app.render()
            return
        app.preferences[key] = value

    controls = [
        panel(ft.Column([
            ft.Dropdown(
                label="Artikelkacheln", value=app.preferences.get("tile_size", "normal"),
                options=[ft.dropdown.Option(key=key, text=label) for key, label in
                         [("small", "Kompakt"), ("normal", "Standard"), ("large", "Groß")]],
                expanded_insets=ft.Padding.all(0),
                on_select=lambda e: update("tile_size", e.control.value),
            ),
            ft.Switch(label="Ausgeglichene Deckel anzeigen", value=app.preferences.get("show_settled_tabs", True),
                      on_change=lambda e: update("show_settled_tabs", e.control.value)),
        ])),
        panel(ft.ListTile(
            leading=ft.Icon(ft.Icons.SCHOOL_OUTLINED),
            title=ft.Text("Einweisung"),
            on_click=lambda _: onboarding(app),
        ), padding=4),
    ]
    if app.admin:
        controls.insert(0, panel(ft.ListTile(
            leading=ft.Icon(ft.Icons.DNS_OUTLINED),
            title=ft.Text("Serververbindung"),
            subtitle=ft.Text(app.server_url),
            on_click=lambda _: server_settings(app),
        ), padding=4))
        controls.append(panel(ft.Column([
            ft.Text("Administration", size=19, weight=ft.FontWeight.BOLD),
            ft.OutlinedButton("Buchungen im Zeitraum löschen", icon=ft.Icons.DELETE_OUTLINE,
                              on_click=lambda _: deletion_dialog(app)),
            ft.OutlinedButton("Einzelne Buchung löschen", icon=ft.Icons.DELETE_OUTLINE,
                              on_click=lambda _: deletion_dialog(app, single=True)),
            *[ft.Text(f"{row['from_day']} bis {row['to_day']} · {row['entry_count']} gelöscht · "
                      f"{local_time(row['created_at'])} · {row['username']}", color=MUTED)
              for row in app.data.get("booking_deletions", [])],
        ])))
    controls.append(AppUpdates(app).build())
    return controls


def deletion_dialog(app, *, single=False, entry_id=None):
    today = app.data["day"]
    start = ft.TextField(label="Von", value=today, hint_text="JJJJ-MM-TT")
    end = ft.TextField(label="Bis einschließlich", value=today, hint_text="JJJJ-MM-TT")
    number = ft.TextField(label="Buchungsnummer", value=str(entry_id or ""), hint_text="z. B. #42")
    feedback = ft.Text(color=ft.Colors.ERROR, visible=False)

    async def preview(_):
        if app.busy:
            return
        if app.pending_bookings:
            feedback.value = "Klär zuerst die ausstehenden Buchungen in der Warteschlange."
            feedback.visible = True
            app.page.update()
            return
        app.busy = True
        cancel.disabled = review.disabled = True
        app.page.update()
        try:
            if single:
                key = (number.value or "").strip().removeprefix("#")
                if not key.isascii() or not key.isdigit() or int(key) < 1:
                    raise ValueError()
                params = {"entry_id": int(key)}
            else:
                params = {"from_day": (start.value or "").strip(), "to_day": (end.value or "").strip()}
                for value in params.values():
                    if date.fromisoformat(value).isoformat() != value:
                        raise ValueError()
            result = await app.call("preview_booking_deletion", **params)
        except (ApiError, ValueError) as error:
            feedback.value = str(error) if isinstance(error, ApiError) else (
                "Gib eine gültige Buchungsnummer ein." if single else "Gib das Datum als JJJJ-MM-TT ein."
            )
            feedback.visible = True
            cancel.disabled = review.disabled = False
            app.page.update()
            return
        finally:
            app.busy = False
        app.page.pop_dialog()
        if result["count"] == 0:
            show_dialog(app.page, "Keine passenden Buchungen", [
                ft.Text(f"{params['from_day']} bis {params['to_day']}"),
            ], [ft.TextButton("Schließen", on_click=lambda _: app.page.pop_dialog())])
            return
        confirm_deletion(app, params, result)

    cancel = ft.TextButton("Abbrechen", on_click=lambda _: app.page.pop_dialog())
    review = ft.FilledButton("Vorschau anzeigen", on_click=preview)
    fields = [number] if single else [
        ft.Text("Gib den ersten und letzten Buchungstag ein. Beide Tage zählen mit.", color=MUTED), start, end,
    ]
    show_dialog(app.page, "Einzelne Buchung löschen" if single else "Buchungen im Zeitraum löschen",
                [*fields, feedback], [cancel, review])


def confirm_deletion(app, params, preview):
    confirmation = ft.TextField(label="LÖSCHEN eingeben")

    def submit():
        if (confirmation.value or "").strip().upper() != "LÖSCHEN":
            raise ValueError("Gib LÖSCHEN ein, um die Auswahl zu bestätigen.")
        return "delete_bookings", {**params, "token": preview["token"], "confirmation": "LÖSCHEN"}

    if "entry_id" in params:
        summary = [
            ft.Text(f"#{row['id']} · {LABELS[row['kind']]} · {euro(row['cents'])} · {row['day']}")
            for row in preview["bookings"]
        ]
        if len(summary) > 1:
            summary.insert(0, ft.Text("Buchung und Storno werden gemeinsam gelöscht."))
    else:
        summary = [
            ft.Text(f"{params['from_day']} bis {params['to_day']} · {preview['count']} Buchungen"),
            ft.Text("\n".join(f"{LABELS[kind]}: {count}" for kind, count in preview["kinds"].items())),
        ]
    form(app, "Buchungen dauerhaft löschen", [
        *summary,
        ft.Text("Die ausgewählten Buchungen und ihre Artikelpositionen werden aus der Datenbank gelöscht. "
                "Tagessummen und Deckelsalden ändern sich entsprechend."),
        confirmation,
    ], submit)
