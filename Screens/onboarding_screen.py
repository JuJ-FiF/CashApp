import asyncio

import flet as ft

from Utils.api import ApiError
from Utils.formatting import euro
from .register_screen import change_cart, total
from .ui_components import AMBER, BACKGROUND, MUTED, show_dialog


STEPS = (
    ("Artikel kombinieren", "Tippe Limo und Wasser an. Tippe eine Kachel erneut an, um zwei Stück hinzuzufügen.", "product"),
    ("Menge erhöhen", "Tippe im Warenkorb auf +, um ein Stück hinzuzufügen.", "increase"),
    ("Menge verringern", "Tippe im Warenkorb auf −, um ein Stück abzuziehen. Bei null verschwindet die Position.", "decrease"),
    ("Bar kassieren", "Öffne „Bar bezahlen“ und gib mindestens den angezeigten Betrag ein.", "sale"),
    ("Warenkorb füllen", "Tippe erneut auf die Übungs-Limo. Diesmal kommt sie auf einen Deckel.", "deckel_product"),
    ("Auf Deckel buchen", "Öffne „Auf Deckel“, suche nach „Übung“ und wähle den Übungsdeckel.", "charge"),
    ("Deckel finden", "Tippe links auf das goldene Deckel-Symbol.", "tabs"),
    ("Deckel öffnen", "Tippe auf den Übungsdeckel, um den offenen Betrag zu sehen.", "tab"),
    ("Teilzahlung erfassen", "Öffne am Übungsdeckel „Barzahlung“. Gib zum Beispiel 1 € ein.", "payment"),
    ("Warteschlange prüfen", "Tippe oben auf das goldene Synchronisationssymbol mit der 1.", "queue"),
    ("Artikel öffnen", "Tippe links auf das goldene Artikel-Symbol.", "articles"),
    ("Eigene Kategorie vergeben", "Öffne das Etikett an der Übungs-Limo. Gib einen eigenen Kategorienamen ein.", "category"),
    ("Zur Kasse wechseln", "Tippe links auf Kasse. Dort siehst du deine persönliche Kategorie und Kachelreihenfolge.", "register"),
    ("Eigene Kategorie ausprobieren", "Tippe auf deine goldene Kategorie. Jetzt siehst du nur die passenden Kacheln.", "filter"),
    ("Alle Artikel anzeigen", "Tippe auf „Alle Artikel“, damit beide Kacheln zum Sortieren sichtbar sind.", "clear_filter"),
    ("Sortieren einschalten", "Tippe neben den Kategorien auf das Symbol mit den zwei Pfeilen.", "sort"),
    ("Artikel verschieben", "Ziehe die Übungs-Limo am Griff auf das Übungs-Wasser.", "drag"),
    ("Übung abschließen", "Deine echten Kategorien und die Kachelreihenfolge gelten pro Personalkonto.", "finish"),
)


