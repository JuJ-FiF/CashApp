from __future__ import annotations

import flet as ft

from Utils.formatting import euro, local_time


BACKGROUND = "#141412"
SURFACE = "#1D1D19"
OUTLINE = "#3C3B32"
AMBER = "#FFD16C"
MUTED = "#C1BDB0"
LABELS = {
    "sale": "Barverkauf",
    "charge": "Auf Deckel",
    "payment": "Deckelzahlung",
    "reversal": "Storno",
}


def product_category(product):
    return product.get("personal_category") or product["category"]


def panel(content, *, col=None, padding=18, expand=None):
    return ft.Container(
        content=content, col=col, padding=padding, bgcolor=SURFACE,
        border=ft.Border.all(1, OUTLINE), border_radius=16, expand=expand,
    )


def show_dialog(page, title, fields, actions, *, modal=True):
    page.show_dialog(ft.AlertDialog(
        modal=modal, title=ft.Text(title, size=21, weight=ft.FontWeight.W_600),
        content=ft.Column(
            fields, width=460, tight=True, spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
        actions=actions, scrollable=True, bgcolor=SURFACE,
        inset_padding=ft.Padding.symmetric(horizontal=12, vertical=10),
        title_padding=ft.Padding(18, 14, 18, 0),
        content_padding=ft.Padding(18, 12, 18, 8),
        actions_padding=ft.Padding(12, 2, 12, 8),
        shape=ft.RoundedRectangleBorder(radius=16),
    ))


def entry_row(entry, actions=None):
    detail = [local_time(entry["created_at"]), entry.get("username"), entry.get("tab_name"), entry.get("items")]
    if entry.get("reversed_id"):
        detail.append(f"zu #{entry['reversed_id']}")
    if entry.get("reason"):
        detail.append(entry["reason"])
    return ft.ListTile(
        title=ft.Text(f"#{entry['id']} · {LABELS[entry['kind']]} · {euro(entry['cents'])}"),
        subtitle=ft.Text(" · ".join(filter(None, detail))), trailing=actions,
    )
