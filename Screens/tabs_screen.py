from __future__ import annotations

import flet as ft

from Utils.api import ApiError
from Utils.formatting import amount, cash_received, euro
from .dialogs import form
from .ui_components import AMBER, MUTED, entry_row, panel, show_dialog


def tabs(app):
    controls = []
    show_settled = app.preferences.get("show_settled_tabs", True)
    for tab in app.data["tabs"]:
        if not show_settled and not tab["balance"]:
            continue
        tile = panel(ft.ListTile(
            leading=ft.Icon(ft.Icons.RECEIPT_LONG, color=AMBER if tab["balance"] else MUTED),
            title=ft.Text(f"{tab['name']} · #{tab['id']}"),
            subtitle=ft.Text("Offen" if tab["balance"] else "Ausgeglichen"),
            trailing=ft.Text(euro(tab["balance"]), weight=ft.FontWeight.BOLD),
            on_click=tab_handler(app, tab),
        ), padding=4)
        if app.training:
            target = "payment" if app.training.active("payment") else "tab"
            tile = app.training.highlight(target, tile, radius=20)
        controls.append(tile)
    return controls or [ft.Text("Noch keine Deckel. Buche einen Warenkorb auf Deckel."
                                if show_settled else "Keine offenen Deckel.")]


def tab_handler(app, tab):
    async def show(_):
        if app.busy:
            return
        if app.training:
            if app.training.active("tab"):
                app.training.advance()
            if not app.training.active("payment"):
                return
            show_dialog(app.page, f"Übungsdeckel · offen {euro(tab['balance'])}", [
                ft.Text("Öffne Barzahlung und gib einen Teilbetrag ein. Der Rest bleibt auf dem Deckel."),
            ], [
                ft.TextButton("Schließen", on_click=lambda _: app.page.pop_dialog()),
                app.training.highlight("payment", ft.FilledButton(
                    "Barzahlung", on_click=lambda _: payment(app, tab, tab["balance"]),
                )),
            ])
            return
        app.busy = True
        try:
            detail = await app.call("tab_detail", tab_id=tab["id"])
        except ApiError as error:
            app.notify(str(error))
            return
        finally:
            app.busy = False
        other = [ft.TextButton("Schließen", on_click=lambda _: app.page.pop_dialog())]
        deckel_actions = [
            ft.OutlinedButton("Name ändern", icon=ft.Icons.EDIT, on_click=lambda _: rename_tab(app, tab)),
        ]
        if app.admin:
            deckel_actions.append(ft.TextButton(
                "Deckel löschen", icon=ft.Icons.DELETE_OUTLINE,
                on_click=lambda _: delete_tab(app, tab, detail["balance"]),
            ))
        fields = [ft.Row(deckel_actions, wrap=True), *[entry_row(e) for e in detail["entries"]]]
        if detail["balance"] > 0:
            other.insert(0, ft.FilledButton(
                "Barzahlung", on_click=lambda _: payment(app, tab, detail["balance"]),
            ))
        if app.admin:
            other.insert(0, ft.TextButton(
                "Kundenkonto freigeben", on_click=lambda _: guest(app, tab, detail.get("guest_username")),
            ))
        show_dialog(app.page, f"{tab['name']} · offen {euro(detail['balance'])}",
                    fields, other, modal=False)
    return show


def rename_tab(app, tab):
    app.page.pop_dialog()
    name = ft.TextField(label="Deckelname", value=tab["name"], max_length=120)
    form(app, f"Deckelname ändern · {tab['name']}", [name], lambda: (
        "rename_tab", {"tab_id": tab["id"], "tab_name": " ".join((name.value or "").split())},
    ))


def delete_tab(app, tab, balance):
    app.page.pop_dialog()
    unpaid = [ft.Text(f"Der offene Betrag von {euro(balance)} wird storniert.")] if balance else []
    form(app, f"Deckel löschen · {tab['name']}", [
        *unpaid,
        ft.Text("Der Deckel und sein Kundenzugang werden aus der Kasse entfernt. "
                "Zahlungen und Stornos bleiben in der Tagesabrechnung erhalten."),
    ], lambda: ("delete_tab", {"tab_id": tab["id"], "expected_balance": balance}))


def payment(app, tab, balance):
    app.page.pop_dialog()
    paid = ft.TextField(label="Teil- oder Gesamtbetrag in €", value=f"{balance / 100:.2f}".replace(".", ","))
    received = ft.TextField(label="Gegeben in € (leer = passend)")

    def submit():
        cents = amount(paid.value)
        if not 0 < cents <= balance:
            raise ValueError("Gib einen Teilbetrag bis zur Höhe des offenen Betrags ein.")
        return "payment", {"tab_id": tab["id"], "cents": cents,
                           "received": cash_received(received.value, cents) if received.value else cents}

    form(app, f"Barzahlung · {tab['name']}", [paid, received], submit, booking=True)


def guest(app, tab, username=None):
    app.page.pop_dialog()
    name = ft.TextField(label="Kunden-Benutzername", value=username or "", max_length=64)
    feedback = ft.Text(color=ft.Colors.ERROR, visible=False)

    async def release(_):
        if app.busy:
            return
        app.busy = True
        confirm.disabled = cancel.disabled = True
        app.page.update()
        try:
            result = await app.call("invite_guest", tab_id=tab["id"], username=name.value)
        except ApiError as error:
            feedback.value = str(error)
            feedback.visible = True
            confirm.disabled = cancel.disabled = False
            app.page.update()
            return
        finally:
            app.busy = False
        app.page.pop_dialog()
        show_dialog(app.page, "Kundenkonto freigegeben", [
            ft.Text("Gib dem Kunden den Benutzernamen und den Einmalcode. Er legt sein Passwort bei der Aktivierung fest."),
            ft.Text(f"Benutzername: {result['username']}", selectable=True),
            ft.Text(result["code"], selectable=True, color=AMBER, size=26, weight=ft.FontWeight.BOLD),
            ft.Text(f"{app.server_url}/?aktivieren", selectable=True),
            ft.Text("Der Code gilt sieben Tage und wird nach fünf falschen Eingaben gesperrt.", color=MUTED),
        ], [ft.TextButton("Schließen", on_click=lambda _: app.page.pop_dialog())])

    confirm = ft.FilledButton("Einmalcode erstellen", on_click=release)
    cancel = ft.TextButton("Abbrechen", on_click=lambda _: app.page.pop_dialog())
    show_dialog(app.page, f"Kundenkonto freigeben · {tab['name']}", [
        name,
        ft.Text("Ein neuer Code ersetzt eine noch offene Freigabe. Ein bestehendes Passwort gilt bis zur Aktivierung.", color=MUTED),
        feedback,
    ], [cancel, confirm])
