# Vision

## Was ist book2md?

book2md macht aus einem Buch, das man besitzt, eine gegliederte Markdown-Datei: Text,
Überschriften mit klickbarem Inhaltsverzeichnis, Abbildungen und Tabellen als Bilder. Es
liest das Buch so, wie eine Lese-App es auf dem Bildschirm zeigt, und erzeugt das Ergebnis
ohne Handarbeit.

## Zielgruppe

- Der Eigentümer des Repos, für die eigene, private Bibliothek gekaufter Bücher
  (Ablage der Ergebnisse ausserhalb dieses Repos)

## Kernfunktionen

- Ein Aufruf pro Buch: `book2md.py BUCH --out DATEI`; Titel, Autor, Sprache, Überschriften,
  Inhaltsverzeichnis und Abbildungen ermittelt das Werkzeug selbst
- Läuft im Hintergrund; der Rechner bleibt während des Lesens nutzbar
- Erkennt und überwindet Störungen der Lese-App (Abschlussfenster, eingeblendete Leiste,
  langsames Umblättern) und meldet jeden Abbruch mit Phase und Ursache
- Nach einem Abbruch in der Texterkennung setzt derselbe Befehl ohne erneutes Blättern fort
- Abbildungen und Tabellen werden ausgeschnitten und an ihrer Stelle im Text eingesetzt

## Gestaltungsprinzipien

- Vollautomatisch: Das Werkzeug gibt dem Nutzer keine Vorarbeit auf; was es selbst
  ermitteln kann, ermittelt es, und feste Werte sind Konstanten, keine Argumente
- Reines Python: Inhalte entstehen nur durch das Skript, nicht durch Handarbeit oder eine KI
- Nachvollziehbar: Jeder Fehler nennt Phase, Ursache und Abhilfe; nichts endet still mit
  einem halben Ergebnis
- Lieber Abbruch als stiller Datenverlust
- Kleinste Änderung, die wirkt; jede Annahme über die Lese-App wird live geprüft

## Abgrenzung

- Kein Entfernen von Kopierschutz; die Buchdateien werden nie angefasst, gelesen wird nur,
  was die Lese-App anzeigt
- Keine Verbreitung von Buchinhalten: Ergebnisse, Seitenbilder und Testaufnahmen echter
  Bücher gehören nie in dieses Repo
- Kein Stapelbetrieb mehrerer Bücher und keine Korrektur des erkannten Textes
- Derzeit nur die Kindle-App unter macOS als Quelle

## Lizenz

Keine; alle Rechte vorbehalten. Das Repo ist privat.
