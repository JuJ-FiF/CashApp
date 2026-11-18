# CashApp

Flet-Kasse mit PHP-API, SQLite und einer mobilen Gastansicht. Kasse und Gastansicht verwenden dieselbe Datenbank. Die App orientiert sich an BeverageOrganiser und FootballTasker mit Flet 1.0.3, dunklem Amber-Theme, AppBar und NavigationRail.

## Lokale Entwicklung

Voraussetzungen sind Python ab 3.11 sowie PHP ab 8.2 mit PDO SQLite und Sessions. Die folgenden Befehle sind für PowerShell und werden aus dem CashApp-Projektordner ausgeführt.

In einem Terminal PHP starten. Der Admin wird beim ersten Initialisieren angelegt. Das Passwort über eine lokale Umgebungsvariable setzen und nach der Initialisierung entfernen.

```powershell
$env:TRESEN_DB = Join-Path (Get-Location).Path 'server/cashapp-local.sqlite'
$env:TRESEN_LOCAL = '1'
$env:TRESEN_ADMIN_PASSWORD = Read-Host 'Neues Admin-Passwort (8–72 Bytes)' -MaskInput
php server/manage.php init Admin
Remove-Item Env:TRESEN_ADMIN_PASSWORD
php -S 127.0.0.1:8080 -t server/public
```

Im zweiten Terminal die App starten.

```powershell
python -m pip install -e .
flet run
```

Für die lokale Entwicklung in einer frischen App-Konfiguration vor dem Start `$env:CASHAPP_URL = 'http://127.0.0.1:8080'` setzen. Beim Login `Admin` und das gewählte Passwort eingeben. Einen Artikel anlegen, einen Warenkorb auf einen neuen Deckel buchen und über **Deckel → Kundenkonto freigeben** Benutzername und Einmalcode erzeugen. Der Kunde aktiviert den Zugang unter **Mein Deckel → Konto zum ersten Mal aktivieren** und legt sein Passwort selbst fest. Der Einmalcode gilt sieben Tage und ist nur einmal nutzbar.

Die Kasse speichert die Serveradresse in `settings.json` im App-Datenordner von Flet. Beim Start aus dem Quellprojekt unter Windows ist der Ersatzpfad `%LOCALAPPDATA%\CashApp\settings.json`. Bestehende Quellinstallationen lesen ihre Einstellungen und Warteschlange weiter aus dem bisherigen Datenordner. Angemeldete Admins können die Adresse unter **Einstellungen → Serververbindung** ändern. Bei einem Wechsel wird die laufende Sitzung beendet und eine Neuanmeldung nötig. Artikel, Konten, Deckel, bestätigte Buchungen und Abschlüsse liegen in der SQLite-Datenbank auf dem Server. Auf dem Gerät hält `bookings.sqlite` ausstehende Buchungen fest. Ein noch nicht bestätigter Warenkorb vor dem Auslösen einer Buchung und der Sitzungsschlüssel liegen im Arbeitsspeicher.

`main.py` startet die Kassen-App. `Screens/` enthält die Ansichten und Dialoge, `Utils/` die API-Anbindung, Einstellungen und Formatierung. `server/` enthält die PHP-Komponenten für den Raspberry Pi.

Das Layout ist für Tablets und Handys im Querformat ausgelegt. Artikelraster und Warenkorb scrollen getrennt, die Zahlungsbuttons bleiben im Warenkorb sichtbar. Für den Android-Build nutzt CashApp wie die anderen Flet-Apps die lokale Vorlage `NoAndroidNavBar`. Der Netzwerkzugriff ist im Build als `android.permission.INTERNET` konfiguriert.

## Bereitstellung im Webhosting

```text
/DATA/AppData/webhosting/
  sites/
    kasse/
      public/         Dokumentenstamm
        index.php     aus server/public/
        api.php       aus server/public/
        guest.css     aus server/public/
      data/
        app.sqlite    SQLite-Datenbank
        bootstrap.php aus server/
        manage.php    aus server/
        schema.sql    aus server/
```

- Die PHP-Einstiegspunkte laden `../data/bootstrap.php`. Das Backend öffnet `app.sqlite` im selben privaten Verzeichnis. Der PHP-Worker braucht Schreibrechte für die Datenbank und ihren Ordner. Der Dokumentenstamm bleibt für den PHP-Worker schreibgeschützt. `TRESEN_DB` kann einen separaten Datenbankpfad vorgeben. Im Hostingbetrieb bleibt `TRESEN_LOCAL` ungesetzt.
- Falls `index.php` oder `app.sqlite` bereits Inhalte enthalten, zuerst sichern. Die Initialisierung von CashApp zunächst mit einer leeren Datenbank oder einer Kopie einer bestehenden CashApp-Datenbank prüfen.
- `php manage.php init Admin` im privaten Verzeichnis `/var/www/sites/kasse/data` des Containers ausführen. Beim ersten Start das temporäre `TRESEN_ADMIN_PASSWORD` setzen und danach entfernen.
- `sites/kasse/public` als Dokumentenstamm konfigurieren, den `Authorization`-Header an PHP durchreichen und das serverseitige `HTTPS`-Flag setzen. In der Flet-App die öffentliche HTTPS-Adresse eintragen. Ist die Seite unter `/kasse/` erreichbar, gehört dieser Pfad zur Adresse. Die App ergänzt `/api.php` selbst.
- Dieselbe öffentliche Adresse auf der bestehenden Seite unter **Mein Deckel** verlinken. Die Gäste verwenden ihre vom Admin vergebenen Zugangsdaten.

