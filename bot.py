#!/usr/bin/env python3
"""Tägliche DAV-Bibliothekssuche und Ergebnisversand per GMX-SMTP."""

from __future__ import annotations

import argparse
from datetime import datetime
from email.message import EmailMessage
import os
from pathlib import Path
import re
import smtplib
import ssl
import sys
from zoneinfo import ZoneInfo

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

URL = "https://www.stuttgart-alpin.de/bibliothek"
QUERY_1 = os.getenv("DAV_SUCHBEGRIFF_1", "Alpin-Lehrplan")
QUERY_2 = os.getenv("DAV_SUCHBEGRIFF_2", "Skibergsteigen")
RECIPIENT = os.getenv("EMAIL_TO", "csmitty@gmx.net")
OUT_DIR = Path(os.getenv("OUTPUT_DIR", "ausgabe"))
TZ = ZoneInfo("Europe/Berlin")


def _first_visible(locator):
    for i in range(min(locator.count(), 20)):
        item = locator.nth(i)
        if item.is_visible():
            return item
    raise RuntimeError("Kein sichtbares Eingabefeld/Steuerelement gefunden")


def _search_input_after(page, label: str):
    """Das Eingabefeld unmittelbar nach der Beschriftung auswählen."""
    match = page.get_by_text(label, exact=True)
    for i in range(min(match.count(), 10)):
        target = match.nth(i).locator(
            "xpath=following::input[not(@type='hidden') and not(@type='submit')][1]"
        )
        if target.count() and target.first.is_visible():
            return target.first
    raise RuntimeError(f"Suchfeld hinter '{label}' nicht gefunden – Seite geändert?")


def _select_title_subtitle(page, label_locator):
    """Die Suche auf Titel und Untertitel beschränken."""
    try:
        select = label_locator.locator("xpath=following::select[1]").first
        if not select.is_visible():
            raise RuntimeError("Auswahlfeld nicht sichtbar")
        opts = select.locator("option")
        candidates = [(opts.nth(i).get_attribute("value"), opts.nth(i).inner_text().strip())
                      for i in range(opts.count())]
        # Vorrang hat die tatsächliche Kombination aus Titel und Untertitel.
        matches = [(value, text) for value, text in candidates
                   if "titel" in text.lower() and "untertitel" in text.lower()]
        if not matches:
            raise RuntimeError("Option 'Titel, Untertitel' fehlt")
        select.select_option(value=matches[0][0])
    except Exception as exc:
        raise RuntimeError(f"Suchbereich 'Titel, Untertitel' nicht einstellbar: {exc}") from exc


def _set_search_areas(page):
    labels = page.get_by_text("suchen in:", exact=True)
    if labels.count() < 2:
        raise RuntimeError("Die zwei Dropdowns 'suchen in:' wurden nicht gefunden")
    _select_title_subtitle(page, labels.nth(0))
    _select_title_subtitle(page, labels.nth(1))


def _click_search(page):
    # Button, input[type=submit] und ein möglicher Link sind abgedeckt.
    button = page.get_by_role("button", name=re.compile(r"^\s*Suchen\s*$", re.I))
    if button.count():
        _first_visible(button).click(timeout=10000)
        return
    submit = page.locator('input[type="submit"][value="Suchen"]')
    if submit.count():
        _first_visible(submit).click(timeout=10000)
        return
    text_button = page.get_by_text("Suchen", exact=True)
    if text_button.count():
        _first_visible(text_button).click(timeout=10000)
        return
    raise RuntimeError("Der Such-Button wurde nicht gefunden")


def _parse_results(visible_text: str):
    # Der Trefferzähler ist im DAV-Katalog als z.B. '12 Treffer' dargestellt.
    matches = list(re.finditer(r"(?m)^\s*([\d.,]+)\s+Treffer\s*$", visible_text))
    if not matches:
        raise RuntimeError("Trefferzähler nicht gefunden. Suche ggf. fehlgeschlagen.")
    match = matches[-1]
    count = int(re.sub(r"\D", "", match.group(1)))
    details = visible_text[match.end():]
    for stop in ("Hier können Medien zum Druck", "Reservierung nur für"):
        pos = details.find(stop)
        if pos >= 0:
            details = details[:pos]
    details = details.strip()
    pages = re.search(r"Seite\s+(\d+)\s+von\s+(\d+)", details, re.I)
    page_number, total_pages = (int(pages.group(1)), int(pages.group(2))) if pages else (1, 1)
    if count and not details:
        raise RuntimeError("Trefferzahl vorhanden, aber keine Ergebnisliste lesbar")
    return count, details, page_number, total_pages


def _try_increase_per_page(page):
    """Falls ein 'je Seite'-Dropdown vorhanden ist, möglichst viele Treffer anzeigen."""
    label = page.get_by_text("je Seite", exact=True)
    if not label.count():
        return
    candidates = label.first.locator("xpath=preceding::select[1]")
    if not candidates.count() or not candidates.first.is_visible():
        candidates = label.first.locator("xpath=following::select[1]")
    if not candidates.count() or not candidates.first.is_visible():
        return
    select = candidates.first
    options = select.locator("option")
    numbered = []
    for i in range(options.count()):
        o = options.nth(i)
        shown = o.inner_text().strip()
        value = o.get_attribute("value")
        if shown.isdigit():
            numbered.append((int(shown), value))
    if numbered:
        _, selected_value = max(numbered)
        select.select_option(value=selected_value)
        page.wait_for_timeout(1400)


