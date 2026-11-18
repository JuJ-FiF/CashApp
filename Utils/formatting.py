from datetime import datetime, timezone
import re


def euro(cents):
    return f"{int(cents) / 100:,.2f}".translate(str.maketrans(",.", ".,")) + " €"

def amount(value):
    value = (value or "").strip()
    if not re.fullmatch(r"[0-9]{1,7}(?:[,.][0-9]{1,2})?", value):
        raise ValueError("Bitte einen Eurobetrag mit höchstens zwei Nachkommastellen eingeben.")
    euros, _, fraction = value.replace(",", ".").partition(".")
    cents = int(euros) * 100 + int(fraction.ljust(2, "0"))
    if cents > 100000000:
        raise ValueError("Der Betrag überschreitet den Höchstbetrag.")
    return cents


def cash_received(value, due):
    received = amount(value)
    if received < due:
        raise ValueError("Der gegebene Barbetrag ist kleiner als der zu zahlende Betrag.")
    return received

def local_time(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).astimezone().strftime("%d.%m.%Y · %H:%M")
