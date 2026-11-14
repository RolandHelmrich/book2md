"""Markdown helpers for book2md.

Paragraphs that are headings arrive as markers "@@N|Title" (N = level 1..6).
toc_text() builds the header with a linked table of contents from those headings,
fin_text() turns the markers into headings with anchors and checks the links.
"""
import re

MARKER_RE = re.compile(r"^@@(\d)\|(.+)$")


def slug(t):
    t = t.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "abschnitt"


def uniq(seen, t):
    # repeated titles ("Das große Bild" in two chapters) get -2, -3 ... in book order
    s = slug(t)
    seen[s] = seen.get(s, 0) + 1
    return s if seen[s] == 1 else f"{s}-{seen[s]}"


def headings(paras):
    """[(level, title)] of all heading markers, in book order."""
    out = []
    for p in paras:
        m = MARKER_RE.match(p)
        if m:
            out.append((int(m.group(1)), m.group(2)))
    return out


def toc_text(entries, title, author=""):
    """Header (title, optional author) plus nested links for [(level, title)]."""
    out = [f"# {title}", ""]
    if author:
        out += [f"*{author}*", ""]
    if entries:
        out += ["## Inhalt", ""]
        seen = {}
        top = min(lvl for lvl, _ in entries)
        for lvl, name in entries:
            out.append("  " * (lvl - top) + f"- [{name}](#{uniq(seen, name)})")
        out += [""]
    out += ["---", ""]
    return "\n".join(out) + "\n"


def fin_text(text):
    """Resolve @@N|Title markers; return (text, stats)."""
    seen = {}

    def head(m):
        lvl, name = int(m.group(1)), m.group(2)
        return f'<a id="{uniq(seen, name)}"></a>\n\n{"#" * lvl} {name}'

    text = re.sub(r"^@@(\d)\|(.+)$", head, text, flags=re.M)
    ids = re.findall(r'<a id="([^"]+)"', text)
    links = re.findall(r"\]\(#([^)]+)\)", text)
    stats = {
        "links": len(links),
        "anchors": len(set(ids)),
        "broken": sorted({l for l in links if l not in set(ids)}),
        "dup": sorted({i for i in ids if ids.count(i) > 1}),
        "leftover_markers": len(re.findall(r"@@", text)),
    }
    return text, stats


def stats_line(s):
    return (f"links={s['links']} anchors={s['anchors']} broken={s['broken']} "
            f"dup={s['dup']} leftover_markers={s['leftover_markers']}")
