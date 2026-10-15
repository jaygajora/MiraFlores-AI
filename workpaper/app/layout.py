"""Lay out a simulated source page as a form, not a paragraph.

The packet gives each page's printed text and, for each extracted value, the
characters it was read from (we locate them; the packet's `position` boxes are
synthetic and random, so they cannot drive layout). This module turns the text
into blocks a reviewer recognises from paper:

  heading  - form name / parties line
  fields   - a grid of labelled boxes ("Box 1  104,600.00")
  table    - repeated records: brokerage lots, crypto lots, mileage trips
  text     - anything else, kept as prose

Every block cell keeps its character span in the original text, so the anchors
(extracted values) land in the right box and the trace still ends at the exact
words. A real PDF renderer would implement the same contract with page
coordinates instead of character spans.
"""
from __future__ import annotations

import re

ABBREV = {"Inc", "Co", "Dr", "St", "No", "N.A", "U.S", "LLC", "LLP", "Corp", "Ltd", "vs", "Ave", "Blvd", "Rd", "Jr", "Sr"}
VALUE_RE = re.compile(
    r"\d\d/\d\d/\d{4}|\d{4}-\d\d-\d\d|\d\d/\d{4}"                  # dates
    r"|\d{2}-\d{7}|\d{3}-\d\d-\d{4}"                               # EIN / SSN
    r"|(?:(?:SEK|USD|\$)\s?)?-?\(?\d[\d,]*(?:\.\d+)?\)?%?"          # money / numbers
)
TAIL_VALUE = re.compile(r"(?:\s|^|:\s?)((?:(?:SEK|USD|\$)\s?)?-?\(?\d[\d,]*(?:\.\d+)?\)?%?|\d\d/\d\d/\d{4}|\d{4}-\d\d-\d\d|\d\d/\d{4}|\d{2}-\d{7}|\d{3}-\d\d-\d{4}|[A-Z]{2}|checked|none|blank|\(blank\))$")
KEYWORDS = ["wash sale loss disallowed", "adjusted basis", "gross proceeds", "acquired", "sold", "proceeds", "basis", "cost"]
TRIP_RE = re.compile(r"^(\d{4}-\d\d-\d\d) (.+?) \(([^)]+)\) (\d[\d,]*) mi$")


def clauses(text: str) -> list[tuple[int, int]]:
    """Split printed text into clauses at '; ' and sentence ends, keeping exact offsets."""
    cuts = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == ";" and i + 1 < n and text[i + 1] == " ":
            cuts.append((i, i + 2))
        elif ch == "." and (i + 1 == n or (i + 2 < n and text[i + 1] == " " and (text[i + 2].isupper() or text[i + 2].isdigit() or text[i + 2] == "("))):
            word = re.search(r"([A-Za-z.]+)$", text[:i])
            w = word.group(1) if word else ""
            if w.rstrip(".") not in ABBREV:
                cuts.append((i, min(n, i + 2)))
        elif ch == ":" and i + 2 < n and text[i + 1] == " " and text[i + 2].islower() and re.search(r"\d$", text[:i]):
            cuts.append((i, i + 2))
        elif ch == ":" and i + 1 < n and text[i + 1] == " " and re.search(r"(detail|statement|summary|Transactions|Sold lots|Lots still held|Adjusted cost basis|confirmations)$", text[:i]):
            cuts.append((i + 1, i + 2))
        i += 1
    spans = []
    start = 0
    for a, b in cuts:
        if a > start:
            spans.append((start, a))
        start = b
    if start < n:
        spans.append((start, n))
    # trim whitespace
    out = []
    for a, b in spans:
        while a < b and text[a] == " ":
            a += 1
        while b > a and text[b - 1] in " .":
            b -= 1
        if b > a:
            out.append((a, b))
    return out


def _record(text: str, a: int, b: int) -> dict | None:
    """A repeated record: an item followed by keyword/value pairs (lots)."""
    s = text[a:b]
    hits = []
    for kw in KEYWORDS:
        for m in re.finditer(r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])", s):
            if any(m.start() < h[1] and h[0] < m.end() for h in hits):
                continue
            hits.append((m.start(), m.end(), kw))
    hits.sort()
    kws = [h[2] for h in hits]
    if not (("sold" in kws and ("proceeds" in kws or "gross proceeds" in kws)) or ("acquired" in kws and ("cost" in kws or "adjusted basis" in kws))):
        return None
    cells = {}
    item_end = hits[0][0]
    cells["item"] = (a, a + item_end)
    tail = None
    for i, (_hs, he, kw) in enumerate(hits):
        vs = he + 1
        ve = hits[i + 1][0] - 1 if i + 1 < len(hits) else len(s)
        seg = s[vs:ve] if ve > vs else ""
        if i + 1 == len(hits):
            m = re.match(r"^(\([^)]*\)|\S+(?: \([^)]*\))?)(?: (.*))?$", seg)
            if m and m.group(2):
                ve = vs + len(m.group(1))
                tail = (a + ve + 1, a + len(s))
        while ve > vs and s[ve - 1] in ", ":
            ve -= 1
        cells["sold" if kw == "sold" else "proceeds" if kw in ("proceeds", "gross proceeds") else kw] = (a + vs, a + max(vs, ve))
    if tail:
        cells["term"] = tail
    return {"kind": "lots", "cells": cells}


def _trip(text: str, a: int, b: int) -> dict | None:
    m = TRIP_RE.match(text[a:b])
    if not m:
        return None
    return {"kind": "trips", "cells": {"date": (a + m.start(1), a + m.end(1)), "place": (a + m.start(2), a + m.end(2)),
                                       "purpose": (a + m.start(3), a + m.end(3)), "miles": (a + m.start(4), a + m.end(4))}}


