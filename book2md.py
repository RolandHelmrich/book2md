"""Read a book in the local Kindle app (macOS) page by page and save it as Markdown.

Flow: find the book in the app's library database (full title, language), open it via
the app's UI (accessibility), rewind to the cover, press the right arrow key page by page,
capture the Kindle window with `screencapture`, OCR every page with `tesseract`, detect
headings from the text size, rebuild paragraphs and write Markdown with a linked table of
contents.

Only reads what the app shows on screen; the book file itself is never touched.

Usage:
  python3 book2md.py "The Map of Consciousness Explained" --out ~/books/map/map.md
  python3 book2md.py B0847833Y7 --out map.md --author "David R. Hawkins"
  python3 book2md.py "The Map of Consciousness Explained" --out test.md --seiten 5

Runs in the background: key presses go straight to Kindle and only Kindle's window is
photographed, so other apps may be used meanwhile. Kindle must stay open (not quit, window
not closed); a hidden or minimised window is shown again in the back.

Exit codes: 0 ok, 1 aborted, 2 invalid input, 3 file written but book end not reached.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes
import ctypes.util
import glob
import io
import json
import os
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import traceback

try:
    from PIL import Image, ImageChops, ImageStat
except ImportError:
    sys.exit("Fehlt: Pillow. Installieren mit: python3 -m pip install pillow")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mdbook  # noqa: E402  (local copy next to this script)

BUNDLE_ID = "com.amazon.Lassen"
PROCESS = "Kindle"
BOOKDATA = os.path.expanduser(
    "~/Library/Containers/com.amazon.Lassen/Data/Library/Protected/BookData.sqlite")
KEY_RIGHT, KEY_LEFT, KEY_RETURN = 124, 123, 36
ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")

# Fixed settings (formerly options). Measured on Kindle 7.25.1, 2026-11-08.
MAX_PAGES = 3000      # upper bound of screen pages per book
MAX_REWIND = 3000     # upper bound of pages when rewinding to the cover
DELAY = 1.5           # seconds after a page turn
REWIND_DELAY = 0.6    # seconds after a page turn while rewinding
CROP_TOP = 0.08       # share of window height: title bar and running head
CROP_BOTTOM = 0.03    # share of window height: footer
SCALE = 2             # enlarge before OCR (fewer merged words)
PROBE_WAIT = 1.0      # seconds between looks while testing whether a key turns the page
OCR_WORKERS = max(1, min(4, (os.cpu_count() or 2) // 2))  # pages recognised at once

# Kindle language code (BookData.sqlite, ZLANGUAGE) -> tesseract language
LANGS = {"en": "eng", "de": "deu", "fr": "fra", "es": "spa", "it": "ita", "nl": "nld",
         "pt": "por"}
DEFAULT_LANG = "eng"

# Heading detection, from line heights on 12 test pages (2026-11-14): chapter titles are
# 1.65x the body text, short single-word lines reach at most 1.27x.
HEADING_RATIO = 1.5   # line at least this much taller than the page's median line
CAPS_MIN_RATIO = 0.9  # all-caps subheading: at least body size (excludes small print)

RUN_INFO = "lauf.json"
ERROR_LOG = "fehler.log"
EXIT_ABORT, EXIT_INPUT, EXIT_INCOMPLETE = 1, 2, 3


class KindleError(RuntimeError):
    """A step failed (app control, screenshot, OCR); message is shown as is.

    keep=True: the page image folder is kept after the abort (it holds evidence)."""

    def __init__(self, msg, keep=False):
        super().__init__(msg)
        self.keep = keep


class InputError(Exception):
    """Invalid user input; message is shown as is."""


# ---------------------------------------------------------------- library lookup

def load_library():
    """Return [(asin, title, language)] from a snapshot of the app's library database.

    Returns None if the database does not exist; raises KindleError if it is unreadable.
    """
    if not os.path.exists(BOOKDATA):
        return None
    tmp = tempfile.mkdtemp(prefix="kindle-db-")
    try:
        for f in glob.glob(BOOKDATA + "*"):  # db + -wal + -shm: consistent snapshot
            shutil.copy2(f, tmp)
        con = sqlite3.connect(os.path.join(tmp, os.path.basename(BOOKDATA)))
        try:
            rows = con.execute(
                "select ZBOOKID, ZDISPLAYTITLE, ZLANGUAGE from ZBOOK "
                "where coalesce(ZRAWISDICTIONARY,0)=0 and ZDISPLAYTITLE is not null").fetchall()
        finally:
            con.close()
    except (OSError, sqlite3.Error) as e:
        raise KindleError(f"Kindle-Bibliothek nicht lesbar ({BOOKDATA}): {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    books = []
    for book_id, title, lang in rows:
        m = re.match(r"^A:(.+)-0$", book_id or "")
        books.append((m.group(1) if m else book_id, title, lang or ""))
    return books


def match_books(books, query):
    """ASIN match first, then an exact title, then titles starting with the query."""
    if ASIN_RE.match(query):
        hits = [b for b in books if b[0] == query]
        if hits:
            return hits
    q = query.casefold().strip()
    exact = [b for b in books if b[1].casefold().strip() == q]
    if exact:
        return exact
    return [b for b in books if b[1].casefold().startswith(q)]


def resolve_book(query, log=print):
    """(full title, tesseract language) from the library; falls back to the query."""
    try:
        books = load_library()
    except KindleError as e:
        log(f"Warnung: {e}\n  Weiter mit dem Titel wie angegeben.")
        books = None
    if books is None:
        if ASIN_RE.match(query):
            raise InputError(f"'{query}' sieht aus wie eine ASIN, aber die Kindle-Bibliothek ist "
                             "nicht lesbar. Den Buchtitel angeben.")
        log(f"Warnung: Sprache unbekannt, Texterkennung mit '{DEFAULT_LANG}'.")
        return query, DEFAULT_LANG
    matches = match_books(books, query)
    if len(matches) > 1:
        raise InputError("Titel mehrdeutig, bitte genauer angeben oder ASIN verwenden:\n"
                         + "\n".join(f"  {asin}  {t}" for asin, t, _ in matches))
    if not matches:
        if ASIN_RE.match(query):
            raise InputError(f"ASIN {query} nicht in der lokalen Kindle-Bibliothek.")
        log(f"Warnung: '{query}' nicht in der Kindle-Bibliothek gefunden; suche das Buch in "
            f"der App unter diesem Titel. Sprache unbekannt, Texterkennung mit '{DEFAULT_LANG}'.")
        return query, DEFAULT_LANG
    _, title, code = matches[0]
    lang = LANGS.get(code.split("-")[0].lower())
    if not lang:
        log(f"Warnung: Buchsprache '{code}' ohne Zuordnung, Texterkennung mit '{DEFAULT_LANG}'.")
        lang = DEFAULT_LANG
    return title, lang


# ---------------------------------------------------------------- app control

PERMISSION_HINT = ("Systemeinstellungen > Datenschutz & Sicherheit > {} > Terminal einschalten, "
                   "dann Terminal mit Cmd+Q beenden und neu oeffnen.")


def osa(script, *args, timeout=120):
    try:
        r = subprocess.run(["osascript", "-", *args], input=script, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise KindleError(f"AppleScript antwortet nicht innerhalb von {timeout} s "
                          "(Kindle oder System Events haengt). Kindle neu starten.")
    if r.returncode != 0:
        err = r.stderr.strip()
        low = err.lower()
        if ("assistive access" in low or "-25211" in err or "hilfsger" in low
                or "bedienungshilfen" in low):
            raise KindleError("Keine Freigabe 'Bedienungshilfen'. "
                              + PERMISSION_HINT.format("Bedienungshilfen") + f"\n  ({err})")
        if "-1743" in err or "not authori" in low or "nicht berechtigt" in low:
            raise KindleError("Keine Freigabe 'Automation' fuer System Events. "
                              + PERMISSION_HINT.format("Automation > System Events")
                              + f"\n  ({err})")
        raise KindleError(f"AppleScript-Fehler: {err}")
    return r.stdout.strip()


# ---- macOS APIs via ctypes (standard library): window list, key events to one process

_LIBS = {}


def _api():
    """CoreFoundation/CoreGraphics functions with their signatures (loaded once)."""
    if not _LIBS:
        vp = ctypes.c_void_p
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
        cg.CGWindowListCopyWindowInfo.restype = vp
        cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        cg.CGEventCreateKeyboardEvent.restype = vp
        cg.CGEventCreateKeyboardEvent.argtypes = [vp, ctypes.c_uint16, ctypes.c_bool]
        cg.CGEventPostToPid.argtypes = [ctypes.c_int, vp]
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetCount.argtypes = [vp]
        cf.CFArrayGetValueAtIndex.restype = vp
        cf.CFArrayGetValueAtIndex.argtypes = [vp, ctypes.c_long]
        cf.CFDictionaryGetValue.restype = vp
        cf.CFDictionaryGetValue.argtypes = [vp, vp]
        cf.CFStringCreateWithCString.restype = vp
        cf.CFStringCreateWithCString.argtypes = [vp, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFNumberGetValue.restype = ctypes.c_bool
        cf.CFNumberGetValue.argtypes = [vp, ctypes.c_int, vp]
        cf.CFRelease.argtypes = [vp]
        _LIBS.update(cf=cf, cg=cg, keys={})
    return _LIBS


def _key(name):
    """CFString for a dictionary key (cached; 0x08000100 = UTF-8)."""
    api = _api()
    if name not in api["keys"]:
        api["keys"][name] = api["cf"].CFStringCreateWithCString(None, name.encode(), 0x08000100)
    return api["keys"][name]


def _cf_number(d, key):
    cf = _api()["cf"]
    v = cf.CFDictionaryGetValue(d, _key(key))
    if not v:
        return None
    out = ctypes.c_double()
    cf.CFNumberGetValue(v, 13, ctypes.byref(out))  # 13 = kCFNumberDoubleType
    return out.value


def kindle_pid():
    r = subprocess.run(["pgrep", "-x", PROCESS], capture_output=True, text=True)
    pids = r.stdout.split()
    return int(pids[0]) if pids else None


def window_id():
    """ID of Kindle's main window (largest normal window), or None."""
    pid = kindle_pid()
    if pid is None:
        return None
    api = _api()
    arr = api["cg"].CGWindowListCopyWindowInfo(0, 0)  # all windows, also covered ones
    best, best_area = None, 0
    try:
        for i in range(api["cf"].CFArrayGetCount(arr)):
            d = api["cf"].CFArrayGetValueAtIndex(arr, i)
            if _cf_number(d, "kCGWindowOwnerPID") != pid or _cf_number(d, "kCGWindowLayer") != 0:
                continue
            b = api["cf"].CFDictionaryGetValue(d, _key("kCGWindowBounds"))
            area = (_cf_number(b, "Width") or 0) * (_cf_number(b, "Height") or 0) if b else 0
            if area > best_area:
                best, best_area = int(_cf_number(d, "kCGWindowNumber")), area
    finally:
        api["cf"].CFRelease(arr)
    return best


