# book2md

Liest ein Buch in der lokalen Kindle-App (macOS) Seite für Seite und speichert es als
Markdown-Datei mit klickbarem Inhaltsverzeichnis, Abbildungen und Tabellen. Titel, Autor,
Sprache, Überschriften, Abbildungen und Inhaltsverzeichnis ermittelt das Skript selbst.

Es liest nur, was die App auf dem Bildschirm zeigt. Die Buchdatei wird nicht angefasst.
Gedacht für eigene, gekaufte Bücher und den privaten Gebrauch.

## Aufruf

```
python3 book2md.py BUCH --out DATEI
```

| Argument | Bedeutung |
|---|---|
| `BUCH` | Titel (Anfang genügt, Gross/Klein egal) oder ASIN, z. B. `B0847833Y7` |
| `--out DATEI` | Ziel-Markdown-Datei; Ordner wird angelegt, Datei überschrieben |
| `--author TEXT` | optional: Autor überschreiben; sonst liest das Skript ihn aus dem Bibliothekseintrag in Kindle („Hawkins MD/PHD, David R.“ wird „David R. Hawkins“) |
| `--seiten N` | optional, für einen Testlauf: nur N Seiten ab der aktuellen Seite, ohne Zurückblättern und ohne Cover |

Beispiele:

```
python3 book2md.py "The Map of Consciousness Explained" --out ~/books/map/map.md
```

```
python3 book2md.py B0847833Y7 --seiten 5 --out /tmp/test/map.md
```

## Voraussetzungen

| Was | Getestet mit |
|---|---|
| macOS mit der App „Amazon Kindle“ (`com.amazon.Lassen`) | Kindle 7.25.1 |
| Python 3 | 3.14.5 |
| Pillow (`python3 -m pip install pillow`) | 12.1.0 |
| Tesseract mit Sprachdaten (`brew install tesseract tesseract-lang`) | 5.5.0 |

Einmalig in **Systemeinstellungen > Datenschutz & Sicherheit** für die App, aus der das
Skript startet (z. B. Terminal): **Bedienungshilfen** und **Bildschirmaufnahme** einschalten,
**Automation > System Events** erlauben (macOS fragt beim ersten Lauf), danach Terminal mit
Cmd+Q beenden und neu öffnen.

## Ablauf

1. **Prüfen:** Argumente, Zielordner, Programme. Fehler hier enden mit `Eingabefehler: ...`,
   bevor Kindle angefasst wird.
2. **Buch und Sprache:** Titel oder ASIN werden in einer Kopie der Kindle-Bibliotheksdatenbank
   gesucht; ein exakt passender Titel gewinnt. Die Buchsprache aus der Datenbank bestimmt die
   Texterkennung (`en` → `eng`, `de` → `deu`, ebenso fr, es, it, nl, pt; sonst `eng` mit
   Warnung).
3. **Öffnen:** Zeigt Kindle gerade ein offenes Buch, wechselt das Skript per Escape zur
   Bibliothek (es kann den Titel des offenen Buchs nicht lesen und rät nie). War das Buch schon
   einmal offen, hat es unten in Kindle einen Tab; den drückt das Skript im Hintergrund. Sonst
   drückt es den Eintrag in der Bibliothek, notfalls über die Suche; dafür kommt Kindle für
   einige Sekunden nach vorne, danach bekommt die vorher aktive App den Fokus zurück. Das
   Skript wartet, bis die Seiten wirklich erscheinen (bis 30 s). Kindle öffnet das Buch an der
   zuletzt gelesenen Stelle.
4. **Tastentest:** Das Skript setzt den Fokus auf die Seite und prüft mit einem Pfeil links
   und rechts, ob Kindle umblättert. Die Leseposition
   bleibt dabei gleich. Blättert Kindle auch im zweiten Versuch nicht, bricht das Skript ab,
   ohne etwas zu schreiben, und behält das Bild der stehenden Seite zur Kontrolle.
5. **Zum Anfang:** Pfeil links bis zum Cover; das Skript meldet, wie viele Seiten es
   zurückgeblättert hat. Wird der Anfang nicht erreicht, bricht es ab, statt eine Seite aus der
   Mitte als Cover zu speichern.
