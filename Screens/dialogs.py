from __future__ import annotations

import sqlite3
from time import time
from uuid import uuid4

import flet as ft

from Utils.api import ApiError
from .queue_screen import sync_bookings
from .ui_components import show_dialog


def form(app, title, fields, submit, *, booking=False, training_target=None):
    feedback = ft.Text(color=ft.Colors.ERROR, visible=False)

    async def save(_):
        if app.busy:
            return
        if app.training:
            try:
                app.training.booked(*submit())
            except ValueError as error:
                feedback.visible = True
                feedback.value = str(error)
                app.page.update()
            return
        app.busy = True
        confirm.disabled = True
        cancel.disabled = True
        app.page.update()
        try:
            action, data = submit()
            if booking:
                data["request_id"] = uuid4().hex
                data["booking_time"] = int(time())
                app.booking_queue.add(app.api.server, app.username, title, action, data)
            else:
                await app.call(action, **data)
        except (ValueError, ApiError, sqlite3.Error, OSError) as error:
            feedback.visible = True
            if isinstance(error, ApiError) and error.status == 401:
                feedback.value = f"{error} Verwende die Sitzungsanmeldung unten."
                unlock.visible = True
            elif isinstance(error, (sqlite3.Error, OSError)):
                feedback.value = "Buchung konnte auf diesem Gerät nicht gesichert werden. Bitte Speicher prüfen."
            else:
                feedback.value = str(error)
            cancel.disabled = False
            confirm.disabled = False
            app.page.update()
            return
        finally:
            app.busy = False
        if action in ("sale", "charge"):
            app.cart.clear()
        app.page.pop_dialog()
        if booking:
            app.render()
            await sync_bookings(app, just_queued=True)
            return
        try:
            app.data = await app.call("state")
        except ApiError as error:
            app.notify(f"Aktion gespeichert. Übersicht konnte nicht geladen werden. {error}")
            app.render()
            return
        app.render()

    unlock_password = ft.TextField(label="Passwort für die Kassensitzung", password=True)

    async def unlock_session(_):
        if app.busy:
            return
        app.busy = True
        try:
            session = await app.call("login", username=app.username, password=unlock_password.value)
            app.api.token = session["token"]
            app.session_expired = False
            if app.heartbeat:
                app.heartbeat.cancel()
            app.heartbeat = app.page.run_task(app.keep_alive, app.api)
            unlock.visible = False
            unlock_password.value = ""
            feedback.value = "Sitzung wieder aktiv. Du kannst die Aktion erneut senden."
        except ApiError as error:
            feedback.value = str(error)
        finally:
            app.busy = False
            app.page.update()

    unlock = ft.Column(
        [unlock_password, ft.TextButton("Sitzung erneut anmelden", on_click=unlock_session)],
        visible=False,
    )
    confirm = ft.FilledButton("Bestätigen", on_click=save)
    cancel = ft.TextButton("Abbrechen", on_click=lambda _: app.page.pop_dialog())
    confirm_action = app.training.highlight(training_target, confirm) if training_target else confirm
    show_dialog(app.page, title, [*fields, feedback, unlock], [cancel, confirm_action])