SPACE_MSG = ("Das Kindle-Fenster liegt nicht auf dem aktuellen Schreibtisch (anderer Space oder "
             "eine App im Vollbild). Kindle blaettert dort nicht um. Kindle muss auf dem "
             "sichtbaren Schreibtisch liegen; verdeckt sein darf es.")


def on_this_space():
    """True if accessibility sees Kindle's window, i.e. it is on the current Space."""
    n = osa(f'tell application "System Events" to tell process "{PROCESS}" '
            'to return count of windows')
    return n not in ("", "0")


def ensure_kindle():
    """Kindle running with a visible window. Kindle is never brought to the front."""
    if kindle_pid() is None:
        subprocess.run(["open", "-g", "-b", BUNDLE_ID], capture_output=True)  # -g: background
    for _ in range(30):
        if kindle_pid() and window_id():
            break
        time.sleep(1)
    else:
        raise KindleError("Kindle-Fenster erscheint nicht innerhalb von 30 s.")
    if not on_this_space():
        raise KindleError(SPACE_MSG)
    # hidden (Cmd+H) or minimised windows cannot be photographed: show them in the back
    osa(f'tell application "System Events" to tell process "{PROCESS}"\n'
        '  if visible is false then set visible to true\n'
        '  if value of attribute "AXMinimized" of window 1 then '
        'set value of attribute "AXMinimized" of window 1 to false\n'
        'end tell')


