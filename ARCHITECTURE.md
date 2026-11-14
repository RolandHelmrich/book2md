# Architecture

## Technologie

| Komponente | Version (getestet) | Begründung |
|---|---|---|
| Python | 3.14.5 | Standardbibliothek zuerst; macOS-Schnittstellen über `ctypes` statt Zusatzpaketen |
| Pillow | 12.1.0 | Bildzuschnitt, Seitenvergleich, Erkennung von Abbildungen |
| Tesseract | 5.5.0 (Homebrew, mit `tesseract-lang`) | Texterkennung mit Wortpositionen und -höhen (TSV) |
| Kindle für macOS | 7.25.1 | einzige unterstützte Quelle |
| macOS-Werkzeuge | `osascript`, `screencapture`, `pgrep`, `open` | Bedienungshilfen, Fensterfoto, Prozess, Start im Hintergrund |

## Repository-Struktur

```
book2md/
├── .github/workflows/
│   └── joy-merge.yml    # von joy verwaltet: führt joy-Items bei Pull Requests zusammen
├── .joy/                # joy-Projektstand, nur über die joy-CLI ändern
├── .gitattributes       # von joy verwaltet: Merge-Regeln für .joy/
├── ARCHITECTURE.md      # diese Datei
├── CONTRIBUTING.md      # Konventionen
├── README.md            # Bedienung, Ablauf, Fehlermeldungen, Grenzen
├── SECURITY.md          # von joy erzeugt: welche Felder in .joy/ öffentlich sind
├── VISION.md            # Ziele und Abgrenzung
├── book2md.py           # Hauptskript (Ablauf, Kindle-Steuerung, Texterkennung, Abbildungen)
├── mdbook.py            # Inhaltsverzeichnis, Anker, Linkprüfung
└── tests/
    └── test_book2md.py  # Tests ohne Kindle
```

Nicht im Repo (per `.gitignore`): `.claude/` mit der KI-Konfiguration, lokal erzeugt von
`joy ai init`, sowie lokale joy-Dateien (`.joy/config.yaml`, `.joy/credentials.yaml`,
`.joy/hooks/`) und `*.seitenbilder/`.

## Ablauf und Komponenten

`book2md.py` arbeitet in Phasen; jeder Abbruch nennt seine Phase.

1. **Vorprüfung:** Argumente, Zielordner, Programme
2. **Bibliothek:** Titel und Sprache aus einer Kopie von Kindles `BookData.sqlite`
3. **Buch öffnen:** über die Bedienungshilfen (AppleScript); Tab des Buchs im Hintergrund,
   sonst Bibliothekseintrag mit kurzem Vordergrund; Autor aus dem Bibliothekseintrag
4. **Tastentest, Zurückblättern, Lesen:** Pfeiltasten per `CGEventPostToPid` direkt an
   Kindle, Fensterfoto per `screencapture -l <Fenster-ID>`; Seitenwechsel durch
   Bildvergleich
5. **Texterkennung:** Tesseract-TSV je Seite, mehrere Seiten parallel in Threads
6. **Schreiben:** Markdown über `mdbook.py`, Abbildungen nach `img/`, Datei in einem Schritt

## Datenablage

- Keine Datenbank. Kindles `BookData.sqlite` wird nur gelesen, und zwar als Kopie.
- Ausgabe dort, wo `--out` hinzeigt: `<name>.md` und `img/` (Cover, `abbildung-NNN.png`).
- Während eines Laufs: `<name>.seitenbilder/` neben der Ausgabe mit `page-NNNN.png`,
  `lauf.json` (Titel, Autor, Status, Buchende erreicht) und bei Bedarf `fehler.log`. Nach
  Erfolg gelöscht; nach einem Abbruch in der Texterkennung wiederverwendet.

## Architekturentscheidungen

Stand 2026-11-14, noch nicht als joy-Decisions erfasst; neue Entscheidungen werden
joy-Decision-Items (`joy ls -D -a`).

- **Hintergrund-Betrieb:** Tasten an die Prozess-ID, Foto nur des Kindle-Fensters. Grenze:
  Kindle muss auf dem sichtbaren Schreibtisch liegen; auf einem anderen Space blättert es
  nicht um, was das Skript erkennt und meldet.
- **Überschriften aus der Zeilenhöhe** (ab 1,5-mal Fliesstext) und aus kurzen Zeilen in
  Grossbuchstaben; Titel- und Inhaltsverzeichnisseiten werden ausgenommen.
- **Abbildungen = gezeichneter Inhalt ausserhalb sicher erkannter Textzeilen**; Tabellen
  werden als Bild übernommen, weil ihre Texterkennung nur Zeichensalat ergibt.
- **Störungen der App werden über die Bedienungshilfen erkannt:** Abschlussfenster
  („Recommend this book“, Knopf „Close“), Leiste („Close Book“, Tippen blendet aus).
- **Keine Buchinhalte im Repo:** Tests arbeiten mit einer simulierten App und künstlichen
  Seitenbildern.

## Leistung

Kein Ziel festgelegt. Gemessen am 2026-11-14 an 109 Bildschirmseiten (Fenster 1931 Pixel
breit): Blättern und Fotos 213 s, Texterkennung mit Abbildungen 210 s bei 4 parallelen
Seiten, Prüfung auf die Kindle-Leiste etwa 1 s pro Seite.
