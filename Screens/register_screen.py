from __future__ import annotations

import flet as ft

from Utils.api import ApiError
from Utils.formatting import cash_received, euro
from Utils.settings import local_product_order, save_local_product_order
from .dialogs import form
from .ui_components import AMBER, BACKGROUND, MUTED, OUTLINE, panel, product_category


def total(app):
    return sum(line["cents"] * line["quantity"] for line in app.cart.values())


def change_cart(app, product, delta, update):
    if app.busy:
        return
    key = product["id"]
    line = app.cart.get(key, product)
    quantity = app.cart.get(key, {}).get("quantity", 0) + delta
    if quantity <= 0:
        app.cart.pop(key, None)
    elif quantity <= 999:
        app.cart[key] = {**line, "quantity": quantity}
    update()


def register(app):
    training = app.training
    viewport = app.layout
    landscape, compact, _ = viewport
    server_order = app.data.get("product_order")
    order = local_product_order(app.server_url, app.username) if server_order is None else server_order
    ranks = {key: rank for rank, key in enumerate(order)}
    ordered = sorted(app.data["products"], key=lambda p: ranks.get(p["id"], len(ranks)))
    products = [p for p in ordered if p["enabled"]]
    categories = [None, *sorted({product_category(p) for p in products}, key=str.casefold)]
    sorting = bool(training and training.active("drag"))
    if app.category not in categories:
        app.category = None

    def filter_target(name):
        if not training:
            return None
        if name is None and training.active("clear_filter"):
            return "clear_filter"
        if training.active("filter") and name == training.data["products"][0].get("personal_category"):
            return "filter"
        return None

    def category(name):
        if training:
            target = filter_target(name)
            if target and not training.busy:
                training.category = name
                training.advance(f"✓  Nach {name} gefiltert" if name else "✓  Alle Artikel sind sichtbar")
            return
        app.category = name
        for chip, label in zip(filters.controls, categories):
            chip.selected = label == name
        grid.controls = tiles()
        app.page.update()

    def filter_chip(name):
        target = filter_target(name)
        chip = ft.Chip(label=ft.Text(name or "Alle Artikel"), selected=name == app.category,
                       disabled=bool(training and not target),
                       on_select=lambda _: category(name))
        return training.highlight(target, chip, radius=12) if target else chip

    filters = ft.Row([filter_chip(name) for name in categories],
                     scroll=ft.ScrollMode.AUTO, spacing=6, expand=True)

    def toggle_sort(_):
        nonlocal sorting
        if training:
            if not training.busy and training.active("sort"):
                training.advance()
            return
        sorting = not sorting
        sort_button.icon = ft.Icons.CHECK if sorting else ft.Icons.SWAP_HORIZ
        sort_button.tooltip = "Sortieren beenden" if sorting else "Artikel sortieren"
        sort_hint.visible = sorting
        grid.controls = tiles()
        app.page.update()

    sort_button = ft.IconButton(ft.Icons.CHECK if sorting else ft.Icons.SWAP_HORIZ,
                                tooltip="Artikel sortieren", on_click=toggle_sort,
                                disabled=bool(training and not training.active("sort")) or len(products) < 2)
    sort_hint = ft.Text("Artikel am Griff auf die gewünschte Kachel ziehen.", color=MUTED,
                        size=12, visible=sorting)

    async def swap(event, target):
        source = getattr(event, "src", None)
        if app.busy or not sorting or source is None or source.data == target:
            return
        positions = {p["id"]: i for i, p in enumerate(ordered)}
        if source.data not in positions:
            return
        if training:
            if training.active("drag") and source.data == 1 and target == 2:
                training.swapped()
            return
        a, b = positions[source.data], positions[target]
        order = [p["id"] for p in ordered]
        order[a], order[b] = order[b], order[a]
        app.busy = True
        try:
            if server_order is None:
                save_local_product_order(app.server_url, app.username, order)
            else:
                await app.call("save_product_order", product_ids=order)
                app.data["product_order"] = order
        except (ApiError, OSError) as error:
            app.notify(f"Artikelreihenfolge konnte nicht gespeichert werden. {error}")
            return
        finally:
            app.busy = False
        if app.layout != viewport:
            app.render()
            return
        ordered[a], ordered[b] = ordered[b], ordered[a]
        grid.controls = tiles()
        app.page.update()

    def tile(p):
        label = ft.Column([
            ft.Text(p["name"], size=13 if compact else 15, weight=ft.FontWeight.W_600,
                    max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(euro(p["cents"]), color=AMBER, weight=ft.FontWeight.BOLD),
        ], alignment=ft.MainAxisAlignment.CENTER, spacing=2)
        if not sorting:
            button = ft.OutlinedButton(
                content=label,
                on_click=lambda _: training.added(p, update_cart) if training else change_cart(app, p, 1, update_cart),
                disabled=bool(training and not training.can_add(p)),
                tooltip=f"{p['name']} zum Warenkorb hinzufügen",
                style=ft.ButtonStyle(
                    alignment=ft.Alignment.CENTER_LEFT, padding=8 if compact else 12,
                    bgcolor=BACKGROUND, side=ft.BorderSide(1, OUTLINE),
                    shape=ft.RoundedRectangleBorder(radius=10),
                ),
            )
            if training and training.can_add(p):
                target = "product" if training.active("product") else "deckel_product"
                return training.highlight(target, button, radius=14)
            return button
        label.expand = True
        handle = ft.Draggable(
            data=p["id"], group="register-products", max_simultaneous_drags=1,
            content=ft.Container(ft.Icon(ft.Icons.DRAG_INDICATOR, color=AMBER, size=20),
                                 padding=ft.Padding.symmetric(vertical=12, horizontal=3)),
            content_feedback=ft.Container(
                ft.Text(p["name"], color=BACKGROUND, weight=ft.FontWeight.W_600, max_lines=2),
                width=155, padding=10, bgcolor=AMBER, border_radius=8,
            ),
        )

        async def accept(event):
            await swap(event, p["id"])

        target = ft.DragTarget(
            group="register-products", on_accept=accept,
            content=ft.Container(
                ft.Row([handle, label], spacing=2), padding=6,
                bgcolor=BACKGROUND, border=ft.Border.all(1, OUTLINE), border_radius=10,
            ),
        )

        return training.highlight("drag", target, radius=14) if training and p["id"] == 1 else target

    def tiles():
        return [tile(p) for p in ordered if p["enabled"] and
                (app.category is None or app.category == product_category(p))]

    default_extent = 150 if compact else 190
    tile_size = app.preferences.get("tile_size")
    tile_extent = {"small": default_extent - 24, "large": default_extent + 40}.get(tile_size, default_extent)
    grid = ft.GridView(
        controls=tiles(), expand=True, max_extent=tile_extent,
        child_aspect_ratio=1.25 if tile_size == "small" else (1.55 if compact else 1.85),
        spacing=8, run_spacing=8,
    )
    receipt = ft.ListView(expand=True, spacing=4)
    headline = ft.Text("Warenkorb", size=18 if compact else 22, weight=ft.FontWeight.BOLD, expand=True)
    sum_text = ft.Text(color=AMBER, size=21 if compact else 27, weight=ft.FontWeight.BOLD)
    pay = ft.FilledButton("Bar bezahlen", height=38 if compact else None, on_click=lambda _: sale(app))
    charge_tab = ft.OutlinedButton("Auf Deckel", height=38 if compact else None, on_click=lambda _: charge(app))

    def quantity_button(line, delta):
        increase = delta > 0
        target = "increase" if increase else "decrease"
        button = ft.IconButton(
            ft.Icons.ADD if increase else ft.Icons.REMOVE,
            tooltip="Ein Stück hinzufügen" if increase else "Ein Stück entfernen",
            padding=0 if compact else None, width=34 if compact else None, height=34 if compact else None,
            disabled=bool(training and (not training.active(target) or (increase and line["quantity"] >= 999))),
            on_click=lambda _: training.adjust(line, delta) if training else change_cart(app, line, delta, update_cart),
        )
        return training.highlight(target, button) if training and not button.disabled else button

    def update_cart(*, repaint=True):
        receipt.controls = [
            ft.Row([
                ft.Column([
                    ft.Text(line["name"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            weight=ft.FontWeight.W_600),
                    ft.Text(euro(line["cents"] * line["quantity"]), color=MUTED, size=12),
                ], expand=True, spacing=2),
                quantity_button(line, -1),
                ft.Text(str(line["quantity"])),
                quantity_button(line, 1),
            ], spacing=0)
            for line in app.cart.values()
        ] or [ft.Text("Noch keine Positionen.", color=MUTED)]
        sum_text.value = euro(total(app))
        pay.disabled = not app.cart or bool(training and not training.active("sale"))
        charge_tab.disabled = not app.cart or bool(training and not training.active("charge"))
        if repaint:
            app.page.update()

    update_cart(repaint=False)
    catalog = panel(ft.Column([
        ft.Row([filters, training.highlight("sort", sort_button) if training else sort_button], spacing=2),
        sort_hint,
        grid if products else ft.Text("Noch keine aktiven Artikel.", color=MUTED),
    ], spacing=8), padding=10 if compact else 16, expand=6)
    basket = panel(ft.Column([
        ft.Row([headline, sum_text], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        receipt,
        ft.Divider(height=5 if compact else None),
        training.highlight("sale", pay) if training else pay,
        training.highlight("charge", charge_tab) if training else charge_tab,
    ], spacing=3 if compact else 9, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=10 if compact else 16, expand=4)
    layout = ft.Row if landscape else ft.Column
    return layout(
        [catalog, basket], spacing=8 if compact else 14,
        **({"vertical_alignment": ft.CrossAxisAlignment.STRETCH} if landscape else
           {"horizontal_alignment": ft.CrossAxisAlignment.STRETCH}),
    )


def cart_payload(app):
    return [{key: p[key] for key in ("id", "quantity", "cents")} for p in app.cart.values()]


def sale(app):
    cents = total(app)
    received = ft.TextField(label="Gegeben in €", value=f"{cents / 100:.2f}".replace(".", ","))
    form(app, f"Bar bezahlen · {euro(cents)}", [received],
              lambda: ("sale", {"items": cart_payload(app), "received": cash_received(received.value, cents)}),
              booking=True)


def charge(app):
    tabs = app.data["tabs"]
    results = ft.ListView(height=132, spacing=0)
    selector = ft.RadioGroup(content=results)
    search = ft.TextField(label="Bestehenden Deckel suchen", prefix_icon=ft.Icons.SEARCH,
                          hint_text="Name oder Deckelnummer", visible=bool(tabs))
    name = ft.TextField(label="Oder neuer Deckelname" if tabs else "Neuer Deckelname", max_length=120)

    def search_tabs(event=None):
        query = (search.value or "").strip().casefold()
        matches = [
            t for t in tabs
            if query in t["name"].casefold() or query.lstrip("#") == str(t["id"])
        ]
        if selector.value not in {str(t["id"]) for t in matches}:
            selector.value = None
        results.controls = [
            ft.Radio(value=str(t["id"]), label=f"{t['name']} · #{t['id']} · {euro(t['balance'])}")
            for t in matches
        ] or [ft.Text("Keine passenden Deckel.", color=MUTED)]
        if event is not None:
            app.page.update()

    search.on_change = search_tabs
    selector.visible = bool(tabs)
    search_tabs()

    def submit():
        new_name = " ".join((name.value or "").split())
        if bool(selector.value) == bool(new_name):
            raise ValueError("Wähle einen bestehenden Deckel oder gib einen neuen Namen ein.")
        if new_name and any(" ".join(t["name"].split()).casefold() == new_name.casefold() for t in tabs):
            raise ValueError("Dieser Deckelname existiert bereits. Wähle den vorhandenen Deckel aus.")
        target = {"tab_id": int(selector.value)} if selector.value else {"tab_name": new_name}
        return "charge", {"items": cart_payload(app), **target}

    form(app, f"Auf Deckel · {euro(total(app))}", [search, selector, name], submit, booking=True)