# Walks the window's UI tree recursively. `entire contents` is not used on purpose: in
# Kindle it sometimes returns 0 elements although the library is visible (seen 2026-11-08).
# mode "press":  press the library grid entry whose description starts with needle
#                (opens the book only while Kindle is the active app, 2026-11-14)
# mode "tab":    press the tab of a book opened before (works in the background)
# mode "find":   report whether a button whose description starts with needle exists
# mode "tap":    tap the page: toggles Kindle's toolbar (shows or hides it, 2026-11-14)
# mode "describe": text of the library entry: "<title>, <Last> <titles>, <First>, "
# mode "search": put needle into the "Search Kindle" field (Return is sent separately)
# mode "reader": report whether the reading view (page text element) is showing
# mode "focus":  give the page text element keyboard focus
# mode "cancel": Escape on the page: leaves the reading view for the library (2026-11-14)
UI_ACTION = '''
global found, mode, needle
on walkEl(e, depth)
	if found is not missing value or depth > 25 then return
	tell application "System Events"
		try
			set r to role of e
			if ((mode is "press" or mode is "describe" or mode is "find") and r is "AXButton") or (mode is "tab" and r is "AXRadioButton") then
				if ((description of e) as text) starts with needle then set found to e
			else if mode is "search" and r is "AXTextField" then
				if ((description of e) as text) is "Search Kindle" then set found to e
			else if (mode is "reader" or mode is "focus" or mode is "cancel" or mode is "tap") and r is "AXGenericElement" then
				set found to e
			end if
		end try
		if found is not missing value then return
		try
			set kids to UI elements of e
		on error
			set kids to {}
		end try
	end tell
	repeat with c in kids
		my walkEl(c, depth + 1)
		if found is not missing value then return
	end repeat
end walkEl
on run argv
	set mode to item 1 of argv
	set needle to item 2 of argv
	set found to missing value
	tell application "System Events" to tell process "%s" to set w to window 1
	my walkEl(w, 0)
	if found is missing value then return "notfound"
	if mode is "reader" then return "reader"
	if mode is "find" then return "found"
	if mode is "describe" then
		tell application "System Events" to return (description of found) as text
	end if
	if mode is "focus" then
		tell application "System Events" to set focused of found to true
		return "focused"
	end if
	if mode is "cancel" then
		tell application "System Events" to perform action "AXCancel" of found
		return "cancelled"
	end if
	if mode is "tap" then
		tell application "System Events" to perform action "AXPress" of found
		return "tapped"
	end if
	tell application "System Events"
		if mode is "press" or mode is "tab" then
			perform action "AXPress" of found
			return "pressed"
		end if
		set value of found to needle
		set focused of found to true
		return "searched"
	end tell
end run
''' % PROCESS


# Kindle's end-of-book panel ("Overall rating", "Recommend this book", "More by ...") appears
# when paging past the end of the main text (seen 2026-11-14, page 303 -> 308 of 379) and
# blocks further page turns. Its "Close" button (the chevron on top) works in the background.
END_PANEL = '''
global found, wantRole, needle
on walkEl(e, depth)
	if found is not missing value or depth > 30 then return
	tell application "System Events"
		try
			if ((role of e) as text) is wantRole then
				set d to ""
				try
					set d to (description of e) as text
				end try
				if d is needle then set found to e
			end if
		end try
		if found is not missing value then return
		try
			set kids to UI elements of e
		on error
			set kids to {}
		end try
	end tell
	repeat with c in kids
		my walkEl(c, depth + 1)
		if found is not missing value then return
	end repeat
end walkEl
on run
	tell application "System Events" to tell process "%s" to set w to window 1
	set found to missing value
	set wantRole to "AXHeading"
	set needle to "Recommend this book"
	my walkEl(w, 0)
	if found is missing value then return "none"
	set found to missing value
	set wantRole to "AXButton"
	set needle to "Close"
	my walkEl(w, 0)
	if found is missing value then return "stuck"
	tell application "System Events" to perform action "AXPress" of found
	return "closed"
end run
''' % PROCESS


def close_end_panel():
    """Close Kindle's end-of-book panel if it is open: "closed", "none" or "stuck"."""
    return osa(END_PANEL)


CREDENTIAL_RE = re.compile(r"(?i)(md|phd|m\.d\.|ph\.d\.|dr\.?|prof\.?)(/(md|phd|m\.d\.|ph\.d\.))*,?")


def author_from_entry(entry, title):
    """Author from a library entry text; "Hawkins MD/PHD, David R." -> "David R. Hawkins".

    Returns "" if the entry does not start with the title or names no author.
    """
    if not entry.startswith(title):
        return ""
    rest = entry[len(title):].strip().strip(",").strip()
    parts = [p.strip() for p in rest.split(",") if p.strip()]
    if not parts:
        return ""
    name = f"{parts[1]} {parts[0]}" if len(parts) == 2 else ", ".join(parts)
    return " ".join(t for t in name.split() if not CREDENTIAL_RE.fullmatch(t))


def front_app():
    return osa('tell application "System Events" to return name of first process '
               'whose frontmost is true')


def wait_for_reader(seconds=30):
    for _ in range(seconds):
        if osa(UI_ACTION, "reader", "") == "reader":
            return True
        time.sleep(1)
    return False


def open_book(title, log=print):
    """Open the book and wait until its pages show; return the author ("" if unknown).

    An open book is left first via Escape: in the reading view its title is not visible to
    the script, so it never guesses which book is open. The book's tab (present if it was
    opened before) works in the background; the library entry needs Kindle in front for a
    moment, after which the previously active app gets the focus back.
    """
    ensure_kindle()
    if osa(UI_ACTION, "reader", "") == "reader":
        log("Kindle zeigt ein offenes Buch; wechsle zur Bibliothek ...")
        close_end_panel()
        left = False
        # Escape leaves the book unless Kindle's toolbar is showing; then "Close Book" does
        for action, needle in (("cancel", ""), ("press", "Close Book")):
            osa(UI_ACTION, action, needle)
            for _ in range(5):
                time.sleep(1)
                if osa(UI_ACTION, "reader", "") != "reader":
                    left = True
                    break
            if left:
                break
        if not left:
            raise KindleError("Kindle verlaesst die Leseansicht nicht (weder Escape noch "
                              "'Close Book' wirken).")

    entry = osa(UI_ACTION, "describe", title)
    author = author_from_entry(entry, title) if entry != "notfound" else ""

    if osa(UI_ACTION, "tab", title) == "pressed":
        if wait_for_reader():
            return author
        raise KindleError(f"Tab von '{title}' gedrueckt, aber das Buch erscheint nicht "
                          "innerhalb von 30 s.")

    previous = front_app()
    log("Oeffne das Buch aus der Bibliothek (Kindle kommt dafuer kurz nach vorne) ...")
    osa(f'tell application id "{BUNDLE_ID}" to activate')
    time.sleep(1)
    try:
        pressed = osa(UI_ACTION, "press", title) == "pressed"
        if not pressed and osa(UI_ACTION, "search", title) == "searched":
            press(KEY_RETURN)
            time.sleep(3)
            pressed = osa(UI_ACTION, "press", title) == "pressed"
        if not pressed:
            raise KindleError(f"Buch '{title}' in der Kindle-Bibliothek nicht gefunden, auch "
                              "nicht ueber die Suche.")
        if not wait_for_reader():
            raise KindleError(f"Buch '{title}' gedrueckt, aber es erscheint nicht innerhalb "
                              "von 30 s (Buch nicht heruntergeladen?).")
        return author
    finally:
        if previous and previous != PROCESS:
            osa(f'tell application "System Events" to set frontmost of process '
                f'"{previous}" to true')


