"""Tests for book2md.py without the Kindle app: a simulated Kindle for page turning,
synthetic page images for OCR and figures. Run: python3 tests/test_book2md.py"""
import sys, os, io, glob, json, shutil, tempfile, contextlib, importlib.util
TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOL)
spec = importlib.util.spec_from_file_location("k", os.path.join(TOOL, "book2md.py"))
def load():
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
k = load()
from PIL import Image
import mdbook
TITLE = "The Map of Consciousness Explained: A Proven Energy Scale to Actualize Your Ultimate Potential"
fails = []
def check(name, cond, info=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  [{info}]" if info and not cond else ""))
    if not cond: fails.append(name)

# ---------- simulated Kindle for walk()
class Book:
    def __init__(s, n, start=0, lag=0, lose=(), panel_at=None):
        s.n, s.pos, s.lag, s.lose, s.presses, s.pending = n, start, lag, set(lose), 0, []
        s.panel_at, s.panel, s.panel_shown = panel_at, False, False
    def press(s, d):
        s.presses += 1
        if s.presses in s.lose or s.panel: return
        if s.panel_at is not None and d == k.KEY_RIGHT and s.pos == s.panel_at - 1 and not s.panel_shown:
            s.pos += 1; s.panel = True; s.panel_shown = True; return
        s.pending.append([s.lag, 1 if d == k.KEY_RIGHT else -1])
    def close(s):
        if s.panel: s.panel = False; return "closed"
        return "none"
    def tick(s):
        for p in s.pending: p[0] -= 1
        for p in [p for p in s.pending if p[0] < 0]:
            s.pos = min(max(s.pos + p[1], 0), s.n - 1); s.pending.remove(p)
    def img(s): return Image.new("L", (60, 80), 250 if s.panel else 10 + 3 * s.pos)
def run_walk(book, direction=None, maxp=100, keep=True):
    global k
    k = load(); d = tempfile.mkdtemp()
    k.capture = lambda p: (book.tick(), open(p, "wb").close())
    k.crop = lambda p, t, b: book.img()
    k.press = book.press
    k.time.sleep = lambda x: None
    k.on_this_space = lambda: run_walk.space
    k.close_end_panel = book.close
    shots = {}
    k.capture = lambda p: (book.tick(), open(p, "wb").close(), shots.__setitem__(p, book.pos if not book.panel else "panel"))
    run_walk.shots = shots
    paths, end, turned = k.walk(direction or k.KEY_RIGHT, d, maxp, 0, keep=keep, log=lambda m: None)
    run_walk.turned = turned
    return paths, end, d
run_walk.space = True
b = Book(10); paths, end, d = run_walk(b)
check("walk: 10 Seiten, Ende erkannt", len(paths) == 10 and end is True, (len(paths), end))
check("walk: Dateien fortlaufend", sorted(os.listdir(d)) == [f"page-{i:04d}.png" for i in range(1, 11)], os.listdir(d))
b = Book(10, lag=1); paths, end, d = run_walk(b)
check("walk: langsames Umblaettern, keine Seite verloren", len(paths) == 10 and end is True, (len(paths), end))
b = Book(10, lose={3}); paths, end, d = run_walk(b)
check("walk: verlorener Tastendruck, kein Fehlende", len(paths) == 10 and end is True, (len(paths), end))
b = Book(10); paths, end, d = run_walk(b, maxp=4)
check("walk: Obergrenze vor Ende -> end False", len(paths) == 4 and end is False)
b = Book(50, start=20); paths, end, d = run_walk(b, direction=k.KEY_LEFT, keep=False)
check("walk: Zurueckblaettern erreicht Anfang", end is True and b.pos == 0)
check("walk: Zurueckblaettern zaehlt 20 Seiten", run_walk.turned == 20, run_walk.turned)
b = Book(50, start=20); paths, end, d = run_walk(b, direction=k.KEY_LEFT, maxp=5, keep=False)
check("walk: Zurueckblaettern zu kurz -> end False", end is False)
run_walk.space = False
try:
    run_walk(Book(10, lose=set(range(4, 100)))); check("walk: Kindle auf anderem Space", False)
except Exception as e:
    check("walk: stehendes Bild ohne sichtbares Fenster -> Abbruch statt Buchende", "Schreibtisch" in str(e) and "Nach 4 Seiten" in str(e), str(e))
run_walk.space = True
b = Book(10, panel_at=6); paths, end, d = run_walk(b)
seen = [run_walk.shots[p] for p in paths]
check("walk: Abschlussfenster geschlossen, alle 10 Seiten, keine Fensteraufnahme",
      end is True and seen == list(range(10)), (end, seen))
b = Book(10, panel_at=3); paths, end, d = run_walk(b, maxp=4)
check("walk: Obergrenze zaehlt Seiten, nicht Aufnahmen (mit Abschlussfenster)",
      len(paths) == 4 and end is False, (len(paths), end))
k = load()
check("Ueberschrift: Sonderzeichen-Salat abgewiesen", not k.plausible_heading("a«eoeo¢ea"))


# ---------- key test (check_turning) with simulated Kindle
def sim(book, broken_until_prepare=0):
    m = load(); d = tempfile.mkdtemp()
    state = {"prepares": 0}
    def press(dirn):
        if state["prepares"] <= broken_until_prepare - 1 or broken_until_prepare < 0:
            return  # keys swallowed (overlay)
        book.press(dirn)
    def prep(log=print): state["prepares"] += 1
    m.capture = lambda p: (book.tick(), open(p, "wb").close())
    m.crop = lambda p, t, b: book.img()
    m.press = press; m.prepare_reader = prep; m.time.sleep = lambda x: None
    m.on_this_space = lambda: True
    m.close_end_panel = lambda: "none"
    return m, d, state
b = Book(10, start=5); m, d, st = sim(b)
check("Tastentest: Mitte -> nicht am Anfang, Position unveraendert", m.check_turning(d, log=lambda x: None) is False and b.pos == 5, b.pos)
b = Book(10, start=0); m, d, st = sim(b)
check("Tastentest: erste Seite erkannt, Position unveraendert", m.check_turning(d, log=lambda x: None) is True and b.pos == 0, b.pos)
b = Book(10, start=5, lag=1); m, d, st = sim(b)
check("Tastentest: langsames Kindle", m.check_turning(d, log=lambda x: None) is False and b.pos == 5, b.pos)
b = Book(10, start=5); m, d, st = sim(b, broken_until_prepare=2)
check("Tastentest: zweiter Versuch nach Korrektur klappt", m.check_turning(d, log=lambda x: None) is False and b.pos == 5 and st["prepares"] == 2, (b.pos, st))
b = Book(10, start=5); m, d, st = sim(b, broken_until_prepare=-1)
try:
    m.check_turning(d, log=lambda x: None); check("Tastentest: Tasten wirkungslos -> Abbruch", False)
except m.KindleError as e:
    check("Tastentest: Tasten wirkungslos -> Abbruch mit Bildpfad, Ordner bleibt", "blaettert nicht um" in str(e) and e.keep and "probe.png" in str(e), str(e))

# ---------- heading detection on synthetic TSV
def tsv(rows):  # rows: (block, par, line, height, text)
    out = ["level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"]
    for b, p, l, h, t in rows:
        for i, w in enumerate(t.split()):
            out.append(f"5\t1\t{b}\t{p}\t{l}\t{i+1}\t{100+i*60}\t0\t50\t{h}\t95\t{w}")
    return "\n".join(out)
body = [(3, 1, n, 26, "some ordinary body text line here") for n in range(1, 8)]
t = k.tsv_to_text(tsv([(1, 1, 1, 44, "PREFACE")] + body), 2000)
check("Ueberschrift: grosse Zeile -> @@2", t.startswith("@@2|PREFACE"), t[:40])
t = k.tsv_to_text(tsv([(1, 1, 1, 44, "CHAPTER 1"), (2, 1, 1, 44, "Overview of the Map")] + body), 2000)
check("Ueberschrift ueber zwei Bloecke -> eine", t.startswith("@@2|CHAPTER 1 Overview of the Map"), t[:60])
t = k.tsv_to_text(tsv([(1, 1, 1, 44, "CONTENTS"), (2, 1, 1, 26, "Preface 1")] + [(4, 1, 1, 44, "CHAPTER 3: x")] + body), 2000)
check("Inhaltsverzeichnisseite: keine Ueberschriften", "@@" not in t, t[:80])
t = k.tsv_to_text(tsv([(2, 1, 1, 26, "EMBRACE WHAT YOU ARE")] + body), 2000)
check("Grossbuchstaben-Zeile -> @@3", t.startswith("@@3|EMBRACE WHAT YOU ARE"), t[:40])
t = k.tsv_to_text(tsv([(2, 1, 1, 17, "HAY HOUSE INC")] + body), 2000)
check("Kleingedrucktes in Grossbuchstaben bleibt Text", "@@" not in t, t[:40])
t = k.tsv_to_text(tsv([(2, 1, 1, 26, "ALSO BY DAVID R. HAWKINS, M.D., PH.D.")] + body), 2000)
check("Grossbuchstaben mit Schlusspunkt bleibt Text", "@@" not in t, t[:40])
t = k.tsv_to_text(tsv([(2, 1, 1, 33, "Courage")] + body), 2000)
check("kurze Einzelwortzeile 1.27x bleibt Text", "@@" not in t, t[:40])
check("merge_pages: Ueberschrift wird nicht angehaengt",
      k.merge_pages([["text ends here"], ["@@2|PREFACE"], ["lower start"]]) == ["text ends here", "@@2|PREFACE", "lower start"])

# ---------- text functions
check("NOISE: 'civil' bleibt", k.paragraphs("He was\ncivil\nto me.") == ["He was civil to me."])
for w in ["ill", "Civic", "mix", "I", "XL"]:
    check(f"NOISE: Wort '{w}' bleibt", k.paragraphs(w) == [w])
for w in ["xiv", "cxii", "42", "Page 3 of 200", "Seite 4 von 9"]:
    check(f"NOISE: '{w}' entfernt", k.paragraphs(w) == [])
h = mdbook.toc_text([(2, "A"), (3, "B")], "T", "")
check("toc ohne Autor: kein '**'", "**" not in h and "- [A](#a)\n  - [B](#b)" in h, repr(h))
h0 = mdbook.toc_text([], "T", "Au")
check("toc ohne Ueberschriften: kein 'Inhalt'", "Inhalt" not in h0 and "*Au*" in h0, repr(h0))
t, s = mdbook.fin_text(h + "@@2|A\n\ntext\n\n@@3|B\n")
check("fin_text: Links sauber", s["broken"] == [] and s["dup"] == [] and s["leftover_markers"] == 0 and s["links"] == 2, s)

check("Abschlussfenster-Text erkannt", k.is_end_panel(["Overall rating Review this book on Amazon.", "Recommend this book"]))
check("normaler Satz mit 'recommend this book' kein Abschlussfenster", not k.is_end_panel(["I recommend this book to everyone."]))
check("'Back to 308' wird entfernt", k.paragraphs("Back to 308\nText.") == ["Text."])
check("'#' am Absatzanfang maskiert", k.md_escape("#a. text") == "\\#a. text")

# ---------- library
books = [("B000000001", "The Map of Consciousness Explained", "en"),
         ("B000000002", "The Map of Consciousness Explained: Workbook", "en"),
         ("B000000003", "Letting Go", "de")]
check("match: exakter Titel gewinnt", k.match_books(books, "the map of consciousness explained") == [books[0]])
check("match: Anfang mehrdeutig", len(k.match_books(books, "The Map")) == 2)
k.load_library = lambda: books
check("Sprache aus Bibliothek: de -> deu", k.resolve_book("Letting", log=lambda m: None) == ("Letting Go", "deu"))
k = load()
if os.path.exists(k.BOOKDATA) and any(b[0] == "B0847833Y7" for b in (k.load_library() or [])):
    check("echte Bibliothek: Titel und Sprache", k.resolve_book("B0847833Y7") == (TITLE, "eng"))
else:
    print("--   echte Bibliothek: uebersprungen (Buch B0847833Y7 nicht in der Kindle-Bibliothek)")

# ---------- osa error mapping
def osa_err(stderr):
    class R: returncode = 1; stdout = ""
    R.stderr = stderr
    orig = k.subprocess.run; k.subprocess.run = lambda *a, **kw: R
    try: k.osa("x"); return None
    except k.KindleError as e: return str(e)
    finally: k.subprocess.run = orig
check("osa: Bedienungshilfen", "Bedienungshilfen" in osa_err("osascript is not allowed assistive access. (-1719)"))
check("osa: Automation", "Automation" in osa_err("Not authorized to send Apple events to System Events. (-1743)"))
check("osa: -1719 Invalid index nicht als Freigabe", "Freigabe" not in osa_err("Can't get window 1. Invalid index. (-1719)"))
try: k.osa("delay 3", timeout=1); check("osa: Timeout", False)
except k.KindleError as e: check("osa: Timeout als Meldung", "antwortet nicht" in str(e))

# ---------- open_book: Escape out of an open book, tab in background, library entry in front
def ui(state):
    def osa(script, mode="", needle=""):
        if not mode and "Recommend this book" in script:
            state["calls"].append("panel"); return "none"
        if not mode:
            state["calls"].append("front:" + ("set" if "set frontmost" in script else ("activate" if "activate" in script else "get")))
            return "Brave Browser"
        state["calls"].append(mode)
        if mode == "reader": return "reader" if state["reader"] else "notfound"
        if mode == "cancel":
            if state["escape_works"]: state["reader"] = False
            return "cancelled"
        if mode == "tab":
            if state["tab"]: state["reader"] = state["opens"]; return "pressed"
            return "notfound"
        if mode == "press":
            if state["in_library"]: state["reader"] = state["opens"]; return "pressed"
            return "notfound"
        if mode == "search": return "notfound"
        if mode == "describe": return "X, Hawkins MD/PHD, David R., " if state["in_library"] else "notfound"
    return osa
def fresh(**kw):
    m = load(); m.ensure_kindle = lambda: None; m.press = lambda c: None; m.time.sleep = lambda x: None
    st = {"reader": False, "escape_works": True, "in_library": True, "tab": False, "opens": True, "calls": []}
    st.update(kw); m.osa = ui(st); return m, st
m, st = fresh(reader=True, tab=True)
check("open_book: Autor aus der Bibliothek", m.open_book("X", log=lambda x: None) == "David R. Hawkins")
check("open_book: offenes Buch -> Escape, dann Tab, ganz im Hintergrund",
      "cancel" in st["calls"] and "tab" in st["calls"] and not any(c.startswith("front:") for c in st["calls"]), st["calls"])
m, st = fresh(tab=False)
m.open_book("X", log=lambda x: None)
check("open_book: ohne Tab -> kurz nach vorne, danach Fokus zurueck",
      "front:activate" in st["calls"] and st["calls"][-1] == "front:set" and "press" in st["calls"], st["calls"])
m, st = fresh(tab=False, opens=False)
try: m.open_book("X", log=lambda x: None); check("open_book: Buch erscheint nicht", False)
except m.KindleError as e: check("open_book: Buch erscheint nicht -> Meldung, Fokus trotzdem zurueck", "erscheint nicht" in str(e) and st["calls"][-1] == "front:set", (str(e), st["calls"][-3:]))
m, st = fresh(reader=True, escape_works=False)
try: m.open_book("X", log=lambda x: None); check("open_book: Escape wirkungslos", False)
except m.KindleError as e: check("open_book: Escape wirkungslos -> Meldung", "Leseansicht" in str(e), str(e))
m, st = fresh(tab=False, in_library=False)
try: m.open_book("X", log=lambda x: None); check("open_book: Buch fehlt", False)
except m.KindleError as e: check("open_book: Buch fehlt auch in Suche -> Meldung", "auch nicht" in str(e), str(e))
k = load()

# ---------- main(): inputs and failure handling
def run_main(argv, mod):
    real = mod.resolve_book
    mod.resolve_book = lambda q, log=print: (TITLE, "eng") if q == "B0847833Y7" else real(q, log)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try: mod.main(argv); code = 0
        except SystemExit as e: code = e.code
    return code, out.getvalue(), err.getvalue()
T = tempfile.mkdtemp()
code, o, e = run_main(["X", "--seiten", "0", "--out", f"{T}/o/m.md"], k)
check("main: --seiten 0 -> Code 2", code == 2 and "--seiten" in e, (code, e))
code, o, e = run_main(["X", "--out", T], k)
check("main: --out Ordner -> Code 2", code == 2 and "Ordner" in e, (code, e))
code, o, e = run_main(["X", "--toc", "a.txt", "--out", f"{T}/o/m.md"], k)
check("main: alte Option --toc abgelehnt", code == 2, (code, e))

def synthetic_page(path, text="This is a synthetic test page with a few lines of text."):
    """A light page with printed text lines, as a stand-in for a Kindle screenshot."""
    from PIL import ImageDraw, ImageFont
    img = Image.new("RGB", (900, 1200), (255, 255, 255))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=28)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    for i in range(8):
        d.text((60, 150 + i * 60), text, fill=(0, 0, 0), font=font)
    img.save(path)


