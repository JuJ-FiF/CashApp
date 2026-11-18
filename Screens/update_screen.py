"""Update-Dialoge für CashApp."""

import asyncio
import logging
import sys

import flet as ft

from Utils.updater import (
    check_for_update,
    download_apk,
    is_android_runtime,
    open_security_settings as open_android_security_settings,
    request_install_permission,
    start_android_update,
)
from Utils.version import APP_VERSION
from .ui_components import AMBER, MUTED, panel

logger = logging.getLogger(__name__)


class AppUpdates:
    def __init__(self, app):
        self.app = app
        self.update_status = app.update_status_banner

    def build(self):
        return panel(ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.SYSTEM_UPDATE, color=AMBER),
                ft.Text("App-Updates", size=18, weight=ft.FontWeight.W_600),
            ], spacing=10),
            ft.Text(f"Installierte Version: {APP_VERSION}"),
            ft.Text("Updates werden über GitHub-Releases geprüft und als Android-App installiert.", color=MUTED),
            ft.Row([
                ft.OutlinedButton("Nach Updates suchen", icon=ft.Icons.SYSTEM_UPDATE, on_click=self.check_updates),
            ], alignment=ft.MainAxisAlignment.END, wrap=True),
        ], spacing=10))

    async def check_updates(self, _=None):
        if self.app.update_running:
            return
        self.app.update_running = True
        self._set_update_status("Suche nach Updates …")
        try:
            update = await check_for_update()
            if update is None:
                if sys.platform == "win32":
                    await self.simulate_update_process()
                else:
                    self._hide_update_status()
                    self._show_update_message(
                        "Keine Updates",
                        f"Du verwendest bereits die aktuelle Version {APP_VERSION}.",
                    )
                return
            self._hide_update_status()
            self.show_update_dialog(update)
        except Exception as error:
            logger.warning(f"Updateprüfung fehlgeschlagen: {error}")
            self._hide_update_status()
            self._show_update_message(
                "Updateprüfung fehlgeschlagen",
                f"Die Suche nach Updates konnte nicht durchgeführt werden.\n\nFehler:\n{error}",
            )
        finally:
            self.app.update_running = False

    def show_update_dialog(self, update: dict):
        async def install_update(_):
            await self.download_update(update["download_url"])

        self.app.page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Update verfügbar: {update['version']}"),
            content=ft.Column(
                [ft.Text(update["changelog"] or "Keine Änderungen angegeben.", selectable=True)],
                tight=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                ft.TextButton("Später", on_click=lambda _: self.app.page.pop_dialog()),
                ft.FilledButton(
                    "Update installieren",
                    icon=ft.Icons.SYSTEM_UPDATE,
                    on_click=install_update,
                ),
            ],
        ))

    def _set_update_status(self, message: str, icon=None):
        indicator = (
            ft.Icon(icon, color=ft.Colors.WHITE)
            if icon
            else ft.ProgressRing(width=20, height=20, stroke_width=2, color=ft.Colors.WHITE)
        )
        self.update_status.content = ft.Row([
            indicator,
            ft.Text(message, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD, expand=True),
        ], spacing=10)
        self.update_status.visible = True
        self.app.page.update()

    def _hide_update_status(self):
        self.update_status.visible = False
        self.app.page.update()

    async def simulate_update_process(self):
        steps = [
            ("Updatevorgang wird unter Windows simuliert …", None),
            ("Download wird simuliert …", None),
            ("Installationsdialog wird simuliert …", ft.Icons.SYSTEM_UPDATE),
        ]
        for message, icon in steps:
            self._set_update_status(message, icon)
            await asyncio.sleep(0.7)
        self._set_update_status(
            f"Simulation abgeschlossen · Version {APP_VERSION} bleibt installiert.",
            ft.Icons.CHECK_CIRCLE,
        )
        await asyncio.sleep(2)
        self._hide_update_status()

    def _show_update_message(self, title: str, message: str):
        self.app.page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Text(message, selectable=True),
            actions=[ft.TextButton("OK", on_click=lambda _: self.app.page.pop_dialog())],
        ))

    def show_update_safety_dialog(self, download_url: str):
        async def open_settings(_):
            try:
                await asyncio.to_thread(open_android_security_settings)
            except Exception as error:
                self.app.notify(f"Sicherheitseinstellungen konnten nicht geöffnet werden: {error}")

        async def continue_update(_):
            await self.download_update(download_url, safety_confirmed=True)

        self.app.page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text("Sicherheitseinstellung prüfen"),
            content=ft.Column(
                [
                    ft.Text(
                        "Auf Samsung Galaxy kann die Automatische Sperre die "
                        "Installation dieses Updates blockieren. Falls nötig, "
                        "öffne Sicherheit und Datenschutz → Automatische Sperre "
                        "und deaktiviere sie vorübergehend. Aktiviere sie nach "
                        "dem Update wieder."
                    ),
                    ft.OutlinedButton(
                        "Sicherheitseinstellungen öffnen",
                        icon=ft.Icons.SECURITY,
                        on_click=open_settings,
                    ),
                ],
                tight=True,
                spacing=14,
            ),
            actions=[
                ft.TextButton("Abbrechen", on_click=lambda _: self.app.page.pop_dialog()),
                ft.FilledButton(
                    "Weiter",
                    icon=ft.Icons.ARROW_FORWARD,
                    on_click=continue_update,
                ),
            ],
        ))

    async def download_update(self, download_url: str, safety_confirmed: bool = False):
        if self.app.update_running:
            return
        self.app.update_running = True
        try:
            self.app.page.pop_dialog()
            if sys.platform == "win32":
                await self.simulate_update_process()
                return

            if not is_android_runtime():
                self._show_update_message("Android-Update", "Die APK lässt sich auf Android installieren.")
                return
            if self.app.cart:
                self._show_update_message("Warenkorb offen", "Schließe den Warenkorb ab oder leere ihn vor dem Update.")
                return
            if not safety_confirmed:
                self.show_update_safety_dialog(download_url)
                return

            self._set_update_status("Installationsberechtigung wird geprüft …")
            can_install = await asyncio.to_thread(request_install_permission)
            if not can_install:
                self._hide_update_status()
                self._show_update_message(
                    "Installation erlauben",
                    "Android hat die Einstellung für diese Quelle geöffnet. Erlaube dort die Installation unbekannter Apps und starte das Update anschließend erneut. Die APK wurde noch nicht heruntergeladen.",
                )
                return

            self._set_update_status("Update wird heruntergeladen …")
            apk_path = await asyncio.to_thread(download_apk, download_url)
            if self.app.cart or self.app.busy:
                self._hide_update_status()
                self._show_update_message("Kasse in Benutzung", "Schließe den aktuellen Vorgang ab und starte das Update erneut.")
                return

            self._set_update_status("Installationsdialog wird geöffnet …")
            await asyncio.to_thread(start_android_update, apk_path)
            self._set_update_status(
                "Bitte das Update im Android-Installationsdialog bestätigen.",
                ft.Icons.SYSTEM_UPDATE,
            )
        except Exception as error:
            logger.warning(f"Android-Update fehlgeschlagen: {error}")
            self._hide_update_status()
            self._show_update_message(
                "Update fehlgeschlagen",
                f"Das Update konnte nicht gestartet werden.\n\nFehler:\n{error}",
            )
        finally:
            self.app.update_running = False
