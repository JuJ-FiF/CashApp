from __future__ import annotations

import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


from .version import APP_VERSION


class ApiError(Exception):
    def __init__(self, message: str, status: int = 0, *, booking_rejected=False):
        super().__init__(message)
        self.status = status
        self.booking_rejected = booking_rejected


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Api:
    def __init__(self, server: str):
        server = server.strip().rstrip("/")
        url = urlsplit(server)
        port = url.port
        local = url.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            not url.hostname or url.username is not None or url.query or url.fragment
            or port == 0 or any(char.isspace() for char in server)
            or (url.scheme != "https" and not (local and url.scheme == "http"))
        ):
            raise ApiError("Gib eine HTTPS-Serveradresse mit optionalem Unterordner ein.")
        self.server = server.removesuffix("/api.php")
        self.endpoint = self.server + "/api.php"
        self.token = ""
        self.opener = build_opener(NoRedirect())

    def call(self, action: str, *, timeout=8, **fields):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"CashApp/{APP_VERSION}",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(
            self.endpoint,
            json.dumps({"action": action, **fields}).encode(),
            headers,
        )
        status = 200
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read()
        except HTTPError as error:
            status = error.code
            redirect = urlsplit(error.headers.get("Location", ""))
            if status in (301, 302, 303, 307, 308) and (
                (redirect.hostname or "").endswith(".cloudflareaccess.com")
                or redirect.path.startswith("/cdn-cgi/access/login")
            ):
                error.close()
                raise ApiError(
                    "Cloudflare Access verlangt eine zusätzliche Anmeldung. "
                    "Die Anfrage hat den CashApp-Server noch nicht erreicht.",
                    status,
                ) from error
            with error:
                try:
                    raw = error.read()
                except (OSError, HTTPException) as read_error:
                    raise ApiError("Die Serverantwort wurde unterbrochen. Bitte erneut versuchen.") from read_error
        except (OSError, URLError, HTTPException) as error:
            raise ApiError("Server zurzeit nicht erreichbar. Bitte erneut versuchen.") from error
        try:
            result = json.loads(raw)
            if isinstance(result, dict) and result.get("ok") is True and status == 200:
                return result["data"]
            if isinstance(result, dict) and isinstance(result.get("error"), str):
                raise ApiError(result["error"], status, booking_rejected=result.get("booking_rejected") is True)
            if isinstance(result, dict) and result.get("cloudflare_error") is True:
                code = result.get("error_code", status)
                raise ApiError(f"Cloudflare hat die Anfrage blockiert (Fehler {code}).", status)
        except (ValueError, KeyError):
            pass
        raise ApiError("Unerwartete Serverantwort. Prüfe die Serveradresse.", status)