def prepared(name, pages=("page-0001.png", "page-0002.png"), status="aufgenommen"):
    d = f"{T}/{name}.seitenbilder"; os.makedirs(d)
    for p in pages: synthetic_page(os.path.join(d, p))
    json.dump({"buch": TITLE, "from_current": False, "seiten_limit": None, "status": status,
               "ende_erreicht": True}, open(f"{d}/lauf.json", "w"))
    return d
d = prepared("kaputt"); open(f"{d}/page-0003.png", "w").write("x")
code, o, e = run_main(["B0847833Y7", "--out", f"{T}/kaputt.md"], k)
check("main: kaputtes Seitenbild -> Phase, Seite, Wiederverwendung genannt",
      code == 1 and "Texterkennung" in e and "page-0003.png" in e and "Derselbe Befehl" in e, (code, e))
check("main: Seitenbilder nach Abbruch erhalten", os.path.exists(f"{d}/page-0001.png"))
check("main: keine halbe Ausgabedatei", not os.path.exists(f"{T}/kaputt.md"))
os.remove(f"{d}/page-0003.png")
code, o, e = run_main(["B0847833Y7", "--out", f"{T}/kaputt.md"], k)
check("main: zweiter Aufruf verwendet Seitenbilder weiter, ohne Kindle", code == 0 and "Kindle wird nicht benutzt" in o and "Leseposition" not in o, (code, o, e))
check("main: Seitenbilder nach Erfolg geloescht", not os.path.exists(d))
d = prepared("ctrlc")
k2 = load(); k2.read_page = lambda *a, **kw: (_ for _ in ()).throw(KeyboardInterrupt)
code, o, e = run_main(["B0847833Y7", "--out", f"{T}/ctrlc.md"], k2)
check("main: Ctrl+C -> Meldung, Seitenbilder erhalten", code == 1 and "Ctrl+C" in e and os.path.exists(f"{d}/page-0001.png"), (code, e))
d = prepared("bug")
k3 = load(); k3.merge_pages = lambda *a: 1 / 0
code, o, e = run_main(["B0847833Y7", "--out", f"{T}/bug.md"], k3)
check("main: unerwarteter Fehler -> fehler.log", code == 1 and "ZeroDivisionError" in e and os.path.exists(f"{d}/fehler.log"), (code, e))
d = prepared("halb", status="laeuft")
k4 = load(); k4.open_book = lambda t: (_ for _ in ()).throw(k4.KindleError("Testabbruch"))
code, o, e = run_main(["B0847833Y7", "--out", f"{T}/halb.md"], k4)
check("main: unvollstaendige Aufnahme wird nicht weiterverwendet", code == 1 and "Phase 'Buch oeffnen'" in e and not os.path.exists(d), (code, e))

