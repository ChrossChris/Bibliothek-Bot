# DAV-Alpinbibliothek: täglicher E-Mail-Bot

Der Bot durchsucht `https://www.stuttgart-alpin.de/bibliothek` täglich nach:

- `Alpin-Lehrplan` in **Titel, Untertitel**
- **UND** `Skibergsteigen` in **Titel, Untertitel**

Er sendet die Zahl der Treffer, den auf der Suchergebnisseite angezeigten Text
und ein Bildschirmfoto an `csmitty@gmx.net`. Auch bei null Treffern erfolgt eine E-Mail.
Der Bot reserviert **keine** Medien. Falls die Suche fehlschlägt, wird versucht,
eine Fehlermeldung zu mailen.

## Einrichtung auf GitHub (ohne dauernd laufenden eigenen Rechner)

1. Ein **privates** Repository auf https://github.com/new erstellen, z. B. `dav-bibliothek-bot`.
2. Die Dateien und den versteckten Ordner `.github/workflows/` genauso wie im ZIP
   ins Repository hochladen. Der Workflow muss auf dem **Standardbranch** liegen.
3. Im Repository **Settings → Secrets and variables → Actions** öffnen und
   zwei *Repository secrets* anlegen:
   - `GMX_USERNAME` = deine GMX-Absenderadresse (z. B. `csmitty@gmx.net`)
   - `GMX_PASSWORD` = dein **GMX-App-Passwort**, falls 2-Faktor-Authentifizierung aktiviert ist,
     sonst das für SMTP gültige Passwort. Nichts davon in die Dateien schreiben.
4. In GMX ggf. unter E-Mail-Einstellungen **POP3/IMAP** bzw. Zugriff durch externe
   E-Mail-Programme aktivieren.
5. Unter **Actions → DAV Alpinbibliothek – tägliche Suche → Run workflow**
   einen **einmaligen Testlauf** starten.
6. Bei erfolgreicher Ausführung wird der Bot jeden Tag um **08:15 Europe/Berlin**
   ausgeführt (GitHub kann einzelne geplante Jobs verzögert starten).

**Sicherheit:** Das GMX-Passwort niemals in den Quellcode, Issues, Screenshots oder Chat kopieren.
Für ein privates Repository werden ggf. die GitHub-Actions-Nutzungsgrenzen deines Tarifs
angewendet.

## Optional: lokal testen

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
python bot.py --ohne-email
```

Dadurch werden ein Bericht und ein Screenshot in `ausgabe/` angelegt, aber **keine** E-Mail gesendet.
Für einen SMTP-Test kann man anschließend die Umgebungsvariablen `GMX_USERNAME`
und `GMX_PASSWORD` lokal setzen und `python bot.py --test-email` aufrufen.

## Anpassungen

- Uhrzeit ändern: `.github/workflows/taeglich.yml`, Feld `cron` (`15 8 * * *`).
- Empfängeradresse ändern: Workflowvariable `EMAIL_TO`.
- Suchwörter ändern: `DAV_SUCHBEGRIFF_1` und `DAV_SUCHBEGRIFF_2`.

## Grenzen / Hinweis

Der Browsercode ist auf die beiden sichtbaren Suchfelder und Dropdowns der
DAV-Bibliotheksseite ausgelegt. **Die Live-Suche konnte in dieser Umgebung nicht
vollständig getestet werden.** Wenn DAV das Layout oder die zugrunde liegende
Suchfunktion ändert, müssen die Selektoren eventuell angepasst werden. Falls
mehrere Ergebnisseiten entstehen, enthält die E-Mail die Trefferzahl und die
angezeigte (möglichst umfangreiche) Seite; die Pagination wird ausdrücklich
gekennzeichnet. Der Bot umgeht keine Zugriffssperren oder Captchas.