def press(key_code):
    """Send a key straight to Kindle (works while other apps are in front)."""
    pid = kindle_pid()
    if pid is None:
        raise KindleError("Kindle laeuft nicht mehr (beendet waehrend des Laufs?).")
    api = _api()
    for down in (True, False):
        ev = api["cg"].CGEventCreateKeyboardEvent(None, key_code, down)
        api["cg"].CGEventPostToPid(pid, ev)
        api["cf"].CFRelease(ev)
        time.sleep(0.03)


def capture(path):
    """Photograph Kindle's window, even when other windows cover it."""
    wid = window_id()
    if wid is None:
        raise KindleError("Kindle-Fenster nicht gefunden (Kindle beendet oder Fenster "
                          "geschlossen?).")
    r = subprocess.run(["screencapture", "-x", "-o", "-l", str(wid), path],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(path):
        raise KindleError("Fensterfoto fehlgeschlagen. Freigabe 'Bildschirmaufnahme' pruefen: "
                          + PERMISSION_HINT.format("Bildschirmaufnahme")
                          + (f"\n  ({r.stderr.strip()})" if r.stderr.strip() else ""))


def prepare_reader(log=print):
    """Keyboard focus on the page text (Kindle stays where it is)."""
    if osa(UI_ACTION, "focus", "") != "focused":
        log("  Hinweis: Seiteninhalt nicht gefunden, Fokus nicht gesetzt.")
    time.sleep(0.5)


def hide_toolbar(log=print):
    """Hide Kindle's toolbar (header, blue frame, "Page x of y") before a page photo.

    Kindle shows it by itself at the end of the main text and of the book. A tap on the
    page toggles it, so tap only while it is visible ("Close Book" button present).
    """
    if osa(UI_ACTION, "find", "Close Book") != "found":
        return
    osa(UI_ACTION, "tap", "")
    time.sleep(1)
    if osa(UI_ACTION, "find", "Close Book") == "found":
        log("  Hinweis: Kindle-Leiste liess sich nicht ausblenden; sie ist auf dieser Seite "
            "mit im Bild.")


def snap_to(path):
    capture(path)
    return crop(path, CROP_TOP, CROP_BOTTOM)


def snap(shots):
    path = os.path.join(shots, "probe.png")
    capture(path)
    return crop(path, CROP_TOP, CROP_BOTTOM)


def try_turn(direction, before, shots, waits=3):
    """Press once; return the new page image if the page changed, else None."""
    press(direction)
    for _ in range(waits):
        time.sleep(PROBE_WAIT)
        img = snap(shots)
        if not same_page(img, before):
            return img
    return None


def check_turning(shots, log=print):
    """Make sure the arrow keys turn pages; the reading position is left as it was.

    Returns True if the book already shows its first page.
    """
    for attempt in (1, 2):
        if not on_this_space():
            raise KindleError(SPACE_MSG)
        prepare_reader(log)
        before = snap(shots)
        after = try_turn(KEY_LEFT, before, shots)
        if after is not None:
            try_turn(KEY_RIGHT, after, shots)  # back to where the reader was
            return False
        after = try_turn(KEY_RIGHT, before, shots)
        if after is not None:
            try_turn(KEY_LEFT, after, shots)
            return True
        if attempt == 1:
            log("  Kindle blaettert nicht um; zweiter Versuch nach Fokuskorrektur ...")
    raise KindleError(
        "Kindle blaettert nicht um: Die Seite blieb nach Pfeil links und Pfeil rechts gleich, "
        "auch im zweiten Versuch (Fokus auf die Seite gesetzt). "
        "Es wurde nichts geschrieben. Bild der stehenden Seite: "
        + os.path.join(shots, "probe.png"), keep=True)


# ---------------------------------------------------------------- images

def crop(path, top, bottom):
    with Image.open(path) as im:
        w, h = im.size
        return im.crop((0, int(h * top), w, int(h * (1 - bottom))))


def same_page(a, b, tolerance=1.0):
    """True if two cropped page images look identical (mean grey difference)."""
    if a is None or b is None:
        return False
    sa = a.convert("L").resize((300, max(1, int(300 * a.height / a.width))))
    sb = b.convert("L").resize(sa.size)
    return ImageStat.Stat(ImageChops.difference(sa, sb)).mean[0] < tolerance


def tesseract_langs():
    r = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True)
    # the header line goes to stdout or stderr depending on the version
    lines = (r.stdout + "\n" + r.stderr).splitlines()
    return {l.strip() for l in lines if l.strip() and " " not in l.strip()}