# user's run 2026-11-14: keys swallowed -> abort, nothing written, folder kept
k5 = load()
b = Book(10, start=5)
k5.open_book = lambda t: None
k5.capture = lambda p: (b.tick(), open(p, "wb").close())
k5.crop = lambda p, t, bt: b.img()
k5.press = lambda dirn: None
k5.prepare_reader = lambda log=print: None
k5.time.sleep = lambda x: None
k5.on_this_space = lambda: True
k5.close_end_panel = lambda: "none"
k5.hide_toolbar = lambda log=print: None
code, o, e = run_main(["B0847833Y7", "--out", f"{T}/stuck.md"], k5)
check("main: Tasten wirkungslos -> Code 1, Phase Tastentest, keine Datei, Ordner erhalten",
      code == 1 and "Phase 'Tastentest'" in e and not os.path.exists(f"{T}/stuck.md")
      and os.path.exists(f"{T}/stuck.seitenbilder/probe.png"), (code, e))
# normal flow with status lines
k6 = load()
b = Book(6, start=3)
k6.open_book = lambda t: None
k6.capture = lambda p: (b.tick(), Image.new("L", (60, 80), 10 + 3 * b.pos).save(p))
k6.crop = lambda p, t, bt: b.img()
k6.press = b.press
k6.prepare_reader = lambda log=print: None
k6.time.sleep = lambda x: None
k6.on_this_space = lambda: True
k6.close_end_panel = lambda: "none"
k6.read_page = lambda p, lang, d: ["Text der Seite."]
k6.hide_toolbar = lambda log=print: None
k6.open_book = lambda t: "David R. Hawkins"
code, o, e = run_main(["B0847833Y7", "--out", f"{T}/ok.md"], k6)
check("main: Ablauf meldet jeden Schritt",
      code == 0 and all(x in o for x in ["Buch geoeffnet.", "Tastentest: Kindle blaettert um.", "Zurueckgeblaettert: 3 Seiten", "Gelesen: 6 Seiten, Buchende erreicht."]), (code, o, e))