## Bedienung

- **Kasse** · Kategorien, Warenkorb, Barverkauf mit Rückgeld und Buchen auf neue oder bestehende Deckel. Im Dialog **Auf Deckel** nach Name oder Deckelnummer suchen. Über **Artikel sortieren** lassen sich zwei Kachelpositionen per Drag-and-drop tauschen. Die persönliche Reihenfolge wird je Konto gespeichert. Bei einem Server ohne diese Funktion speichert das Gerät die Reihenfolge je Server und Konto lokal.
- **Deckel** · Buchungen und Restsaldo. Deckelnamen sind eindeutig und können vom Personal geändert werden. Admins können Deckel löschen. Dabei storniert CashApp den noch offenen Betrag mit Gegenbuchungen, hebt den Kundenzugang auf und entfernt den Deckel aus der Auswahl. Bereits geleistete Zahlungen und die Buchungshistorie bleiben erhalten. Direktverkäufe werden komplett bar bezahlt.
- **Artikel und Personal** · Admins pflegen die Artikelstammdaten und verwalten Personal. Jedes Personalkonto kann über **Persönliche Kategorie** die Kategorie eines Artikels für seine eigene Kassenansicht festlegen. Ein leeres Feld setzt sie auf den Standard zurück. Unter **Personal** können Admins andere Personalkonten sperren, deren Passwörter zurücksetzen oder die Konten aus dem aktiven Personalbestand löschen. Historische Buchungen behalten ihre Zuordnung. Personal und Gäste können denselben Benutzernamen verwenden. Gastkonten sehen ausschließlich ihren zugeordneten Deckel.
- **Tagesabrechnung** · CashApp gruppiert Verkäufe und Netto-Barzahlungen automatisch je Kalendertag in der Zeitzone Europe/Berlin. Der Tageswechsel erfolgt um Mitternacht. Offene Deckel bleiben über den Tageswechsel bestehen. Der offene Gesamtsaldo zeigt den aktuellen Stand. Frühere manuelle Abschlüsse bleiben zur Nachvollziehbarkeit in der Datenbank.
- **Gerätesperre** · Es kann genau eine App-Sitzung gleichzeitig kassieren. Bei **Abmelden** und beim regulären Schließen des Desktopfensters sendet die App eine Abmeldung. Auf Mobilgeräten versucht sie das beim Beenden, sofern das Betriebssystem noch ein Ereignis zustellt. Bei einem Ausfall läuft die Sperre spätestens 60 Sekunden nach dem letzten erfolgreichen Kontakt aus. Gastzugriffe bleiben unabhängig davon möglich.
- **Einstellungen** · Serveradresse, Kachelgröße und Anzeige ausgeglichener Deckel werden auf dem Gerät gespeichert. Unter **Administration** können Admins Buchungen nach Buchungsnummer oder für einen inklusiven Datumsbereich dauerhaft löschen. In der Tagesabrechnung lässt sich die Einzelvorschau direkt an der Buchungszeile öffnen. Ein zugehöriges Storno steht mit in der Vorschau. Nach der Vorschau ist die Eingabe von **LÖSCHEN** erforderlich. CashApp prüft die verbleibenden Deckelsalden. Der Löschvorgang und Sperrmerkmale für alte Offline-Anfragen bleiben nachvollziehbar. Vorhandene Sicherungen werden durch den Vorgang nicht geändert.
- **Einweisung** · Neu angelegte Personalkonten sehen beim ersten Login einen interaktiven Übungsmodus mit goldenen Markierungen direkt in Kasse und Deckelansicht. Barverkauf, Deckelbuchung, Teilzahlung und Synchronisierung laufen mit separaten Beispieldaten. Danach vergibt das Personal eine eigene Kategorie und probiert den Filter aus. Zum Schluss blendet es alle Artikel wieder ein und verschiebt die Kacheln per Drag-and-drop. CashApp merkt sich den Abschluss pro Konto. Über **Einstellungen → Einweisung** lässt sie sich erneut öffnen.
- **Verbindung** · Die Anmeldung benötigt den Server. Bei **Bestätigen** legt die App jede Buchung zuerst mit fester Buchungskennung und Erfassungszeit in der lokalen Warteschlange ab. Bei aktiver Kassensitzung versucht sie den Versand im Hintergrund alle 15 Sekunden und sofort beim Zurückkehren in die App. Beim nächsten Login sendet sie offene Buchungen ebenfalls erneut. Der Server erkennt wiederholte Buchungskennungen und ordnet nachgereichte Buchungen dem erfassten Kalendertag zu. Eine fachlich abgelehnte Buchung bleibt zur Prüfung sichtbar.

## App-Updates

Unter **Einstellungen → App-Updates** prüft CashApp das neueste öffentliche GitHub-Release von `JuJ-FiF/CashApp`. Android öffnet für die APK den nativen Installer. Unter Windows wird der Ablauf simuliert. Für ein Update müssen APK-Paket-ID und Signatur zur installierten App passen.

## Sicherung und Wiederherstellung

`php manage.php backup /privater/pfad/cashapp-sicherung.sqlite` erstellt eine konsistente SQLite-Kopie. Zur Wiederherstellung einen neuen Datenbankpfad mit einer Kopie der Sicherung vorbereiten und ihn bei gestoppten PHP-Prozessen als `TRESEN_DB` konfigurieren. Vor dem Wechsel die aktuelle Datenbank sichern. Nach Wiederanlauf den letzten Abschluss und einen Deckelsaldo prüfen.