def tesseract_tsv(image, lang, scale=SCALE):
    """Tesseract TSV of one page, coordinates in the enlarged image.

    The image is enlarged first (scale 2 cut merged words like "ona"/"howit" from 10 to 3
    on 5 test pages, 2026-11-08). TSV tells where each word sits, how tall it is and how
    sure tesseract is (centred lines, headings, figures).
    """
    if scale != 1:
        image = image.resize((image.width * scale, image.height * scale), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    r = subprocess.run(["tesseract", "stdin", "stdout", "-l", lang, "--psm", "3", "tsv"],
                       input=buf.getvalue(), capture_output=True,
                       env={**os.environ, "OMP_THREAD_LIMIT": "1"})  # one core per page
    if r.returncode != 0:
        raise KindleError("tesseract: " + r.stderr.decode(errors="replace").strip())
    return r.stdout.decode("utf-8", errors="replace")


def ocr(image, lang, scale=SCALE):
    """OCR one page; returns text with blank lines between paragraphs (no figures)."""
    return tsv_to_text(tesseract_tsv(image, lang, scale), image.width * scale)


def tsv_words(tsv):
    """Words of a TSV: (block, par, line, left, top, width, height, conf, text)."""
    for row in tsv.splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip():
            continue
        yield (int(f[2]), int(f[3]), int(f[4]), int(f[6]), int(f[7]), int(f[8]), int(f[9]),
               float(f[10]), f[11].strip())


def tsv_lines(tsv, skip=None):
    """TSV -> {(block, par): {line: [left, right, words, heights, top]}} and their order.

    skip(left, top, width, height) -> True drops a word (it lies inside a figure).
    """
    groups, order = {}, []
    for block, par, line, left, top, width, height, _, text in tsv_words(tsv):
        if skip and skip(left, top, width, height):
            continue
        key = (block, par)
        if key not in groups:
            groups[key] = {}
            order.append(key)
        ln = groups[key].setdefault(line, [left, left + width, [], [], top])
        ln[0], ln[1], ln[4] = min(ln[0], left), max(ln[1], left + width), min(ln[4], top)
        ln[2].append(text)
        ln[3].append(height)
    return groups, order


# ---- figures: drawn content that is not a recognised word (photos, diagrams, tables)

FIG_CELL = 8           # px grid on the unscaled page
FIG_MIN = 0.10         # a figure is at least 10 % of page width and height
FIG_TEXT_CONF = 50     # words below this confidence are debris inside a picture, not text
FIG_FULLPAGE = 0.6     # a box over 60 % of the page is a figure only on pages without text
FIG_MAX_TEXT = 30      # ... i.e. with fewer sure words than this outside the box


def _is_word(text, conf):
    return conf >= FIG_TEXT_CONF and sum(c.isalnum() for c in text) * 2 >= len(text)


def find_figures(image, tsv, scale=SCALE):
    """Boxes (x0, y0, x1, y1) of figures on an unscaled page image.

    Ink = pixels that differ from the page background. Lines of sure words are masked out,
    with the strip below them (Kindle underlines "popular highlights" there). What ink
    remains forms the figures: grid cells with ink are joined to regions; regions smaller
    than FIG_MIN are dropped (stray marks). Tables count as figures: their grid lines stay.
    """
    from PIL import ImageDraw, ImageFilter
    g = image.convert("L")
    w, h = g.size
    border = [g.getpixel((x, y)) for x in range(0, w, 7) for y in (0, h - 1)]
    bg = statistics.median(border)
    ink = g.point(lambda v: 255 if abs(v - bg) > 40 else 0)
    words, lines = [], {}
    for block, par, line, l, t, ww, hh, conf, text in tsv_words(tsv):
        if _is_word(text, conf):
            words.append((l / scale, t / scale, ww / scale, hh / scale))
            ln = lines.setdefault((block, par, line), [l, t, l + ww, t + hh])
            ln[0], ln[1] = min(ln[0], l), min(ln[1], t)
            ln[2], ln[3] = max(ln[2], l + ww), max(ln[3], t + hh)
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    # whole text lines incl. the gaps between words and the strip below them, where
    # Kindle draws its "popular highlights" underline
    for l, t, r, b in lines.values():
        l, t, r, b = l / scale, t / scale, r / scale, b / scale
        draw.rectangle((l - 3, t - 3, r + 3, b + (b - t) * 1.0 + 3), fill=255)
    rest = ImageChops.subtract(ink, mask)
    cw, ch = max(1, w // FIG_CELL), max(1, h // FIG_CELL)
    cells = rest.resize((cw, ch), Image.BOX).point(lambda v: 255 if v > 20 else 0)
    cells = cells.filter(ImageFilter.MaxFilter(5))  # join nearby parts of one figure
    px = cells.load()
    seen, boxes = set(), []
    for y in range(ch):
        for x in range(cw):
            if not px[x, y] or (x, y) in seen:
                continue
            stack, xs, ys = [(x, y)], [], []
            seen.add((x, y))
            while stack:
                a, b = stack.pop()
                xs.append(a)
                ys.append(b)
                for na, nb in ((a + 1, b), (a - 1, b), (a, b + 1), (a, b - 1)):
                    if 0 <= na < cw and 0 <= nb < ch and px[na, nb] and (na, nb) not in seen:
                        seen.add((na, nb))
                        stack.append((na, nb))
            box = (min(xs) * FIG_CELL, min(ys) * FIG_CELL,
                   min(w, (max(xs) + 1) * FIG_CELL), min(h, (max(ys) + 1) * FIG_CELL))
            if box[2] - box[0] >= FIG_MIN * w and box[3] - box[1] >= FIG_MIN * h:
                boxes.append(box)

    def inside(word, box):
        cx, cy = word[0] + word[2] / 2, word[1] + word[3] / 2
        return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]

    kept = []
    for box in boxes:
        area = (box[2] - box[0]) * (box[3] - box[1])
        outside = sum(not inside(wd, box) for wd in words)
        if area > FIG_FULLPAGE * w * h and outside >= FIG_MAX_TEXT:
            continue  # a frame around text (e.g. Kindle's toolbar border), not a figure
        kept.append(box)
    # a box inside another kept box is part of that figure
    return [b for b in kept if not any(o != b and o[0] <= b[0] and o[1] <= b[1]
                                       and b[2] <= o[2] and b[3] <= o[3] for o in kept)]


def read_page(path, lang, fig_dir):
    """Text of one page image with figures cut out.

    Figures are saved as <fig_dir>/<page>-fig<N>.png and appear in the text as their own
    paragraph "@@IMG|<file>" at their place in reading order.
    """
    image = crop(path, CROP_TOP, CROP_BOTTOM)
    tsv = tesseract_tsv(image, lang)
    figures = []
    for n, box in enumerate(find_figures(image, tsv), 1):
        pad = 4
        box = (max(0, box[0] - pad), max(0, box[1] - pad),
               min(image.width, box[2] + pad), min(image.height, box[3] + pad))
        name = os.path.join(fig_dir, f"{os.path.splitext(os.path.basename(path))[0]}-fig{n}.png")
        image.crop(box).save(name)
        figures.append((tuple(v * SCALE for v in box), "@@IMG|" + name))
    return paragraphs(tsv_to_text(tsv, image.width * SCALE, figures=figures))


HEADING_CHARS_RE = re.compile(r"[\w\s.,:;!?'’‘\"“”()&/–—-]")


def plausible_heading(text):
    """Heading text must be words, not OCR debris from tables or symbols ("a«eoeo¢ea")."""
    letters = sum(c.isalpha() for c in text)
    return (letters >= 3 and all(HEADING_CHARS_RE.match(c) for c in text)
            and re.search(r"[A-Za-zÄÖÜäöüß]{3}", text) is not None)


def is_caps_heading(text):
    """Short all-caps line without closing punctuation: a subheading."""
    letters = [c for c in text if c.isalpha()]
    words = text.split()
    return (len(letters) >= 4 and all(c.isupper() for c in letters)
            and 2 <= len(words) <= 12 and not text.endswith((".", ",", ";", "!", "?"))
            and plausible_heading(text))


def tsv_to_text(tsv, page_width, headings=True, figures=()):
    """Rebuild page text from tesseract TSV: paragraphs separated by blank lines.

    Headings become their own paragraph "@@N|Title": consecutive lines at least
    HEADING_RATIO taller than the page's median line give level 2 (the book title is
    level 1), a single all-caps line of body size gives level 3. A page with more than one
    large heading is a title or contents page: there everything stays plain text.
    figures: [(box in TSV coordinates, marker)]; words inside a box are dropped and the
    marker is placed in reading order (column, then height on the page).
    """
    def in_figure(left, top, width, height):
        cx, cy = left + width / 2, top + height / 2
        return any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b, _ in figures)

    def place(left, top):  # reading order: left column first, then top to bottom
        return (1 if left > page_width * 0.5 else 0, top)

    groups, order = tsv_lines(tsv, skip=in_figure if figures else None)
    heights = [statistics.median(ln[3]) for g in groups.values() for ln in g.values()]
    median = statistics.median(heights) if heights else 0
    out, where, big = [], [], 0
    for key in order:
        lines = [groups[key][n] for n in sorted(groups[key])]
        chunks = []  # (kind, [lines]) with kind "h2" or "body"
        for ln in lines:
            ratio = statistics.median(ln[3]) / median if median else 1
            big_line = ratio >= HEADING_RATIO and plausible_heading(" ".join(ln[2]))
            kind = "h2" if headings and big_line else "body"
            if chunks and chunks[-1][0] == kind:
                chunks[-1][1].append(ln)
            else:
                chunks.append((kind, [ln]))
        for kind, part in chunks:
            texts = [" ".join(ln[2]) for ln in part]
            pos = place(part[0][0], part[0][4])
            if kind == "h2":
                if out and out[-1].startswith("@@2|"):  # title spread over two blocks
                    out[-1] += " " + " ".join(texts)
                else:
                    big += 1
                    out.append("@@2|" + " ".join(texts))
                    where.append(pos)
                continue
            ratio = statistics.median(part[0][3]) / median if median else 1
            if (headings and len(part) == 1 and len(lines) == 1
                    and ratio >= CAPS_MIN_RATIO and is_caps_heading(texts[0])):
                out.append("@@3|" + texts[0])
                where.append(pos)
                continue
            centred = is_centred([(l, r) for l, r, *_ in part], page_width)
            out.append(("\n\n" if centred else "\n").join(texts))
            where.append(pos)
    if headings and big > 1:
        return tsv_to_text(tsv, page_width, headings=False, figures=figures)
    for box, marker in sorted(figures, key=lambda f: place(f[0][0], f[0][1])):
        pos = place(box[0], box[1])
        i = next((i for i, w in enumerate(where) if w > pos), len(out))
        out.insert(i, marker)
        where.insert(i, pos)
    return "\n\n".join(out)