check("main: Autor automatisch im Dateikopf", "*David R. Hawkins*" in open(f"{T}/ok.md").read())

# ---------- figures
from PIL import ImageDraw
k = load()
page = Image.new("RGB", (800, 1000), (0, 0, 0))
ImageDraw.Draw(page).rectangle((200, 300, 600, 600), fill=(255, 255, 255))
boxes = k.find_figures(page, "level\n", scale=2)
check("Abbildung: helles Bild auf dunkler Seite gefunden",
      len(boxes) == 1 and abs(boxes[0][0] - 200) <= 16 and abs(boxes[0][3] - 600) <= 48, boxes)
check("Abbildung: leere Seite ergibt keine", k.find_figures(Image.new("RGB", (800, 1000)), "level\n") == [])
fig_tsv = tsv([(1, 1, 1, 26, "text above the picture"), (3, 1, 1, 26, "text below the picture")])
lines_out = []
for r in fig_tsv.splitlines():
    f = r.split("\t")
    if len(f) == 12 and f[2] == "3":
        f[7] = "900"
    lines_out.append("\t".join(f))
fig_tsv = "\n".join(lines_out)
t = k.tsv_to_text(fig_tsv, 2000, figures=[((100, 300, 1500, 700), "@@IMG|x.png")])
check("Abbildung: steht zwischen Text darueber und darunter",
      t.split("\n\n") == ["text above the picture", "@@IMG|x.png", "text below the picture"], t)