def run_search() -> tuple[int, str, str, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    screenshot = OUT_DIR / "dav-suchergebnis.png"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale="de-DE", timezone_id="Europe/Berlin", viewport={"width": 1280, "height": 850})
            response = page.goto(URL, wait_until="domcontentloaded", timeout=45000)
            if response and response.status >= 400:
                raise RuntimeError(f"DAV-Seite antwortet mit HTTP {response.status}")
            try:
                initial_count = _parse_results(page.locator("body").inner_text())[0]
            except RuntimeError:
                initial_count = None
            _search_input_after(page, "Suchen nach:").fill(QUERY_1)
            _search_input_after(page, "und (optional):").fill(QUERY_2)
            _set_search_areas(page)
            _click_search(page)
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except PlaywrightTimeoutError:
                pass  # Seiten mit Daueranfragen erreichen networkidle evtl. nie.
            page.wait_for_timeout(1700)
            _try_increase_per_page(page)
            page.wait_for_timeout(900)
            # Fehler vermeiden, wenn etwa ein Captcha / eine Login-Seite erscheint.
            content = page.locator("body").inner_text(timeout=15000)
            count, details, current_page, total_pages = _parse_results(content)
            if initial_count is not None and initial_count > 500 and count == initial_count:
                raise RuntimeError("Trefferzahl ist unverändert: Suchfilter offenbar nicht aktiv")
            if _search_input_after(page, "Suchen nach:").input_value() != QUERY_1:
                raise RuntimeError("Der erste Suchbegriff wurde nicht übernommen")
            if _search_input_after(page, "und (optional):").input_value() != QUERY_2:
                raise RuntimeError("Der zweite Suchbegriff wurde nicht übernommen")
            # Zur Nachvollziehbarkeit zusätzlich die angezeigte Seite als Bild beilegen.
            page.screenshot(path=str(screenshot), full_page=True, animations="disabled", timeout=25000)
            pagination = f"Seite {current_page} von {total_pages}"
            if total_pages > 1:
                pagination += " (die E-Mail enthält nur die aktuell angezeigte Seite; weitere Treffer im Katalog)"
            return count, details, pagination, screenshot
        finally:
            browser.close()


def _send(subject: str, body: str, attachment: Path | None = None):
    username = os.getenv("GMX_USERNAME", "").strip()
    password = os.getenv("GMX_PASSWORD", "")
    if not username or not password:
        raise RuntimeError("GMX_USERNAME/GMX_PASSWORD fehlen (GitHub-Secrets anlegen)")
    msg = EmailMessage()
    msg["From"] = username
    msg["To"] = RECIPIENT
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment and attachment.is_file() and attachment.stat().st_size < 12 * 1024 * 1024:
        msg.add_attachment(attachment.read_bytes(), maintype="image", subtype="png", filename=attachment.name)
    with smtplib.SMTP_SSL("mail.gmx.net", 465, context=ssl.create_default_context(), timeout=25) as smtp:
        smtp.login(username, password)
        smtp.send_message(msg)


def main():
    parser = argparse.ArgumentParser(description="DAV-Bibliothek täglich prüfen und Ergebnis mailen")
    parser.add_argument("--ohne-email", action="store_true", help="Testlauf: Bericht speichern, keine E-Mail senden")
    parser.add_argument("--test-email", action="store_true", help="Nur SMTP-Testmail senden")
    args = parser.parse_args()
    now = datetime.now(TZ).strftime("%d.%m.%Y %H:%M %Z")
    if args.test_email:
        _send("DAV-Bibliotheksbot: Test-E-Mail", "GMX-SMTP-Versand funktioniert.")
        print("Test-E-Mail verschickt")
        return

    try:
        count, details, pagination, screenshot = run_search()
        body = (
            f"DAV Alpinbibliothek Stuttgart – Abfrage vom {now}\n\n"
            f"1. Suchen nach: {QUERY_1} (Titel, Untertitel)\n"
            f"2. UND: {QUERY_2} (Titel, Untertitel)\n\n"
            f"Treffer insgesamt: {count}\n{pagination}\n\n"
            f"ANGEZEIGTE ERGEBNISSE:\n\n{details if count else 'Keine Treffer.'}\n\n"
            f"Katalog: {URL}\n\n"
            "Ein Bildschirmfoto der Ergebnisse ist angehängt, sofern klein genug.\n"
            "Der Katalog kann sich ändern; die Abfrage legt nichts in den Medienkorb und reserviert nichts.\n"
        )
        OUT_DIR.mkdir(exist_ok=True, parents=True)
        (OUT_DIR / "bericht.txt").write_text(body, encoding="utf-8")
        print(f"Suche erfolgreich: {count} Treffer; {pagination}")
        if not args.ohne_email:
            _send(f"DAV-Bibliothek: {count} Treffer – {now[:10]}", body, screenshot)
            print(f"Ergebnis an {RECIPIENT} verschickt")
    except Exception as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        if not args.ohne_email:
            try:
                _send("DAV-Bibliotheksbot: Suche fehlgeschlagen",
                      f"Die DAV-Bibliotheksabfrage vom {now} konnte nicht abgeschlossen werden.\n\n"
                      f"Suchbegriffe: {QUERY_1} UND {QUERY_2}\n"
                      f"Fehler: {type(exc).__name__}: {exc}\n\nQuelle: {URL}\n")
            except Exception as mail_exc:
                print(f"Auch die Fehler-E-Mail konnte nicht gesendet werden: {mail_exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
