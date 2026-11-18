from __future__ import annotations

import flet as ft

from Utils.formatting import amount, euro
from .dialogs import form
from .ui_components import MUTED, panel, product_category


def products(app):
    controls = []
    if app.admin:
        controls.append(ft.FilledButton("Neuer Artikel", on_click=lambda _: edit_product(app, {})))
    for product in app.data["products"]:
        category = product_category(product)
        if category != product["category"]:
            category += f" (Standard: {product['category']})"
        training = app.training
        can_edit = not training or (training.active("category") and product["id"] == 1)
        category_button = ft.IconButton(
            ft.Icons.LABEL_OUTLINE, tooltip="Persönliche Kategorie",
            on_click=lambda _, p=product: edit_personal_category(app, p),
            disabled=not can_edit,
        )
        actions = [training.highlight("category", category_button)
                   if training and can_edit else category_button]
        if app.admin:
            actions.append(ft.IconButton(ft.Icons.EDIT, tooltip="Artikel bearbeiten",
                                         on_click=lambda _, p=product: edit_product(app, p)))
        controls.append(panel(ft.ListTile(
            title=ft.Text(product["name"]),
            subtitle=ft.Text(f"{category} · {euro(product['cents'])} · "
                             f"{'Aktiv' if product['enabled'] else 'Inaktiv'}"),
            on_click=(lambda _, p=product: edit_personal_category(app, p)) if can_edit else None,
            trailing=ft.Row(actions, tight=True, spacing=0),
        ), padding=4))
    return controls or [ft.Text("Noch keine Artikel.", color=MUTED)]


def category_input(current, categories, label="Kategorie"):
    category_name = current
    category = ft.Dropdown(
        label=label,
        hint_text="Auswählen oder neuen Namen eingeben",
        value=current or None,
        text=current,
        editable=True,
        enable_filter=True,
        expanded_insets=ft.Padding.all(0),
        expand=True,
        options=[ft.dropdown.Option(key=label, text=label) for label in categories],
    )

    def choose_category(event):
        nonlocal category_name
        category_name = event.control.value or ""

    def type_category(event):
        nonlocal category_name
        category_name = event.control.text or ""

    category.on_select = choose_category
    category.on_text_change = type_category

    def selected_category():
        label = category_name.strip()
        return next((v for v in categories if v.casefold() == label.casefold()), label)

    return ft.Row([category]), selected_category


def edit_personal_category(app, product):
    categories = sorted({label for p in app.data["products"] for label in
                         (p["category"], product_category(p))}, key=str.casefold)
    category, selected_category = category_input(
        product.get("personal_category") or "", categories, "Persönliche Kategorie",
    )

    def submit():
        label = selected_category()
        return "save_personal_category", {
            "product_id": product["id"],
            "category": label if label and label != product["category"] else None,
        }

    training = app.training
    detail = (
        "Gib einen eigenen Kategorienamen ein, zum Beispiel Favoriten, und tippe auf Bestätigen."
        if training else f"Standard: {product['category']}. Leere das Feld, um wieder die Standardkategorie zu verwenden."
    )
    form(app, f"Persönliche Kategorie · {product['name']}", [
        training.highlight("category", category, radius=8) if training else category,
        ft.Text(detail, color=MUTED),
    ], submit, training_target="category" if training else None)


def edit_product(app, product):
    name = ft.TextField(label="Name", value=product.get("name", ""))
    categories = sorted({p["category"] for p in app.data["products"] if p["category"]}, key=str.casefold)
    category, selected_category = category_input(product.get("category", ""), categories)
    price = ft.TextField(label="Preis in €", value=(
        f"{product['cents'] / 100:.2f}".replace(".", ",") if product else ""
    ))
    enabled = ft.Checkbox(label="In der Kasse verfügbar", value=bool(product.get("enabled", 1)))

    def submit():
        label = selected_category()
        if not label:
            raise ValueError("Wähle eine Kategorie oder gib einen neuen Namen ein.")
        data = {"name": name.value, "category": label, "cents": amount(price.value),
                "enabled": int(enabled.value)}
        if product:
            data["id"] = product["id"]
        return "save_product", data

    form(app, "Artikel bearbeiten" if product else "Neuer Artikel",
         [name, category, price, enabled], submit)
