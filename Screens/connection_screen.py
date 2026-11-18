from __future__ import annotations

import sqlite3

import flet as ft

from Utils.api import Api, ApiError
from Utils.settings import save_server
from .onboarding_screen import onboarding
from .queue_screen import sync_bookings
from .ui_components import AMBER, MUTED, panel, show_dialog


def login(app, message=""):
    app.page.clean()
    app.page.appbar = None
    name = ft.TextField(label="Benutzername")
    password = ft.TextField(label="Passwort", password=True, can_reveal_password=True)
    feedback = ft.Text(message, color=ft.Colors.ERROR, visible=bool(message))

    async def sign_in(_):
        if button.disabled or app.closing_window:
            return
        app.busy = True
        button.disabled = True
        app.page.update()
        try:
            app.api = Api(app.server_url)
            session = await app.call("login", username=name.value, password=password.value)
            app.api.token = session["token"]
            try:
                data = await app.call("state")
            except ApiError:
                try:
                    await app.call("logout")
                except ApiError:
                    pass
                raise
            app.session_expired = False
            app.data = data
            app.admin = session["role"] == "admin"
            app.screen = 0
            app.category = None
            app.username = session["username"]
            app.display_username = session.get("display_username", app.username)
            try:
                app.load_pending()
            except (OSError, sqlite3.Error):
                app.pending_bookings = []
            app.render()
            app.heartbeat = app.page.run_task(app.keep_alive, app.api)
            try:
                save_server(app.api.server)
            except OSError:
                app.notify("Die Serveradresse konnte lokal nicht gespeichert werden.")
        except (ApiError, ValueError) as error:
            app.api = None
            feedback.value = str(error)
            feedback.visible = True
            button.disabled = False
            app.page.update()
        finally:
            app.busy = False
        if app.api and app.pending_bookings:
            await sync_bookings(app)
        if app.api and app.data.get("onboarding_pending"):
            onboarding(app, automatic=True)

    button = ft.FilledButton("Anmelden", on_click=sign_in)
    password.on_submit = sign_in
    login_card = panel(ft.ResponsiveRow([
        ft.Column([
            ft.Icon(ft.Icons.POINT_OF_SALE, size=28, color=AMBER),
            ft.Text("CashApp", size=32, weight=ft.FontWeight.BOLD),
            ft.Text("Personal-Login", color=MUTED),
            ft.Text(app.server_url, color=MUTED, selectable=True, size=12),
        ], col={"xs": 12, "sm": 5}, spacing=8),
        ft.Column(
            [name, password, feedback, button],
            col={"xs": 12, "sm": 7}, spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
    ], spacing=24, run_spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER), padding=18)
    centered = ft.Container(content=login_card, width=680, padding=12)
    app.page.add(ft.SafeArea(ft.Column(
        [ft.Container(
            ft.Column([centered], alignment=ft.MainAxisAlignment.CENTER,
                      horizontal_alignment=ft.CrossAxisAlignment.CENTER, scroll=ft.ScrollMode.AUTO),
            expand=True, alignment=ft.Alignment.CENTER,
        )], expand=True,
    ), expand=True))


def server_settings(app):
    if not app.admin or not app.api or not app.api.token:
        return
    address = ft.TextField(label="Serveradresse", value=app.server_url, autofocus=True)
    feedback = ft.Text(color=ft.Colors.ERROR, visible=False)

    async def save(_):
        if app.busy or not app.admin or not app.api or not app.api.token:
            return
        if app.cart:
            feedback.value = "Schließe den Warenkorb ab oder leere ihn vor dem Serverwechsel."
            feedback.visible = True
            app.page.update()
            return
        app.busy = True
        save_button.disabled = cancel.disabled = True
        app.page.update()
        had_session = app.api is not None
        try:
            server = Api(address.value).server
            save_server(server)
            if had_session and server != app.server_url:
                await app.end_session(allow_unreachable=True)
            app.server_url = server
        except (ApiError, OSError, ValueError) as error:
            feedback.value = str(error) if not isinstance(error, OSError) else "Die Adresse konnte lokal nicht gespeichert werden."
            feedback.visible = True
            save_button.disabled = cancel.disabled = False
            app.page.update()
            return
        finally:
            app.busy = False
        app.page.pop_dialog()
        if app.api is None:
            login(app)

    save_button = ft.FilledButton("Speichern", on_click=save)
    cancel = ft.TextButton("Abbrechen", on_click=lambda _: app.page.pop_dialog())
    address.on_submit = save
    show_dialog(app.page, "Serververbindung", [
            address,
            ft.Text("Bei einem Serverwechsel meldest du dich am neuen Server an.", color=MUTED),
            feedback,
    ], [cancel, save_button])