6. **Lesen:** Fensterfoto, Pfeil rechts, warten. Bleibt die Seite gleich, wartet das Skript
   erst und schaut neu, dann drückt es ein zweites Mal; erst danach gilt das Buchende als
   erreicht. So geht bei langsamem Umblättern keine Seite verloren. Blendet Kindle seine Leiste
   ein (Kopfzeile, blauer Rahmen, „Page x of y“; das macht es am Ende des Haupttexts und des
   Buchs von selbst), tippt das Skript vor dem Fensterfoto einmal auf die Seite und blendet sie
   so aus. Steht das Bild nur still,
   weil Kindle nicht mehr auf dem sichtbaren Schreibtisch liegt, ist das ein Abbruch, kein
   Buchende. Bleibt es bei einer einzigen Seite, ebenso. Zeigt Kindle nach dem Haupttext sein
   Abschlussfenster (Bewertung, „Recommend this book“, weitere Bücher), schliesst das Skript es
   über dessen Knopf und liest Anhang, Glossar usw. weiter; das Fenster selbst landet nicht im
   Text. Seiten mit diesem Fenstertext verwirft auch die Texterkennung.
7. **Abbildungen:** Auf jeder Seite gilt als Abbildung, was gezeichnet ist, aber nicht zu
   einer sicher erkannten Textzeile gehört: Fotos, Diagramme, Logos und Tabellen (deren
   Gitterlinien bleiben übrig). Bereiche unter 10 % der Seitenbreite oder -höhe zählen nicht.
   Jede Abbildung wird ausgeschnitten, als `img/abbildung-001.png` usw. gespeichert und an
   ihrer Stelle im Lesefluss als `![Abbildung 1](img/abbildung-001.png)` eingesetzt; die
   Texterkennung innerhalb der Abbildung entfällt (dort entstünde nur Zeichensalat).
   Textstellen, die Tesseract gar nicht lesen kann, landen so ebenfalls als Bild im Ergebnis
   statt zu verschwinden.
8. **Texterkennung und Überschriften:** Tesseract liefert Text und Zeilenhöhe; mehrere Seiten
   werden gleichzeitig erkannt. Eine Zeile,
   die mindestens 1,5-mal so hoch ist wie der Fliesstext der Seite, wird Kapitelüberschrift
   (`##`); eine einzelne kurze Zeile in Grossbuchstaben ohne Schlusspunkt wird
   Zwischenüberschrift (`###`). Seiten mit mehreren grossen Zeilen (Titel- und
   Inhaltsverzeichnisseiten) bekommen keine Überschriften. Seitenzahlen fallen weg,
   Silbentrennung wird aufgelöst, Absätze über Seitengrenzen werden verbunden.
9. **Speichern:** Kopf mit Titel, Autor und Inhaltsverzeichnis aus den erkannten
   Überschriften, Cover-Bild, Text mit Abbildungen. Abbildungen eines früheren Laufs im Ordner
   `img` werden ersetzt. Die Datei wird in einem Schritt geschrieben; ein Abbruch
   hinterlässt keine halbe Datei.

Typische Ausgabe bis zur Texterkennung:

```
Buch: The Map of Consciousness Explained: ... (Texterkennung: eng)
Buch geoeffnet.
Tastentest: Kindle blaettert um.
Blaettere zurueck zum Anfang ...
Zurueckgeblaettert: 23 Seiten, Anfang erreicht.
Lese Seiten ...
Gelesen: 312 Seiten, Buchende erreicht.
```

**Während des Laufs** bleibt der Rechner frei. Das Skript holt Kindle nicht nach vorne,
schickt die Pfeiltasten direkt an Kindle und fotografiert nur das Kindle-Fenster. Du kannst
also in anderen Apps arbeiten oder ein Video schauen, mit diesen Regeln:

- Kindle offen lassen: nicht beenden, das Fenster nicht schliessen. Ein ausgeblendetes oder
  ins Dock gelegtes Fenster holt das Skript beim Start zurück (ungetestet).
- Kindle muss auf dem **sichtbaren Schreibtisch** liegen; andere Fenster dürfen darüber
  liegen. Nicht auf einen anderen Schreibtisch (Space) wechseln und keine App im **Vollbild**
  nutzen (auch YouTube nicht im Vollbild-Modus), denn dort blättert Kindle nicht um. Das
  Skript erkennt das und bricht mit Meldung ab.
- In Kindle selbst nicht klicken oder tippen.

Ctrl+C im Terminal bricht sicher ab. **Danach** steht die Kindle-Leseposition auf der zuletzt
gelesenen Seite.

## Was erstellt wird

Für `--out ~/books/map/map.md`:

```
~/books/map/
├── map.md              Titel, Autor, Inhaltsverzeichnis, Cover-Link, Text mit Abbildungen
└── img/
    ├── cover.png       erste Seite als Bild (nicht bei --seiten)
    ├── abbildung-001.png
    └── ...             eine Datei pro Abbildung oder Tabelle, in Buchreihenfolge
```

