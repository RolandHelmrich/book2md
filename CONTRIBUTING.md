# Contributing

## Konventionen

- Code, Bezeichner, Kommentare und Docstrings auf Englisch; Datei- und Ordnernamen
  englisch in kebab-case oder als kurzes Wort (`book2md.py`, `mdbook.py`)
- Meldungen an den Nutzer auf Deutsch, im Code ohne Umlaute (`Zurueckblaettern`)
- Dokumentation (README, VISION, ARCHITECTURE, dieses Dokument) und joy-Items auf Deutsch
- Stil wie im bestehenden Code (PEP 8, Zeilen bis 100 Zeichen); kein Linter konfiguriert
- Feste Werte als Konstanten oben in `book2md.py`, nicht als Argumente
- Kommentare nur, wo der Grund nicht aus dem Code hervorgeht; gemessene Werte mit Datum
- Keine Emojis

## Commits

Präfix auf Englisch, Beschreibung auf Deutsch, mit Verweis auf ein joy-Item:

```
fix: Abschlussfenster vor dem Buchende schliessen [BKMD-0001-xx]
```

Präfixe: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`. `[no-item]` nur für
Infrastruktur-Commits ohne passendes Item. Der joy-Hook (`.joy/hooks/commit-msg`) lehnt
Nachrichten ohne Item-Verweis und ohne `[no-item]` ab.

Commits, die ein KI-Mitglied im Auftrag macht, enden mit `Delegated-By: <Adresse aus der
Token-Einlösung>` (siehe `.claude/CLAUDE.md`); ein `Co-Authored-By` des KI-Werkzeugs ist
erlaubt, aber nicht verlangt.

Nie committen: Buchtext, Seitenbilder, Ausgaben echter Bücher, `*.seitenbilder/`.

## Tests

```
python3 tests/test_book2md.py
```

- Läuft ohne Kindle: simulierte App für das Blättern, künstliche Seitenbilder für
  Texterkennung und Abbildungen; Exit-Code 0 nur, wenn alle Prüfungen bestehen
- Jede Änderung am Verhalten bekommt eine Prüfung; vor jedem Commit alle Tests grün
- Verhalten der echten Kindle-App (Fenster, Tasten, Bedienungshilfen) wird zusätzlich live
  geprüft, mit einem Probelauf `--seiten N`, und das Ergebnis in README oder Item festgehalten

## CI/CD

Keine Test-Pipeline: Die Tests brauchen macOS mit Tesseract und laufen lokal.

joy hat `.github/workflows/joy-merge.yml` angelegt und verwaltet es selbst. Der Workflow
läuft nur bei Pull Requests und führt dort joy-Items zusammen; bei Arbeit direkt auf `main`
startet er nicht.

## Branches

Trunk-based auf `main`, kleine Commits. git (commit, push) bedient ausschliesslich der
Eigentümer; Claude liefert die Befehle.