t = k.tsv_to_text(tsv([(1, 1, 1, 26, "inside words gone")]), 2000, figures=[((0, -10, 2000, 100), "@@IMG|y.png")])
check("Abbildung: Woerter im Bild fallen weg", t == "@@IMG|y.png", t)

# full run: figure becomes img/abbildung-001.png with a link
k7 = load()
b = Book(3, start=0)
k7.open_book = lambda t: "A"
k7.capture = lambda p: (b.tick(), Image.new("L", (60, 80), 10 + 3 * b.pos).save(p))
k7.crop = lambda p, t, bt: b.img()
k7.press = b.press; k7.prepare_reader = lambda log=print: None; k7.time.sleep = lambda x: None
k7.on_this_space = lambda: True; k7.close_end_panel = lambda: "none"; k7.hide_toolbar = lambda log=print: None
def fake_read(p, lang, d):
    f = os.path.join(d, os.path.basename(p) + "-fig1.png"); Image.new("RGB", (5, 5)).save(f)
    return ["Text vorher.", "@@IMG|" + f, "Text nachher."]
k7.read_page = fake_read
code, o, e = run_main(["B0847833Y7", "--out", f"{T}/fig/m.md"], k7)
md = open(f"{T}/fig/m.md").read() if os.path.exists(f"{T}/fig/m.md") else ""
check("main: Abbildungen nummeriert, kopiert und verlinkt",
      code == 0 and "![Abbildung 1](img/abbildung-001.png)" in md and "![Abbildung 2](img/abbildung-002.png)" in md
      and os.path.exists(f"{T}/fig/img/abbildung-002.png") and "Abbildungen: 2" in o, (code, o, e))

print("\n" + ("ALLE OK" if not fails else f"{len(fails)} FEHLGESCHLAGEN: {fails}"))
sys.exit(1 if fails else 0)