Während des Laufs liegen die Seitenbilder in `~/books/map/map.seitenbilder/`. Nach Erfolg
wird der Ordner gelöscht. Bricht der Lauf **nach** dem Blättern ab (z. B. in der
Texterkennung), bleibt er erhalten, und derselbe Befehl verwendet ihn beim nächsten Mal weiter,
ohne Kindle. Bricht er **während** des Blätterns ab, wird beim nächsten Mal neu gelesen.

Aufbau von `map.md`:

```
# <voller Titel aus der Kindle-Bibliothek>

*<Autor>*               (aus Kindle oder --author; fehlt er, gibt es eine Warnung)

## Inhalt                (nur wenn Überschriften erkannt wurden)

- [PREFACE](#preface)
  - [THE BENEFITS OF THE MAP OF CONSCIOUSNESS](#the-benefits-of-the-map-of-consciousness)

---

![Cover](img/cover.png)

<Text; Überschriften mit Anker; Abbildungen als ![Abbildung N](img/abbildung-00N.png)>
```

## Ausgabe und Exit-Codes

```
links=4 anchors=4 broken=[] dup=[] leftover_markers=0
Datei: /Users/.../map.md
Seiten: 109 (davon Cover: ja), Ueberschriften: 94, Abbildungen: 30, Woerter: 96755
```

Die erste Zeile ist die Linkprüfung; ist sie nicht sauber, folgt eine `Warnung:`.

| Code | Bedeutung |
|---|---|
| 0 | fertig |
| 1 | Abbruch während des Laufs (`Abbruch in Phase '...'`) |
| 2 | Eingabefehler, Kindle wurde nicht angefasst |
| 3 | Datei geschrieben, aber Buchende nach 3000 Seiten nicht erreicht |

## Fehlermeldungen

Jeder Abbruch nennt die Phase (`Vorpruefung`, `Bibliothek`, `Buch oeffnen`, `Tastentest`,
`Zurueckblaettern`, `Lesen`, `Texterkennung`, `Schreiben`) und die Ursache. Bei einem
unerwarteten Fehler stehen die technischen Details in `fehler.log` im Seitenbilder-Ordner.

| Meldung (Anfang) | Ursache | Abhilfe |
|---|---|---|
| `Eingabefehler: Titel mehrdeutig` | mehrere Bücher beginnen mit dem Titel | längeren Titel oder ASIN aus der Liste |
| `Eingabefehler: Tesseract-Sprache ... nicht installiert` | Sprachdaten fehlen | `brew install tesseract-lang` |
| `Eingabefehler: Programm fehlt` | tesseract fehlt | `brew install tesseract` |
| `Fehlt: Pillow` | Python-Paket fehlt | `python3 -m pip install pillow` |
| `Keine Freigabe 'Bedienungshilfen'` / `'Automation'` | macOS-Freigabe fehlt | Freigabe einschalten, Terminal neu starten |
| `Fensterfoto fehlgeschlagen` | Freigabe Bildschirmaufnahme fehlt | Freigabe einschalten, Terminal neu starten |
| `Das Kindle-Fenster liegt nicht auf dem aktuellen Schreibtisch` | Kindle auf anderem Space oder eine App im Vollbild | Vollbild verlassen bzw. zum Schreibtisch mit Kindle wechseln, denselben Befehl erneut starten |
| `Kindle laeuft nicht mehr` / `Kindle-Fenster nicht gefunden` | Kindle beendet oder Fenster geschlossen | Kindle offen lassen, denselben Befehl erneut starten |
| `Buch ... in der Kindle-Bibliothek nicht gefunden` | Buch in der Bibliotheksansicht nicht sichtbar (Filter, nicht heruntergeladen) | in Kindle Filter `ALL` wählen bzw. Buch herunterladen |
| `Weder Bibliothek noch Leseansicht` | Kindle in unerwartetem Zustand | Kindle neu starten |
| `Kindle zeigt sein Abschlussfenster ... laesst sich nicht schliessen` | Kindle-Fenster nach dem Haupttext ohne Schliessen-Knopf | Fenster in Kindle über den Pfeil oben schliessen, denselben Befehl erneut starten |
| `Kindle blaettert nicht um` | Pfeiltasten wirken nicht (Ursache beim Lauf vom 2026-11-14 ungeklärt) | Bild im genannten Ordner ansehen, denselben Befehl erneut starten |
| `Kindle hat nach der ersten Seite nicht weitergeblaettert` | Tasten wirkten nur beim Test | wie oben |
| `AppleScript antwortet nicht` | Kindle oder System Events hängt | Kindle neu starten |
| `Warnung: Buchende NICHT erreicht` | Buch länger als 3000 Bildschirmseiten | `MAX_PAGES` im Skript erhöhen |

