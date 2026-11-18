from __future__ import annotations

import flet as ft

from .dialogs import form
from .ui_components import panel


def staff(app):
    controls = [ft.FilledButton("Neues Personalkonto", on_click=lambda _: new_staff(app))]
    for account in app.data["staff"]:
        def toggle(_, row=account):
            form(app, f"{row['username']} {'sperren' if row['enabled'] else 'freigeben'}", [],
                      lambda: ("toggle_staff", {"id": row["id"], "enabled": 1 - row["enabled"]}))
        actions = ft.PopupMenuButton(
            tooltip=f"Optionen für {account['username']}",
            items=[
                ft.PopupMenuItem(content="Sperren" if account["enabled"] else "Freigeben", on_click=toggle),
                ft.PopupMenuItem(content="Passwort zurücksetzen", icon=ft.Icons.KEY,
                                 on_click=lambda _, row=account: reset_password(app, row)),
                ft.PopupMenuItem(content="Konto löschen", icon=ft.Icons.DELETE_OUTLINE,
                                 on_click=lambda _, row=account: delete_account(app, row)),
            ],
        ) if account["username"] != app.display_username else None
        controls.append(panel(ft.ListTile(
            title=ft.Text(account["username"]),
            subtitle=ft.Text(f"{'Admin' if account['role'] == 'admin' else 'Mitarbeiter'} · "
                             f"{'Aktiv' if account['enabled'] else 'Gesperrt'}"),
            trailing=actions,
        ), padding=4))
    return controls


def new_staff(app):
    name = ft.TextField(label="Personal-Benutzername")
    password = ft.TextField(label="Passwort", password=True)
    admin = ft.Checkbox(label="Administrator")
    form(app, "Neues Personalkonto", [name, password, admin], lambda: (
        "add_staff", {"username": name.value, "password": password.value, "role": "admin" if admin.value else "staff"},
    ))


def reset_password(app, account):
    password = ft.TextField(label="Neues Passwort", password=True, can_reveal_password=True)
    confirmation = ft.TextField(label="Passwort wiederholen", password=True, can_reveal_password=True)

    def submit():
        if password.value != confirmation.value:
            raise ValueError("Die Passwörter stimmen nicht überein.")
        return "reset_staff_password", {"id": account["id"], "password": password.value}

    form(app, f"Passwort zurücksetzen · {account['username']}", [password, confirmation], submit)


def delete_account(app, account):
    form(app, f"Personalkonto löschen · {account['username']}", [
        ft.Text("Das Konto verliert seinen Zugang und verschwindet aus der Personalliste. "
                "Seine Buchungen bleiben erhalten."),
    ], lambda: ("delete_staff", {"id": account["id"]}))