def is_centred(spans, page_width):
    """Lines start at different x but share a centre: centred text, not a paragraph."""
    if len(spans) < 2:
        return False
    lefts = [l for l, _ in spans]
    centres = [(l + r) / 2 for l, r in spans]
    return (max(lefts) - min(lefts) > 0.03 * page_width
            and max(centres) - min(centres) < 0.02 * page_width)


# ---------------------------------------------------------------- text (pure functions)

# Lines dropped as page furniture: "Page 3 of 200" / "Location ..", bare numbers and
# lower-case roman page numbers. Only valid roman numerals count, so words made of the
# same letters ("civil", "ill") stay in the text.
NOISE_RE = re.compile(
    r"^\s*((?i:(page|seite|location|position)\s+\S+\s+(of|von)\s+\d+.*)"
    r"|(?i:(back to|zur(ue|ü)ck zu)\s+\S+)|\d{1,4}"
    r"|(?=[ivxlc])c{0,3}(xc|xl|l?x{0,3})(ix|iv|v?i{0,3}))\s*$")
TERMINAL = tuple('.!?:"”’)]…*')


def is_heading(para):
    return para.startswith("@@")


END_PANEL_WORDS = ("overall rating", "review this book", "recommend this book",
                   "customers who bought", "before you go", "follow the author")


def is_end_panel(paras):
    """Page text of Kindle's end-of-book panel (should never reach the book text)."""
    text = " ".join(paras).casefold()
    return sum(w in text for w in END_PANEL_WORDS) >= 2


def md_escape(para):
    """Keep OCR text starting with '#' or '>' from turning into Markdown markup."""
    return "\\" + para if para[:1] in "#>" else para


def paragraphs(page_text):
    """Page text -> list of paragraphs (blank line = paragraph break)."""
    out = []
    for block in re.split(r"\n\s*\n", page_text):
        lines = [l.strip() for l in block.splitlines()]
        lines = [l for l in lines if l and not NOISE_RE.match(l)]
        if not lines:
            continue
        para = lines[0]
        for line in lines[1:]:
            para = join_fragments(para, line)
        out.append(para)
    return out


def join_fragments(left, right):
    """Join two text pieces, resolving end-of-line hyphenation ("Bewusst-" + "sein")."""
    if re.search(r"\w-$", left):
        if right[:1].islower():
            return left[:-1] + right  # hyphenation: drop the hyphen
        return left + right  # compound ("Ich-" + "Gefuehl"): keep the hyphen, no space
    return left + " " + right


def merge_pages(pages):
    """Join page paragraph lists into one list.

    A paragraph split by a page turn or a column break (two-column view) is glued back
    together: the next piece starts lower-case or the previous one ends with , ; - or a
    dash, and the previous one does not end a sentence. Headings are never joined.
    """
    out = []
    for para in (p for paras in pages for p in paras):
        if out and not is_heading(para) and not is_heading(out[-1]):
            prev = out[-1]
            continues = para[:1].islower() or prev.endswith((",", ";", "-", "–"))
            if continues and not prev.endswith(TERMINAL):
                out[-1] = join_fragments(prev, para)
                continue
        out.append(para)
    return out


# ---------------------------------------------------------------- checks

def check_args(a):
    """Validate arguments before Kindle is touched; return the absolute output path."""
    if a.seiten is not None and a.seiten < 1:
        raise InputError("--seiten muss mindestens 1 sein.")
    for tool in ("tesseract", "screencapture", "osascript"):
        if not shutil.which(tool):
            hint = " (brew install tesseract)" if tool == "tesseract" else ""
            raise InputError(f"Programm fehlt: {tool}{hint}")
    out = os.path.abspath(os.path.expanduser(a.out))
    if os.path.isdir(out):
        raise InputError(f"--out ist ein Ordner, erwartet wird eine Datei: {out}")
    folder = os.path.dirname(out)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        raise InputError(f"Zielordner nicht anlegbar: {folder} ({e.strerror or e})")
    if not os.access(folder, os.W_OK):
        raise InputError(f"Zielordner nicht beschreibbar: {folder}")
    if os.path.exists(out) and not os.access(out, os.W_OK):
        raise InputError(f"Zieldatei nicht beschreibbar: {out}")
    return out


