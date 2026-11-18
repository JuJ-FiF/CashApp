import json
import sqlite3
from datetime import datetime

import flet as ft

from Utils.api import ApiError
from Utils.formatting import euro
from .ui_components import MUTED, show_dialog


async def sync_bookings(app, *, just_queued=False):
    if app.busy or not app.api or app.closing_window:
        return
    app.busy = True
    confirmed = []
    message = ""
    try:
        app.load_pending()
        app.update_queue_button()
        for booking in app.pending_bookings:
            if booking["rejection"] or app.closing_window or not app.api:
                break
            try:
                result = await app.call(booking["action"], **json.loads(booking["payload"]))
                if not isinstance(result, dict) or (
                    type(result.get("id")) is not int
                    or result.get("kind") != booking["action"]
                    or type(result.get("cents")) is not int
                    or "received" not in result
                ):
                    raise ApiError("Buchungsbestätigung fehlt.")
            except ApiError as error:
                if error.status == 401:
                    app.session_expired = True
                    message = "Kassensitzung abgelaufen. Melde dich in der Buchungswarteschlange erneut an."
                elif error.booking_rejected:
                    app.booking_queue.reject(booking["request_id"], str(error))
                    message = f"Buchung muss geprüft werden. {error}"
                elif just_queued:
                    message = "Buchung lokal gespeichert. Serverbestätigung steht aus."
                break
            app.booking_queue.confirm(booking["request_id"])
            confirmed.append(result)
        if app.api:
            app.load_pending()
        if confirmed and app.api and not app.closing_window:
            try:
                app.data = await app.call("state")
            except ApiError:
                message = message or "Buchung bestätigt. Übersicht konnte nicht geladen werden."
        if just_queued and app.pending_bookings and not message:
            message = "Buchung lokal gespeichert. Prüfe die Warteschlange."
    except (OSError, sqlite3.Error) as error:
        message = f"Die lokale Buchungswarteschlange konnte nicht aktualisiert werden. {error}"
    finally:
        app.busy = False
    if not app.api or app.closing_window:
        return
    app.update_queue_button()
    if confirmed:
        app.render()
        if not message and len(confirmed) == 1:
            result = confirmed[0]
            message = f"Buchung #{result['id']} bestätigt."
            if result["received"] is not None:
                message += f" Rückgeld {euro(int(result['received']) - int(result['cents']))}."
        elif not message:
            message = f"{len(confirmed)} ausstehende Buchungen bestätigt."
    if message:
        app.notify(message)


def queue_screen(app):
    if app.busy:
        return
    try:
        app.load_pending()
    except (OSError, sqlite3.Error):
        app.notify("Die lokale Buchungswarteschlange kann nicht gelesen werden.")
        return

    async def retry(_):
        head = app.pending_bookings[0] if app.pending_bookings else None
        if head and head["rejection"]:
            try:
                app.booking_queue.retry_rejection(head["request_id"])
            except (OSError, sqlite3.Error):
                app.notify("Die Buchung konnte nicht erneut in die Warteschlange gelegt werden.")
                return
        app.page.pop_dialog()
        await sync_bookings(app, just_queued=True)

    def archive(booking):
        def confirm(_):
            try:
                app.booking_queue.archive_rejection(booking["request_id"])
                app.load_pending()
            except (OSError, sqlite3.Error):
                app.notify("Die Buchung konnte nicht archiviert werden.")
                return
            app.page.pop_dialog()
            app.update_queue_button()
            queue_screen(app)

        app.page.pop_dialog()
        show_dialog(app.page, "Abgelehnte Buchung archivieren", [
            ft.Text("Die Buchung bleibt lokal dokumentiert. Sie wird danach nicht mehr automatisch gesendet."),
        ], [
            ft.TextButton("Abbrechen", on_click=lambda _: app.page.pop_dialog()),
            ft.FilledButton("Archivieren", on_click=confirm),
        ])

    fields = []
    for booking in app.pending_bookings:
        payload = json.loads(booking["payload"])
        when = datetime.fromtimestamp(payload["booking_time"]).strftime("%d.%m.%Y %H:%M") if "booking_time" in payload else payload.get("booking_day", "")
        detail = [f"Erfasst {when}"]
        if payload.get("items"):
            products = {p["id"]: p["name"] for p in app.data["products"]}
            detail.extend(f"{item['quantity']} × {products.get(item['id'], '#' + str(item['id']))}"
                          for item in payload["items"])
        detail.append(booking["rejection"] or "Wartet auf Serverbestätigung")
        fields.append(ft.ListTile(
            title=ft.Text(booking["title"]),
            subtitle=ft.Text(" · ".join(detail), color=MUTED),
            trailing=ft.IconButton(ft.Icons.ARCHIVE_OUTLINED, tooltip="Ablehnung archivieren",
                                   on_click=lambda _, row=booking: archive(row)) if booking["rejection"] else None,
        ))
    actions = [ft.TextButton("Schließen", on_click=lambda _: app.page.pop_dialog())]
    if app.session_expired:
        fields.insert(0, ft.Text("Die Kassensitzung ist abgelaufen. Melde dich mit demselben Konto erneut an.", color=MUTED))
        actions.append(ft.FilledButton("Erneut anmelden", on_click=lambda _: renew_session(app)))
    elif app.pending_bookings:
        head = app.pending_bookings[0]
        if not head["rejection"] or "daily_totals" in app.data:
            actions.append(ft.FilledButton("Jetzt senden", on_click=retry))
    show_dialog(app.page, "Buchungswarteschlange",
                fields or [ft.Text("Keine ausstehenden Buchungen.")], actions)


def renew_session(app):
    if app.busy:
        return
    app.page.pop_dialog()
    password = ft.TextField(label="Passwort", password=True, can_reveal_password=True)
    feedback = ft.Text(color=ft.Colors.ERROR, visible=False)

    async def sign_in(_):
        if app.busy or not app.api:
            return
        app.busy = True
        confirm.disabled = cancel.disabled = True
        feedback.visible = False
        app.page.update()
        try:
            session = await app.call("login", username=app.username, password=password.value)
        except ApiError as error:
            feedback.value = str(error)
            feedback.visible = True
            confirm.disabled = cancel.disabled = False
            app.page.update()
            return
        finally:
            app.busy = False
        app.api.token = session["token"]
        app.session_expired = False
        if app.heartbeat:
            app.heartbeat.cancel()
        app.heartbeat = app.page.run_task(app.keep_alive, app.api)
        app.page.pop_dialog()
        await sync_bookings(app, just_queued=bool(app.pending_bookings))

    confirm = ft.FilledButton("Anmelden", on_click=sign_in)
    cancel = ft.TextButton("Abbrechen", on_click=lambda _: app.page.pop_dialog())
    password.on_submit = sign_in
    show_dialog(app.page, f"Kassensitzung · {app.display_username}", [password, feedback], [cancel, confirm])