class RegisterTraining:
    def __init__(self, app, automatic):
        self.app = app
        self.page = app.page
        self.automatic = automatic
        self.step = 0
        self.screen = 0
        self.cart = {}
        self.category = None
        self.preferences = {"show_settled_tabs": True}
        self.admin = False
        self.username = app.username
        self.feedback = ""
        self.targets = []
        self.pulse_task = None
        self.data = {
            "product_order": [1, 2],
            "products": [
                {"id": 1, "name": "Übungs-Limo", "cents": 250, "enabled": True, "category": "Getränke"},
                {"id": 2, "name": "Übungs-Wasser", "cents": 150, "enabled": True, "category": "Getränke"},
            ],
            "tabs": [{"id": 1, "name": "Übungsdeckel", "balance": 0}],
        }

    @property
    def training(self):
        return self

    @property
    def busy(self):
        return self.app.busy or self.app.training is not self or not self.app.api

    @property
    def layout(self):
        return self.app.layout

    @property
    def server_url(self):
        return self.app.server_url

    def active(self, target):
        return STEPS[self.step][2] == target

    def highlight(self, target, control, *, radius=999):
        if not self.active(target):
            return control
        framed = ft.Container(
            control, border=ft.Border.all(2, AMBER), border_radius=radius, padding=2,
            animate=ft.Animation(440, ft.AnimationCurve.EASE_IN_OUT),
        )
        self.targets.append(framed)
        return framed

    async def pulse(self):
        bright = False
        while self.app.training is self:
            await asyncio.sleep(0.62)
            if self.app.training is not self:
                return
            bright = not bright
            for control in self.targets:
                control.border = ft.Border.all(2, AMBER if bright else "#98743D")
            if self.targets:
                self.page.update()

    def advance(self, feedback=""):
        self.step += 1
        self.feedback = feedback
        self.app.render()

    def can_add(self, product):
        return self.active("product") or (self.active("deckel_product") and product["id"] == 1)

    def added(self, product, update):
        if self.busy or not self.can_add(product):
            return

        def after_add():
            if self.active("deckel_product"):
                self.advance("✓  Übungs-Limo liegt im Warenkorb")
            elif len(self.cart) == 2 and any(line["quantity"] > 1 for line in self.cart.values()):
                self.advance("✓  Verschiedene Artikel und mehrere Stück im Warenkorb")
            else:
                update()

        change_cart(self, product, 1, after_add)

    def adjust(self, product, delta):
        target = "increase" if delta > 0 else "decrease"
        line = self.cart.get(product["id"])
        if self.busy or not self.active(target) or not line or not 0 <= line["quantity"] + delta <= 999:
            return
        note = "Ein Stück hinzugefügt" if delta > 0 else "Ein Stück entfernt"
        change_cart(self, product, delta, lambda: self.advance(f"✓  {note}"))

    def navigate(self, index):
        target = {0: "register", 1: "tabs", 2: "articles"}.get(index)
        if target and not self.busy and self.active(target):
            self.screen = index
            self.advance()

    def swapped(self):
        self.data["product_order"] = [2, 1]
        self.advance("✓  Übungs-Limo und Übungs-Wasser haben die Plätze getauscht")

    def booked(self, action, data):
        if action == "save_personal_category" and self.active("category"):
            label = data["category"]
            if data["product_id"] != 1 or not label or label.casefold() == "getränke":
                raise ValueError("Gib für die Übung einen eigenen Kategorienamen ein, zum Beispiel Favoriten.")
            self.data["products"][0]["personal_category"] = label
            self.page.pop_dialog()
            self.advance(f"✓  Persönliche Kategorie gespeichert: {label}")
            return
        if action != STEPS[self.step][2]:
            raise ValueError("Folge dem goldenen Hinweis in der Einweisung.")
        tab = self.data["tabs"][0]
        if action == "sale":
            feedback = f"✓  Rückgeld: {euro(data['received'] - total(self))}"
        elif action == "charge":
            if data.get("tab_id") != tab["id"]:
                raise ValueError("Wähle den vorhandenen Übungsdeckel.")
            tab["balance"] += total(self)
            feedback = f"✓  {euro(tab['balance'])} stehen auf dem Übungsdeckel"
        else:
            if data["cents"] >= tab["balance"]:
                raise ValueError("Gib für diese Übung weniger als den offenen Betrag ein.")
            tab["balance"] -= data["cents"]
            feedback = f"✓  Teilzahlung erfasst · offen: {euro(tab['balance'])}"
        self.cart.clear()
        self.page.pop_dialog()
        self.advance(feedback)

    def queue(self):
        if self.busy or not self.active("queue"):
            return
        status = ft.AnimatedSwitcher(
            ft.Column([
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.SYNC, color=AMBER),
                    title=ft.Text("Übungs-Teilzahlung"),
                    subtitle=ft.Text("Wartet auf Serverbestätigung"),
                ),
                ft.Text("Bei einer echten Unterbrechung bleibt die Buchung auf dem Gerät gespeichert.", color=MUTED),
            ], key="waiting"),
            duration=300, transition=ft.AnimatedSwitcherTransition.FADE,
        )

        async def demo_sync(_):
            if self.busy or send.disabled:
                return
            send.disabled = close.disabled = True
            status.content = ft.ProgressBar(color=AMBER, key="sending")
            self.page.update()
            await asyncio.sleep(0.75)
            if self.app.training is self and self.app.api:
                status.content = ft.ListTile(
                    key="confirmed", leading=ft.Icon(ft.Icons.CHECK_CIRCLE, color=AMBER),
                    title=ft.Text("Übungsbuchung bestätigt"),
                    subtitle=ft.Text("Bestätigte Buchungen verschwinden aus der Warteschlange."),
                )
                close.disabled = False
                send_frame.visible = False
                if send_frame in self.targets:
                    self.targets.remove(send_frame)
                close_slot.content = self.highlight("queue", close)
                self.page.update()

        def close_queue(_):
            if self.busy:
                return
            self.page.pop_dialog()
            if send_frame in self.targets:
                self.targets.remove(send_frame)
            if not send_frame.visible:
                self.advance("✓  Synchronisierung ausprobiert")

        send = ft.FilledButton("Bestätigung simulieren", on_click=demo_sync)
        close = ft.TextButton("Schließen", on_click=close_queue)
        send_frame = self.highlight("queue", send)
        close_slot = ft.Container(close)
        show_dialog(self.page, "Buchungswarteschlange · Übung", [status], [close_slot, send_frame])

    def guide(self):
        title, instruction, _ = STEPS[self.step]
        compact = self.layout[1]
        final = self.step == len(STEPS) - 1
        show_feedback = bool(self.feedback) and not (compact and (self.active("increase") or self.active("decrease")))
        caption = f"ÜBUNG  ·  {self.step + 1}/{len(STEPS)}  ·  {title}"
        return ft.Container(
            ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.SCHOOL_OUTLINED, color=AMBER, size=20),
                    ft.Text(caption, color=AMBER, size=13, weight=ft.FontWeight.BOLD, expand=True),
                    self.highlight("finish", ft.FilledButton("Fertig", on_click=self.finish)) if final else ft.TextButton(
                        "Später" if self.automatic else "Beenden", on_click=lambda _: self.exit(),
                    ),
                ], spacing=6),
                ft.Text(instruction, size=12 if compact else 14),
                ft.Text(self.feedback, color=AMBER, size=12, visible=show_feedback,
                        max_lines=1 if compact else None, overflow=ft.TextOverflow.ELLIPSIS),
                ft.ProgressBar(value=(self.step + 1) / len(STEPS), color=AMBER, bgcolor=BACKGROUND),
            ], spacing=3),
            padding=ft.Padding.symmetric(horizontal=10, vertical=3 if compact else 8),
            bgcolor="#382D1D", border_radius=12,
        )

    def exit(self):
        if self.app.training is not self:
            return
        if self.pulse_task:
            self.pulse_task.cancel()
        self.app.training = None
        if self.app.api:
            self.app.render()

    async def finish(self, _):
        if self.busy:
            return
        if self.app.data.get("onboarding_pending"):
            self.app.busy = True
            try:
                await self.app.call("complete_onboarding")
            except ApiError as error:
                self.app.notify(str(error))
                return
            finally:
                self.app.busy = False
            self.app.data["onboarding_pending"] = False
        self.exit()


def onboarding(app, *, automatic=False):
    if app.busy or not app.api or app.training:
        return
    app.training = RegisterTraining(app, automatic)
    app.render()
    app.training.pulse_task = app.page.run_task(app.training.pulse)