def check_lang(lang):
    if lang not in tesseract_langs():
        raise InputError(f"Tesseract-Sprache '{lang}' fuer dieses Buch nicht installiert. "
                         "Installieren mit: brew install tesseract-lang")


# ---------------------------------------------------------------- page turning

def walk(direction, shots_dir, max_pages, delay, keep=True, log=print, before_capture=None):
    """Turn pages until the view stops changing; return (paths, end reached, pages turned).

    When a page looks unchanged after a key press, Kindle may just be slow: wait and look
    again first, then press once more. Only if the page still has not changed is it the
    end. This way a slow page turn does not lead to a second key press that skips a page.
    """
    paths, prev, n, turned, panels = [], None, 0, 0, 0
    settle = max(delay, 1.0)
    while True:
        n += 1
        path = os.path.join(shots_dir, f"page-{n:04d}.png" if keep else "probe.png")
        if before_capture:
            before_capture()
        capture(path)
        img = crop(path, CROP_TOP, CROP_BOTTOM)
        if same_page(img, prev):
            changed = False
            for retry in range(2):
                if retry == 1:
                    press(direction)
                time.sleep(settle)
                capture(path)
                img = crop(path, CROP_TOP, CROP_BOTTOM)
                if not same_page(img, prev):
                    changed = True
                    break
            if not changed:
                state = close_end_panel()
                if state == "stuck":
                    raise KindleError("Kindle zeigt sein Abschlussfenster (Bewertung, "
                                      "Empfehlungen) und es laesst sich nicht schliessen.",
                                      keep=True)
                if state == "closed" and panels < 3:
                    # The panel appeared on the previous key press and was saved as a page:
                    # replace that picture with the page behind the panel, then go on.
                    panels += 1
                    log("  Kindle-Abschlussfenster geschlossen, lese weiter ...")
                    time.sleep(settle)
                    if keep and paths:
                        os.remove(path)
                        capture(paths[-1])
                        prev = crop(paths[-1], CROP_TOP, CROP_BOTTOM)
                    else:
                        prev = snap_to(path)
                    press(direction)
                    time.sleep(delay)
                    continue
                if keep:
                    os.remove(path)
                if not on_this_space():  # a frozen view is not the end of the book
                    raise KindleError(f"Nach {len(paths)} Seiten: {SPACE_MSG}")
                return paths, True, turned
        if prev is not None:
            turned += 1
        prev = img
        if keep:
            paths.append(path)
            if len(paths) % 25 == 0:
                log(f"  {len(paths)} Seiten aufgenommen")
        if (len(paths) if keep else turned + 1) >= max_pages:  # pages, not captures
            return paths, False, turned
        press(direction)
        time.sleep(delay)


# ---------------------------------------------------------------- run info

