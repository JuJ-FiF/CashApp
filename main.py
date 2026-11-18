from __future__ import annotations

import asyncio
import os

import flet as ft

from Screens.closing_screen import closing
from Screens.connection_screen import login
from Screens.products_screen import products
from Screens.queue_screen import queue_screen, sync_bookings
from Screens.register_screen import register
from Screens.settings_screen import settings
from Screens.staff_screen import staff
from Screens.tabs_screen import tabs
from Screens.ui_components import AMBER, BACKGROUND, SURFACE
from Utils.api import ApiError
from Utils.booking_queue import BookingQueue
from Utils.settings import load_server, load_settings


class CashApp:
    def __init__(self, page):
        self.page = page
        self.api = None
        self.server_url = load_server(os.getenv("CASHAPP_URL") or os.getenv("TRESEN_URL") or "https://kasse.jf-homeserver.de")
        self.preferences = load_settings()
        self.screen = 0
        self.data = {}
        self.cart = {}
        self.category = None
        self.busy = False
        self.admin = False
        self.heartbeat = None
        self.booking_queue = BookingQueue()
        self.pending_bookings = []
        self.queue_button = None
        self.training = None
        self.update_running = False
        self.update_status_banner = ft.Container(
            visible=False, bgcolor=ft.Colors.GREEN_800, border_radius=12,
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        )
        self.session_expired = False
        self.closing_window = False
        self.layout = self.viewport()
        self.page.on_resize = self.resize
        self.page.on_app_lifecycle_state_change = self.lifecycle_changed
        if not page.web and page.platform in (
            ft.PagePlatform.WINDOWS, ft.PagePlatform.MACOS, ft.PagePlatform.LINUX,
        ):
            page.window.prevent_close = True
            page.window.on_event = self.window_event
        login(self)

    def viewport(self):
        width = self.page.width or 1024
        height = self.page.height or 768
        return width >= 540, width < 900 or height < 470, width >= 1150

    def resize(self, _):
        layout = self.viewport()
        if layout != self.layout and self.data:
            self.render()

    def notify(self, message):
        self.page.show_dialog(ft.SnackBar(ft.Text(message)))

    async def call(self, action, **fields):
        return await asyncio.to_thread(self.api.call, action, **fields)

    def load_pending(self):
        self.pending_bookings = self.booking_queue.pending(self.api.server, self.username)

    def update_queue_button(self):
        if self.queue_button and not self.training:
            count = len(self.pending_bookings)
            self.queue_button.badge = ft.Badge(label=str(count)) if count else None
            self.page.update()

    def can_sync_pending(self):
        return (
            self.api is not None and not self.session_expired and not self.closing_window
            and bool(self.pending_bookings) and not self.pending_bookings[0]["rejection"]
        )

    async def keep_alive(self, api):
        while self.api is api:
            await asyncio.sleep(15)
            if self.api is not api or self.session_expired:
                return
            if self.can_sync_pending() and not self.busy:
                await sync_bookings(self)
                if self.api is not api or self.session_expired:
                    return
                if self.can_sync_pending():
                    # A retry is still pending. Avoid an extra request on an unavailable connection.
                    continue
            try:
                status = await asyncio.to_thread(api.call, "ping")
            except ApiError as error:
                if error.status == 401 and self.api is api:
                    self.session_expired = True
                    self.notify("Kassensitzung abgelaufen. Melde dich über die Buchungswarteschlange erneut an.")
                    return
            else:
                if self.api is api and status and status.get("day") != self.data.get("day"):
                    await self.refresh(None)

    async def window_event(self, event):
        if event.type != ft.WindowEventType.CLOSE or self.closing_window:
            return
        self.closing_window = True
        try:
            while self.busy:
                await asyncio.sleep(0.1)
            await self.release_on_exit()
        finally:
            await self.page.window.destroy()

    async def lifecycle_changed(self, event):
        if event.state == ft.AppLifecycleState.DETACH:
            await self.release_on_exit()
        elif event.state == ft.AppLifecycleState.RESUME:
            if self.api is None and self.data:
                if self.training:
                    self.training.exit()
                self.data = {}
                login(self)
            elif self.can_sync_pending():
                await sync_bookings(self)

    async def release_on_exit(self):
        api, self.api = self.api, None
        self.admin = False
        if self.heartbeat:
            self.heartbeat.cancel()
            self.heartbeat = None
        if api and api.token:
            try:
                await asyncio.to_thread(api.call, "logout", timeout=2)
            except ApiError:
                # The server expires the lease even when the device cannot send logout.
                pass

    async def logout(self, _):
        if self.busy:
            return
        if self.cart:
            self.notify("Leere zuerst den Warenkorb oder schließe ihn ab.")
            return
        self.busy = True
        try:
            await self.end_session()
        except ApiError as error:
            self.notify(str(error))
            return
        finally:
            self.busy = False
        login(self)

    async def end_session(self, *, allow_unreachable=False):
        try:
            await self.call("logout")
        except ApiError as error:
            if error.status != 401 and not allow_unreachable:
                raise
        self.api = None
        self.admin = False
        self.session_expired = False
        self.data = {}
        self.pending_bookings = []
        self.queue_button = None
        if self.heartbeat:
            self.heartbeat.cancel()
            self.heartbeat = None

    async def refresh(self, _):
        if self.busy:
            return
        self.busy = True
        try:
            self.data = await self.call("state")
        except ApiError as error:
            self.notify(str(error))
            return
        finally:
            self.busy = False
        self.render()

    def render(self):
        self.layout = self.viewport()
        _, compact, extended = self.layout
        training = self.training
        view_index = training.screen if training else self.screen
        if training:
            training.targets.clear()
        self.page.clean()
        views = [
            ("Kasse", ft.Icons.POINT_OF_SALE, lambda: register(training or self)),
            ("Deckel", ft.Icons.RECEIPT_LONG, lambda: tabs(training or self)),
            ("Artikel", ft.Icons.INVENTORY_2, lambda: products(training or self)),
            ("Tagesabrechnung", ft.Icons.SUMMARIZE, lambda: closing(self)),
        ]
        if self.admin:
            views.append(("Personal", ft.Icons.PEOPLE, lambda: staff(self)))
        views.append(("Einstellungen", ft.Icons.SETTINGS, lambda: settings(self)))
        title, icon, content = views[view_index]
        count = int(training.active("queue")) if training else len(self.pending_bookings)
        self.queue_button = ft.IconButton(
            ft.Icons.SYNC, tooltip="Buchungswarteschlange", on_click=lambda _: training.queue() if training else queue_screen(self),
            disabled=bool(training and not training.active("queue")),
            width=38 if training else None, height=38 if training else None,
            badge=ft.Badge(
                label=str(count), offset=ft.Offset(-5, 5) if training else None,
            ) if count else None,
        )
        self.page.appbar = ft.AppBar(
            bgcolor=SURFACE,
            toolbar_height=48 if compact else 62,
            center_title=False,
            title=ft.Row([
                ft.Icon(icon, color=AMBER, size=20 if compact else 24),
                ft.Text(title, size=19 if compact else 24, weight=ft.FontWeight.BOLD),
            ], spacing=8),
            actions=[
                training.highlight("queue", self.queue_button) if training else self.queue_button,
                ft.IconButton(ft.Icons.REFRESH, tooltip="Aktualisieren", on_click=self.refresh, disabled=bool(training)),
                ft.IconButton(ft.Icons.SETTINGS, tooltip="Einstellungen",
                              on_click=lambda _: navigate(len(views) - 1), disabled=bool(training)),
                ft.IconButton(ft.Icons.LOGOUT, tooltip=f"{self.display_username} abmelden", on_click=self.logout, disabled=bool(training)),
            ],
        )
        def navigate(index):
            if training:
                training.navigate(index)
                return
            if not self.busy and self.screen != index:
                self.screen = index
                self.render()

        wide_navigation = extended and not compact
        destinations = []
        for i, (label, destination_icon, _) in enumerate(views):
            selected = i == view_index
            target = {0: "register", 1: "tabs", 2: "articles"}.get(i)
            disabled = bool(training and (target is None or not training.active(target)))
            on_click = lambda _, index=i: navigate(index)
            if wide_navigation:
                destination = ft.TextButton(
                    label, icon=destination_icon, height=46, on_click=on_click, disabled=disabled,
                    style=ft.ButtonStyle(
                        alignment=ft.Alignment.CENTER_LEFT, color=AMBER if selected else None,
                        bgcolor="#3A3020" if selected else None,
                        shape=ft.RoundedRectangleBorder(radius=10),
                    ),
                )
            else:
                destination = ft.IconButton(
                    destination_icon, tooltip=label, on_click=on_click, width=44, height=44, disabled=disabled,
                    icon_color=AMBER if selected else None,
                    bgcolor="#3A3020" if selected else None,
                )
            if training and target:
                destination = training.highlight(target, destination, radius=14 if wide_navigation else 999)
            destinations.append(destination)
        nav = ft.Container(
            ft.ListView(destinations, spacing=4, padding=8),
            width=184 if wide_navigation else (68 if training else 60),
            bgcolor=SURFACE,
        )
        area = content() if view_index == 0 else ft.Column(
            content(), spacing=12, scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        inset = 8 if compact else 20
        self.page.add(ft.SafeArea(ft.Row([
            nav,
            ft.Container(
                ft.Column([
                    training.guide(),
                    ft.Container(area, expand=True),
                ], width=1260 if view_index == 0 else 930, spacing=6,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH) if training else
                ft.Column([
                    self.update_status_banner,
                    ft.Container(area, expand=True),
                ], width=1260 if view_index == 0 else 930, spacing=6,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                alignment=ft.Alignment.TOP_CENTER, padding=inset, expand=True,
            ),
        ], spacing=0, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
            avoid_intrusions_top=False, expand=True))


def main(page: ft.Page):
    page.title = "CashApp"
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.AMBER)
    page.dark_theme = ft.Theme(color_scheme_seed=ft.Colors.AMBER)
    page.bgcolor = BACKGROUND
    page.padding = 0
    CashApp(page)


if __name__ == "__main__":
    ft.run(main)