## Dateien

| Datei | Zweck |
|---|---|
| `book2md.py` | Hauptskript; feste Einstellungen (Wartezeiten, Ränder, Schwellen) oben als Konstanten |
| `mdbook.py` | Inhaltsverzeichnis aus den Überschriften, Anker setzen, Links prüfen |
| `tests/test_book2md.py` | Tests ohne Kindle: simulierte App für das Blättern, künstliche Seitenbilder für Texterkennung und Abbildungen |

## Tests

```
python3 tests/test_book2md.py
```

Jede Prüfung meldet `OK` oder `FAIL`; am Ende `ALLE OK` (Exit-Code 0) oder die Liste der
Fehlschläge (Exit-Code 1). Kindle wird dabei nicht angefasst. Eine Prüfung liest die echte
Kindle-Bibliothek und wird übersprungen, wenn das Testbuch dort fehlt.

## Grenzen

- **Überschriften** werden an der Schriftgrösse erkannt. Geprüft an 12 Seiten (Titelei,
  Inhaltsverzeichnis, Vorwort); an Kapitelanfängen im Hauptteil noch nicht. Überschriften in
  normaler Schriftgrösse und gemischter Schreibung erkennt das Skript nicht. Titel bleiben in
  der Schreibung des Buchs (z. B. `PREFACE`).
- **Formatierung:** Kursiv, fett und Infokästen gehen verloren.
- **Abbildungen, Stand 2026-11-14:** geprüft an allen 109 Bildschirmseiten von „The Map of
  Consciousness Explained“ (dunkle Darstellung): Diagramme, Illustration, Logos und alle
  Tabellen gefunden. Tabellen sind Bilder, ihr Inhalt ist also nicht als Text durchsuchbar.
  Eine Abbildung kann eine angrenzende Textzeile mitnehmen. In heller Darstellung ungetestet.
- **„Beliebte Markierungen“ (Popular Highlights):** Kindle unterstreicht viel markierte
  Stellen gepunktet. Diese Zeilen werden zu Buchstabensalat oder als Bild übernommen. Das
  Skript kann die Einstellung nicht selbst ändern (die Reiter im Kindle-Menü sind für die
  Bedienungshilfen unsichtbar). Einmalig in Kindle ausschalten: in einem offenen Buch oben
  „Aa“, Reiter „More“, „Popular Highlights“ aus (Bezeichnung ungeprüft).
- **Texterkennungsfehler:** vereinzelt zusammengezogene Wörter („ona“), Fussnotenzeichen im
  Text, Logos als Buchstabensalat. Der Text ist nicht korrekturgelesen.
- **Fehl-Überschriften:** Offensichtlicher Zeichensalat wird nicht zur Überschrift; vereinzelte Fehl-Überschriften aus normal wirkenden
  Wortresten (z. B. „eigenen OC“ im Lauf vom 2026-11-14) sind möglich. Zeilen, die mit `#` oder
  `>` beginnen, werden maskiert und bleiben Text.
- **Seitenzahlen-Filter:** Eine Zeile nur aus einer Zahl oder kleinen römischen Zahl fällt weg,
  auch eine allein stehende Kapitelnummer.
- **Englische Bindestrichwörter** am Zeilenende werden zusammengezogen („well-known“ wird
  „wellknown“).
- **Ein Buch pro Aufruf.**
- **Hintergrund-Betrieb, Stand 2026-11-14:** Ein Probelauf mit 3 Seiten lief komplett im
  Hintergrund (Terminal vorne, Kindle sichtbar auf dem zweiten Monitor, Öffnen über den Tab).
  Nicht getestet: ein Kindle-Fenster, das **vollständig verdeckt** ist (macOS zeichnet
  verdeckte Fenster möglicherweise nicht neu), das Öffnen über den Bibliothekseintrag im
  echten Lauf und über die Bibliothekssuche.
- **Bis zum Buchende** gelesen am 2026-11-14 (vollständiger Lauf, dazu eine Aufnahme aller
  109 Bildschirmseiten). **Nicht getestet:** die Freigabe-Meldungen mit echtem
  macOS-Fehlertext.
- **Tempo, gemessen 2026-11-14 an 109 Bildschirmseiten (Fenster 1931 Pixel breit):** Blättern
  und Fotos 213 s, Texterkennung mit Abbildungen 210 s bei 4 gleichzeitigen Seiten; dazu etwa
  1 s pro Seite für die Prüfung auf die Kindle-Leiste.