def write_run_info(shots, **info):
    data = read_run_info(shots)
    data.update(info)
    with open(os.path.join(shots, RUN_INFO), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_run_info(shots):
    try:
        with open(os.path.join(shots, RUN_INFO), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def shots_dir_for(out):
    """Page images live next to the output while a run is in progress."""
    return os.path.splitext(out)[0] + ".seitenbilder"


def reusable(shots, title, limit):
    """True if the folder holds a complete capture of this book with the same page limit."""
    info = read_run_info(shots)
    return (info.get("status") == "aufgenommen" and info.get("buch") == title
            and info.get("seiten_limit") == limit
            and bool(glob.glob(os.path.join(shots, "page-*.png"))))


# ---------------------------------------------------------------- main flow

def build_parser():
    ap = argparse.ArgumentParser(
        description="Kindle-Buch als Markdown speichern (Inhaltsverzeichnis, Sprache und "
                    "Ueberschriften automatisch).")
    ap.add_argument("book", metavar="BUCH", help="Titel (Anfang genuegt) oder ASIN")
    ap.add_argument("--out", required=True, metavar="DATEI", help="Ziel-Markdown-Datei")
    ap.add_argument("--author", default="", metavar="TEXT",
                    help="Autor ueberschreiben (sonst aus der Kindle-Bibliothek)")
    ap.add_argument("--seiten", type=int, metavar="N",
                    help="Testlauf: nur N Seiten ab der aktuellen Seite, ohne Zurueckblaettern")
    return ap


class Run:
    """State that the error handler needs: current phase and where screenshots are."""

    def __init__(self, a):
        self.a = a
        self.phase = "Vorpruefung"
        self.shots = None


def capture_book(a, run, title):
    """Open the book, rewind, read; return (paths, from_current, end reached)."""
    shutil.rmtree(run.shots, ignore_errors=True)
    os.makedirs(run.shots)
    from_current = a.seiten is not None
    write_run_info(run.shots, buch=title, from_current=from_current,
                   seiten_limit=a.seiten, status="laeuft")

    run.phase = "Buch oeffnen"
    author = open_book(title)
    write_run_info(run.shots, autor=author)
    time.sleep(4)
    print("Buch geoeffnet." + (f" Autor laut Kindle: {author}" if author else ""))

    run.phase = "Tastentest"
    at_first = check_turning(run.shots)
    print("Tastentest: Kindle blaettert um."
          + (" Das Buch steht auf der ersten Seite." if at_first else ""))

    probe = os.path.join(run.shots, "probe.png")
    if not from_current and not at_first:
        run.phase = "Zurueckblaettern"
        print("Blaettere zurueck zum Anfang ...")
        _, at_start, turned = walk(KEY_LEFT, run.shots, MAX_REWIND, REWIND_DELAY, keep=False)
        if not at_start:
            raise KindleError(f"Buchanfang nach {MAX_REWIND} Seiten nicht erreicht.")
        print(f"Zurueckgeblaettert: {turned} Seiten, Anfang erreicht.")
    if os.path.exists(probe):
        os.remove(probe)

    run.phase = "Lesen"
    print("Lese Seiten ...")
    limit = a.seiten or MAX_PAGES
    paths, at_end, _ = walk(KEY_RIGHT, run.shots, limit, DELAY, before_capture=hide_toolbar)
    if len(paths) < 2 <= limit:
        raise KindleError("Kindle hat nach der ersten Seite nicht weitergeblaettert, obwohl der "
                          "Tastentest vorher funktioniert hat. Es wurde nichts geschrieben. "
                          f"Bild der Seite: {paths[0] if paths else '-'}", keep=True)
    print(f"Gelesen: {len(paths)} Seiten, "
          + ("Buchende erreicht." if at_end else f"Obergrenze {limit} erreicht."))
    write_run_info(run.shots, seiten=len(paths), ende_erreicht=at_end, status="aufgenommen")
    return paths, from_current, at_end


def run_tool(a, run):
    out = check_args(a)

    run.phase = "Bibliothek"
    title, lang = resolve_book(a.book)
    check_lang(lang)
    print(f"Buch: {title} (Texterkennung: {lang})")

    run.shots = shots_dir_for(out)
    if reusable(run.shots, title, a.seiten):
        info = read_run_info(run.shots)
        paths = sorted(glob.glob(os.path.join(run.shots, "page-*.png")))
        from_current, at_end = bool(info.get("from_current")), info.get("ende_erreicht")
        print(f"Seitenbilder eines frueheren Laufs vollstaendig vorhanden ({run.shots}); "
              "Kindle wird nicht benutzt.")
        captured = False
    else:
        paths, from_current, at_end = capture_book(a, run, title)
        info = read_run_info(run.shots)
        captured = True
    print(f"{len(paths)} Seiten, Texterkennung laeuft ...")

    run.phase = "Texterkennung"
    fig_dir = os.path.join(run.shots, "abbildungen")
    shutil.rmtree(fig_dir, ignore_errors=True)
    os.makedirs(fig_dir)
    body_paths, cover_md, cover = paths, "", None
    if not from_current and paths:
        cover = crop(paths[0], CROP_TOP, 0)
        cover_md = "![Cover](img/cover.png)\n\n"
        body_paths = paths[1:]
    def read(p):
        try:
            return read_page(p, lang, fig_dir)
        except (KindleError, OSError) as e:
            raise KindleError(f"Seite {os.path.basename(p)}: {e}")

    pages = []
    # tesseract runs as its own process, so threads read several pages at once
    with ThreadPoolExecutor(max_workers=OCR_WORKERS) as pool:
        for i, (p, page) in enumerate(zip(body_paths, pool.map(read, body_paths)), 1):
            if is_end_panel(page):
                print(f"  {os.path.basename(p)}: Kindle-Abschlussfenster, nicht uebernommen.")
                continue
            pages.append(page)
            if i % 25 == 0:
                print(f"  Texterkennung {i}/{len(body_paths)}")
    paras = merge_pages(pages)
    entries = mdbook.headings(paras)
    author = a.author or info.get("autor", "")
    if not author:
        print("Warnung: Autor in der Kindle-Bibliothek nicht gefunden; Dateikopf ohne Autor.")
    header = mdbook.toc_text(entries, title, author)

    run.phase = "Schreiben"
    img_dir = os.path.join(os.path.dirname(out), "img")
    os.makedirs(img_dir, exist_ok=True)
    for old in glob.glob(os.path.join(img_dir, "abbildung-*.png")):
        os.remove(old)  # figures of an earlier run of this book
    figures = 0
    for i, p in enumerate(paras):
        if p.startswith("@@IMG|"):
            figures += 1
            name = f"abbildung-{figures:03d}.png"
            shutil.copy(p[len("@@IMG|"):], os.path.join(img_dir, name))
            paras[i] = f"![Abbildung {figures}](img/{name})"
    body = "\n\n".join(p if is_heading(p) or p.startswith("![") else md_escape(p)
                       for p in paras)
    text, stats = mdbook.fin_text(header + cover_md + body + "\n")
    if cover is not None:
        cover.save(os.path.join(img_dir, "cover.png"))
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, out)  # never leaves a half-written file behind
    shutil.rmtree(run.shots, ignore_errors=True)

    print(mdbook.stats_line(stats))
    print(f"Datei: {out}")
    print(f"Seiten: {len(paths)} (davon Cover: {'ja' if cover_md else 'nein'}), "
          f"Ueberschriften: {len(entries)}, Abbildungen: {figures}, "
          f"Woerter: {len(text.split())}")
    code = 0
    if stats["broken"] or stats["dup"] or stats["leftover_markers"]:
        print("Warnung: Linkpruefung nicht sauber (broken/dup/leftover_markers oben); "
              "der Text enthaelt vermutlich '@@' aus der Texterkennung.")
    if at_end is False and a.seiten is None:
        print(f"Warnung: Buchende NICHT erreicht: nach {len(paths)} Seiten abgebrochen "
              f"(Obergrenze {MAX_PAGES}). Die Datei ist unvollstaendig.")
        code = EXIT_INCOMPLETE
    if captured:
        print("Hinweis: Die Kindle-Leseposition steht jetzt auf der zuletzt gelesenen Seite.")
    print("Der Text ist Texterkennung und nicht korrekturgelesen.")
    return code


def report_failure(run, msg, tb=None, keep=False):
    """Print what failed and where; keep page images if there are any."""
    lines = [f"Abbruch in Phase '{run.phase}': {msg}"]
    folder = run.shots if run.shots and os.path.isdir(run.shots) else None
    if tb:
        if folder:
            with open(os.path.join(folder, ERROR_LOG), "w", encoding="utf-8") as f:
                f.write(tb)
            lines.append(f"Details: {os.path.join(folder, ERROR_LOG)}")
        else:
            lines.append("Details:\n" + tb)
    pages = glob.glob(os.path.join(folder, "page-*.png")) if folder else []
    if pages and read_run_info(folder).get("status") == "aufgenommen":
        lines.append(f"{len(pages)} Seitenbilder erhalten in: {folder}\n"
                     "Derselbe Befehl noch einmal verwendet sie weiter, ohne neu zu blaettern.")
    elif folder and (tb or keep):
        lines.append(f"Ordner zur Kontrolle erhalten: {folder} (kann danach geloescht werden)")
    elif folder:
        shutil.rmtree(folder, ignore_errors=True)
    print("\n".join(lines), file=sys.stderr)


def main(argv=None):
    a = build_parser().parse_args(argv)
    run = Run(a)
    try:
        code = run_tool(a, run)
    except InputError as e:
        print(f"Eingabefehler: {e}", file=sys.stderr)
        code = EXIT_INPUT
    except KindleError as e:
        report_failure(run, str(e), keep=e.keep)
        code = EXIT_ABORT
    except KeyboardInterrupt:
        report_failure(run, "mit Ctrl+C abgebrochen.")
        code = EXIT_ABORT
    except Exception as e:  # unexpected: keep the details for diagnosis
        report_failure(run, f"Unerwarteter Fehler: {type(e).__name__}: {e}",
                       tb=traceback.format_exc())
        code = EXIT_ABORT
    sys.exit(code)


if __name__ == "__main__":
    main()