DATED_RE = re.compile(r"^(\d{4}-\d\d-\d\d|\d\d/\d\d/\d{4}) (\d[\d,]*\.\d\d)(?: (.+))?$")


def _dated(text: str, a: int, b: int) -> dict | None:
    m = DATED_RE.match(text[a:b])
    if not m:
        return None
    cells = {"date": (a + m.start(1), a + m.end(1)), "amount": (a + m.start(2), a + m.end(2))}
    if m.group(3):
        cells["detail"] = (a + m.start(3), a + m.end(3))
    return {"kind": "dated", "cells": cells}


def _fields(text: str, a: int, b: int) -> list[dict] | None:
    """'Label value' clauses (one or several, e.g. 'Box 12 D 7,400.00, W 2,500.00')."""
    s = text[a:b]
    if len(s) > 160:
        return None
    parts = [(m.start(), m.end()) for m in re.finditer(r"(?:[^,]|,(?! ))+", s)]
    # multi-valued box: every comma part ends with a value
    if len(parts) > 1 and all(TAIL_VALUE.search(s[p0:p1].strip()) for p0, p1 in parts):
        first = s[parts[0][0]:parts[0][1]]
        prefix = re.match(r"^(Box \w+|[A-Z][a-z]+:?)\s", first)
        out = []
        for j, (p0, p1) in enumerate(parts):
            seg = s[p0:p1]
            lead = len(seg) - len(seg.lstrip())
            f = _one_field(text, a + p0 + lead, a + p1)
            if not f:
                return None
            if j > 0 and prefix and not f["label"].startswith(prefix.group(1).rstrip(":")) and len(f["label"]) <= 4:
                f["label"] = f"{prefix.group(1).rstrip(':')} {f['label']}"
            out.append(f)
        return out
    f = _one_field(text, a, b)
    return [f] if f else None


def _one_field(text: str, a: int, b: int) -> dict | None:
    s = text[a:b]
    m = TAIL_VALUE.search(s)
    if not m:
        return None
    label = s[:m.start(1)].rstrip(" :")
    if re.fullmatch(r"[A-Z]{2}", m.group(1)) and not label.startswith("Box"):
        return None
    if not label or len(label) > 90 or not re.search(r"[A-Za-z]", label):
        return None
    # a sentence with several values is prose, not a field
    if len(VALUE_RE.findall(label)) > 2 and not label.startswith("Box"):
        return None
    return {"label": label, "label_span": [a, a + len(label)], "value_span": [a + m.start(1), a + m.end(1)], "value": m.group(1)}


def layout(text: str) -> list[dict]:
    blocks: list[dict] = []
    cl = []
    for a, b in clauses(text):
        # "Prefix: <field or record>" -> heading-ish prefix + parsable rest
        m = re.search(r": (?=\S)", text[a:b])
        if m and m.start() < 70:
            ra = a + m.end()
            if (_trip(text, ra, b) or _record(text, ra, b) or _dated(text, ra, b) or _fields(text, ra, b)) and not _fields(text, a, b):
                cl.append((a, a + m.start() + 1))
                cl.append((ra, b))
                continue
        cl.append((a, b))
    for idx, (a, b) in enumerate(cl):
        rec = _trip(text, a, b) or _record(text, a, b) or _dated(text, a, b)
        if rec:
            last = blocks[-1] if blocks else None
            if last and last["type"] == "table" and last["kind"] == rec["kind"]:
                last["rows"].append(rec["cells"])
            else:
                blocks.append({"type": "table", "kind": rec["kind"], "rows": [rec["cells"]]})
            continue
        fs = _fields(text, a, b) if idx > 0 else None
        if fs:
            last = blocks[-1] if blocks else None
            if last and last["type"] == "fields":
                last["items"] += fs
            else:
                blocks.append({"type": "fields", "items": fs})
            continue
        btype = "heading" if not blocks and idx == 0 else "text"
        last = blocks[-1] if blocks else None
        if btype == "text" and last and last["type"] == "text":
            last["spans"].append([a, b])
        else:
            blocks.append({"type": btype, "spans": [[a, b]]})
    # tables: fixed column order present in any row
    order = ["item", "date", "amount", "detail", "place", "purpose", "miles", "acquired", "cost", "sold", "proceeds", "basis", "adjusted basis", "wash sale loss disallowed", "term"]
    titles = {"item": "Item", "date": "Date", "amount": "Amount", "detail": "Detail", "place": "Destination", "purpose": "Purpose", "miles": "Miles", "acquired": "Acquired",
              "cost": "Cost", "sold": "Sold", "proceeds": "Proceeds", "basis": "Basis", "adjusted basis": "Adjusted basis",
              "wash sale loss disallowed": "Wash sale disallowed", "term": "Term"}
    numeric = {"amount", "miles", "cost", "proceeds", "basis", "adjusted basis", "wash sale loss disallowed"}
    for bl in blocks:
        if bl["type"] == "table":
            cols = [c for c in order if any(c in r for r in bl["rows"])]
            bl["columns"] = [{"key": c, "label": titles[c], "numeric": c in numeric} for c in cols]
            bl["rows"] = [{c: list(r[c]) if c in r else None for c in cols} for r in bl["rows"]]
    # merge tiny field groups that are really a single heading line (e.g. 'Form W-2 2025')
    if blocks and blocks[0]["type"] == "fields" and len(blocks[0]["items"]) == 1 and len(cl) > 1:
        it = blocks[0]["items"][0]
        blocks[0] = {"type": "heading", "spans": [[it["label_span"][0], it["value_span"][1]]]}
    return blocks
