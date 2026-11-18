import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def settings_file():
    storage = os.getenv("FLET_APP_STORAGE_DATA")
    if storage:
        return Path(storage) / "settings.json"
    root = Path(os.getenv("LOCALAPPDATA") or os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config")
    legacy = root / "Tresen"
    current = root / "CashApp"
    # Existing source installations keep their settings and SQLite queue together.
    if not current.exists() and any((legacy / name).exists() for name in ("settings.json", "bookings.sqlite")):
        return legacy / "settings.json"
    return current / "settings.json"


def load_settings():
    try:
        data = json.loads(settings_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_server(default):
    server = load_settings().get("server")
    return server if isinstance(server, str) and server.strip() else default


def save_server(server):
    save_settings({**load_settings(), "server": server})


def local_product_order(server, username):
    layouts = load_settings().get("product_orders", {})
    order = layouts.get(f"{server}\n{username}", []) if isinstance(layouts, dict) else []
    return [item for item in order if type(item) is int] if isinstance(order, list) else []


def save_local_product_order(server, username, order):
    data = load_settings()
    layouts = data.get("product_orders")
    if not isinstance(layouts, dict):
        layouts = {}
    layouts[f"{server}\n{username}"] = order
    save_settings({**data, "product_orders": layouts})


def save_settings(data):
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temp = Path(file.name)
            json.dump(data, file)
        temp.replace(path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
