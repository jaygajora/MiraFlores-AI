"""Read models for the UI: line trace, value, document, return tree, compare, search, exports."""
from __future__ import annotations

import html
import json
import re
from typing import Any

from . import auth
from .checks import _variants, variances
from .domain import AREA_TITLES, area_for_line
from .layout import layout
from .packet import FORM_ORDER, FORM_TITLES
from .state import Workpaper

RENDERER = {"kind": "synthetic-form", "note": "Pages are laid out from printed_content (header, labelled boxes, tables). "
                                               "A PDF renderer can replace this: anchors are the same (doc, page, field), placed by position instead of character span."}


# ---------------------------------------------------------------------- masking helpers
def _layout(u: dict | None, text: str, revealed: bool = False) -> list[dict]:
    blocks = layout(text)
    if not (revealed and u and u.get("clearance")):
        for b in blocks:
            for it in b.get("items", []):
                it["label"] = auth.mask_text(it["label"])
                it["value"] = auth.mask_text(it["value"])
    return blocks


def _mask(u: dict | None, text: str, revealed: bool = False) -> str:
    if revealed and u and u.get("clearance"):
        return text
    return auth.mask_text(text)


# ---------------------------------------------------------------------- span location
def locate(page: str, e: dict) -> list[int] | None:
    if e["value_type"] == "boolean":
        if e["value"] is not True:
            return None
        e = {**e, "text_as_read": "checked"}
    vs = sorted({v for v in _variants(e) if v and len(v) >= 2}, key=len, reverse=True)
    cands = []
    for v in vs:
        for m in re.finditer(re.escape(v), page):
            # avoid matching inside a longer number
            a, b = m.start(), m.end()
            if a > 0 and (page[a - 1].isdigit() or page[a - 1] == ","):
                continue
            if b < len(page) and page[b].isdigit():
                continue
            if b + 1 < len(page) and page[b] in ".," and page[b + 1].isdigit():
                continue
            cands.append((a, b))
        if cands:
            break
    if not cands:
        return None
    if len(cands) == 1:
        return list(cands[0])
    label = e["label"]
    toks = [t for t in re.findall(r"[A-Za-z0-9]+", label) if len(t) >= 2 and t.lower() not in ("box", "the", "of", "and", "lot", "total", "amount")]
    lot = re.match(r"([A-Z]+\d+)_", e["field"])
    anchors = []
    if lot:
        anchors += [m.end() for m in re.finditer(r"\b" + re.escape(lot.group(1)) + r"\b", page)]
    mbox = re.match(r"box(\d+[a-z]?)", e["field"])
    if mbox:
        anchors += [m.end() for m in re.finditer(r"Box " + re.escape(mbox.group(1)) + r"\b", page, re.I)]
    for t in toks:
        anchors += [m.end() for m in re.finditer(re.escape(t), page, re.I)]
    if not anchors:
        return list(cands[0])
    best = min(cands, key=lambda c: min((c[0] - a) if c[0] >= a else 10_000 + (a - c[0]) for a in anchors))
    return list(best)


# ---------------------------------------------------------------------- line detail
def line_detail(w: Workpaper, key: str, u: dict | None) -> dict:
    p = w.p
    s = w.state()
    line = p.current.lines.get(key)
    eff = w.effective()
    if not line and key not in eff["added"]:
        # may exist in an older version only
        for vn in ("v2", "v1"):
            if key in p.versions[vn].lines:
                line = p.versions[vn].lines[key]
                break
        if not line:
            return {"key": key, "missing": True}
    line = line or {"key": key, "label": eff["added"][key]["label"], "value": 0, "rule": "WORKPAPER", "inputs": [], "sources": [],
                    "form": key.split(".")[0], "jurisdiction": "federal", "line": key.split(".", 1)[1]}
    tree = p.trace_down(key, max_depth=1) if key in p.current.lines else {"key": key, "label": line["label"], "value": 0, "inputs": [], "sources": []}
    # big fan-in (e.g. 8949 totals with 110 lots): summarize instead of swamping
    kids = tree.get("inputs", [])
    summarized = None
    if len(kids) > 25:
        kids_sorted = sorted(kids, key=lambda c: -abs(c.get("value") or 0) if isinstance(c.get("value"), (int, float)) else 0)
        summarized = {"count": len(kids), "shown": 12, "sum": round(sum(c["value"] for c in kids if isinstance(c.get("value"), (int, float))), 2),
                      "flagged": [c["key"] for c in kids if c["key"] in eff["delta"] or "basis 0.00" in c.get("label", "")]}
        tree["inputs"] = kids_sorted[:12] + [c for c in kids if c["key"] in summarized["flagged"] and c not in kids_sorted[:12]]
    for c in tree.get("inputs", []):
        c["workpaper"] = w.value_of(c["key"])
        c["adjusted"] = c["key"] in eff["delta"]
        c["verify"] = w.line_verification(c["key"])["status"]
    for src in tree.get("sources", []):
        if src.get("kind") == "value":
            src["verify"] = "verified" if s.verifications.get(src["ref"]) else "unverified"
    used = p.used_by(key)
    path = _path_to_total(w, key)
    py = p.prior_line(key)
    var = next((v for v in variances(p, s.standards.get("variance_review", {})) if v["key"] == key), None)
    adjs = [a for a in w.active_adjustments(s) if a["line"] == key] + [a for a in s.adjustments.values() if a["line"] == key and a["status"] == "reverted"]
    notes = [n for n in s.notes.values() if n["target"] == key]
    fs = [f for f in w.findings() if key in f["lines"] or key in f["evidence"]]
    hist = [w.describe(e) for e in s.events if e["target"] == key or (e["kind"] == "adjustment.recorded" and e["data"].get("line") == key)]
    versions = {vn: (v.lines[key]["value"] if key in v.lines else None) for vn, v in p.versions.items()}
    vchanges = []
    for vn in ("v2", "v3"):
        ch = next((c for c in p.versions[vn].raw["changes_from_previous"] if c["key"] == key), None)
        if ch:
            vchanges.append({"version": vn, **ch, "trigger": p.versions[vn].trigger})
    return {
        "key": key, "label": line["label"], "form": line["form"], "form_title": FORM_TITLES.get(line["form"], line["form"]),
        "area": area_for_line(key, line["form"]), "area_title": AREA_TITLES[area_for_line(key, line["form"])],
        "jurisdiction": line.get("jurisdiction"), "engine_value": line["value"], "workpaper_value": w.value_of(key) if key in p.current.lines else eff["delta"].get(key),
        "delta": eff["delta"].get(key), "stale": [s.adjustments[a] ["reason"] for a in eff["stale"].get(key, [])][:5], "needs_recompute": key in eff["stale"],
        "rule": line["rule"], "rule_text": p.rules.get(line["rule"]), "note": line.get("note"), "trace": tree, "summarized": summarized,
        "used_by": [{"key": k, "label": p.current.lines[k]["label"], "value": p.current.lines[k]["value"], "workpaper": w.value_of(k)} for k in used[:40]],
        "used_by_count": len(used), "path_to_total": path,
        "prior": {"value": py, "label": p.prior["return_2024"]["line_labels"].get(key), "source": p.prior["return_2024"]["line_sources"].get(key)} if py is not None else None,
        "variance": var, "explanation": s.explanations.get(key), "adjustments": adjs, "verification": w.line_verification(key, s),
        "notes": notes, "findings": [_finding_brief(f) for f in fs], "history": hist, "versions": versions, "version_changes": vchanges,
        "category": __import__("app.domain", fromlist=["category_for_line"]).category_for_line(key, line["form"]),
        "attachments": [a for a in s.attachments if a["target"] == key],
    }


def _path_to_total(w: Workpaper, key: str) -> list[dict]:
    """Shortest consumer path from this line to federal total tax (else California total tax)."""
    p = w.p
    from collections import deque

    def bfs(goals):
        q = deque([[key]])
        seen = {key}
        while q:
            path = q.popleft()
            if path[-1] in goals and len(path) > 1:
                return path
            for c in p.current.consumers.get(path[-1], []):
                if c not in seen:
                    seen.add(c)
                    q.append([*path, c])
        return None
    path = bfs({"F1040.24", "F1040.37"}) or bfs({"F540NR.64", "F540NR.97"}) or []
    return [{"key": k, "label": p.current.lines[k]["label"], "linear": k in p.current.signs} for k in path]


def _finding_brief(f: dict) -> dict:
    return {k: f.get(k) for k in ("id", "title", "severity", "status", "kind", "effect", "source")}


# ---------------------------------------------------------------------- value detail
def value_detail(w: Workpaper, ev: str, u: dict | None, revealed=False) -> dict:
    p = w.p
    s = w.state()
    e = p.values[ev]
    page = p.page_text(e["document_id"], e["page"])
    return {"id": ev, **{k: e[k] for k in ("document_id", "page", "field", "label", "value_type", "text_as_read", "confidence", "position")},
            "value": auth.mask_value(e["value"], e["value_type"]) if not (revealed and u and u.get("clearance")) else e["value"],
            "doc_title": p.docs[e["document_id"]]["title"], "landing": p.landing_for_value(ev),
            "landing_lines": [{"key": k, "label": p.current.lines[k]["label"] if k in p.current.lines else k} for k in p.landing_for_value(ev).get("lines", [])],
            "page_text": _mask(u, page, revealed), "span": locate(page, e), "layout": _layout(u, page, revealed),
            "page_values": [{"id": x, "label": p.values[x]["label"], "span": locate(page, p.values[x]), "confidence": p.values[x]["confidence"],
                             "landing": p.landing_for_value(x)} for x in p.values_by_doc.get(e["document_id"], []) if p.values[x]["page"] == e["page"]],
            "page_count": p.docs[e["document_id"]]["page_count"], "verifications": s.verifications.get(ev, []),
            "findings": [_finding_brief(f) for f in w.findings() if ev in f["evidence"]],
            "notes": [n for n in s.notes.values() if n["target"] == ev], "renderer": RENDERER}


# ---------------------------------------------------------------------- document detail
def document_detail(w: Workpaper, did: str, u: dict | None, revealed=False) -> dict:
    p = w.p
    s = w.state()
    d = p.docs[did]
    idx = next((x for x in w.document_index() if x["id"] == did), None)
    pages = []
    for pg in d["pages"]:
        text = pg["printed_content"]
        vals = []
        for ev in p.values_by_doc.get(did, []):
            e = p.values[ev]
            if e["page"] != pg["page"]:
                continue
            land = p.landing_for_value(ev)
            vals.append({"id": ev, "label": e["label"], "field": e["field"], "value": auth.mask_value(e["value"], e["value_type"]) if not revealed else e["value"],
                         "text_as_read": e["text_as_read"] if e["value_type"] not in ("ssn", "account_number") or revealed else auth.mask_text(str(e["text_as_read"])),
                         "confidence": e["confidence"], "position": e["position"], "landing": land, "span": locate(text, e),
                         "verified": bool(s.verifications.get(ev)), "value_type": e["value_type"]})
        pages.append({"page": pg["page"], "text": _mask(u, text, revealed), "values": vals, "layout": _layout(u, text, revealed),
                      "unread": d["extraction"]["status"] == "partial" and f"Page {pg['page']}" in (d["extraction"]["reason"] or "")})
    related = []
    sb = p.superseded_by(did)
    if sb:
        related.append({"ref": sb, "relation": "corrected version (supersedes this)"})
    for other in p.raw["documents"]:
        if p.superseded_by(other["id"]) == did:
            related.append({"ref": other["id"], "relation": "original (superseded by this)"})
    if did in p.duplicate_notes:
        m = re.search(r"\((D\d\d)\)", p.duplicate_notes[did]) or re.search(r"of (D\d\d)", p.duplicate_notes[did])
        if m:
            related.append({"ref": m.group(1), "relation": "same document (this is a second image)"})
    for o, note in p.duplicate_notes.items():
        if did in note and o != did:
            related.append({"ref": o, "relation": "second image of this document"})
    return {"id": did, "title": d["title"], "type": d["document_type"], "issuer": d["issuer"], "belongs_to": d["belongs_to"],
            "tax_year": d["tax_year"], "received_at": d["received_at"], "uploaded_by": d["uploaded_by"], "file_name": d["file_name"],
            "page_count": d["page_count"], "extraction": d["extraction"], "pages": pages, "index": idx, "related": related,
            "findings": [_finding_brief(f) for f in w.findings() if any(p.doc_for_ref(r) == did for r in f["evidence"])],
            "notes": [n for n in s.notes.values() if p.doc_for_ref(n["target"]) == did],
            "attachments": [a for a in s.attachments if a["target"] == did], "renderer": RENDERER, "area": w.doc_area(did),
            "history": [w.describe(e) for e in s.events if e["target"] and p.doc_for_ref(e["target"]) == did]}


# ---------------------------------------------------------------------- return tree
def return_tree(w: Workpaper, form: str | None = None, box: str | None = None) -> dict:
    p = w.p
    s = w.state()
    eff = w.effective()
    fs = w.findings()
    by_line: dict[str, list] = {}
    for f in fs:
        if f["status"] in ("open", "client_answered"):
            for k in f["lines"]:
                by_line.setdefault(k, []).append(f["id"])
    notes_by = {}
    for n in s.notes.values():
        if n["status"] == "open":
            notes_by.setdefault(n["target"], []).append(n["id"])
    passes_by = {}
    for x in w.checks()["passes"]:
        for k in x["lines"]:
            passes_by[k] = True
    forms = {}
    for k in p.current.order:
        forms.setdefault(p.current.lines[k]["form"], []).append(k)
    for k in eff["added"]:
        forms.setdefault(k.split(".")[0], []).append(k)
    out = []
    for f in sorted(forms, key=lambda x: FORM_ORDER.index(x) if x in FORM_ORDER else 99):
        if form and f != form:
            continue
        keys = forms[f]
        rows = []
        lots = 0
        for k in keys:
            if f == "F8949" and not k.endswith(".total") and not form:
                lots += 1
                continue
            if f == "F8949" and box and not k.startswith(f"F8949.{box}."):
                continue
            ln = p.current.lines.get(k) or {"label": eff["added"][k]["label"], "value": 0, "rule": "WORKPAPER"}
            ver = "verified" if s.verifications.get(k) else ("recalculated" if k in passes_by else "")
            rows.append({"key": k, "label": ln["label"], "engine": ln["value"], "workpaper": w.value_of(k) if k in p.current.lines else eff["delta"].get(k),
                         "delta": eff["delta"].get(k), "direct": k in eff["direct"], "stale": k in eff["stale"], "rule": ln["rule"],
                         "findings": by_line.get(k, []), "notes": notes_by.get(k, []), "verify": ver, "added": k in eff["added"],
                         "area": area_for_line(k, f)})
        out.append({"form": f, "title": FORM_TITLES.get(f, f), "lines": rows, "lots": lots,
                    "jurisdiction": "california" if f in ("SchCA540NR", "F540NR", "ScheduleS", "FTB3885A", "FTB5805") else "federal",
                    "open_findings": sum(len(r["findings"]) for r in rows)})
    return {"forms": out}


# ---------------------------------------------------------------------- compare
def compare(w: Workpaper, a: str, b: str) -> dict:
    p = w.p

    def values(v: str) -> dict:
        if v in p.versions:
            return {k: ln["value"] for k, ln in p.versions[v].lines.items()}
        if v == "workpaper":
            vals = {k: w.value_of(k) for k in p.current.lines}
            for k in w.effective()["added"]:
                vals[k] = w.effective()["delta"].get(k)
            return vals
        if v == "2024":
            return dict(p.prior["return_2024"]["lines"])
        raise KeyError(v)
    va, vb = values(a), values(b)
    rows = []
    for k in list(dict.fromkeys(list(va) + list(vb))):
        x, y = va.get(k), vb.get(k)
        if x == y:
            continue
        if isinstance(x, float) and isinstance(y, float) and abs(x - y) < 0.005:
            continue
        line = p.current.lines.get(k) or next((v.lines[k] for v in p.versions.values() if k in v.lines), None)
        cause = None
        if b in ("v2", "v3"):
            cause = p.versions[b].trigger
        if b == "workpaper":
            adj = [ad for ad in w.active_adjustments() if ad["line"] == k]
            cause = "; ".join(ad["reason"] for ad in adj) if adj else "follows from an adjustment upstream"
        rows.append({"key": k, "label": line["label"] if line else p.prior["return_2024"]["line_labels"].get(k, k), "a": x, "b": y,
                     "change": (y - x) if isinstance(x, (int, float)) and isinstance(y, (int, float)) else None, "cause": cause,
                     "form": line["form"] if line else k.split(".")[0]})
    sa = _summary_of(w, a)
    sb = _summary_of(w, b)
    return {"a": a, "b": b, "rows": rows, "count": len(rows), "summary_a": sa, "summary_b": sb,
            "docs_added": sorted(set(p.versions[b].raw["documents_used"]) - set(p.versions[a].raw["documents_used"])) if a in p.versions and b in p.versions else []}


def _summary_of(w: Workpaper, v: str) -> dict | None:
    if v in w.p.versions:
        return w.p.versions[v].raw["summary"]
    if v == "workpaper":
        return w.summary()["workpaper"]
    return None


# ---------------------------------------------------------------------- search
def search(w: Workpaper, q: str, u: dict | None) -> list[dict]:
    p = w.p
    s = w.state()
    ql = q.lower().strip()
    if not ql:
        return []
    out = []
    for k, ln in p.current.lines.items():
        if ql in k.lower() or ql in ln["label"].lower():
            out.append({"kind": "line", "ref": k, "title": f"{k} {ln['label']}", "sub": f"{ln['value']:,}" if isinstance(ln["value"], (int, float)) else str(ln["value"])})
    for did in w.visible_docs(s):
        d = p.docs[did]
        hit = ql in d["title"].lower() or ql in did.lower()
        txt = " ".join(pg["printed_content"] for pg in d["pages"])
        i = txt.lower().find(ql)
        if hit or i >= 0:
            snip = auth.mask_text(txt[max(0, i - 50): i + 80]) if i >= 0 else d["issuer"]
            out.append({"kind": "document", "ref": did, "title": f"{did} {d['title']}", "sub": snip})
    for f in w.findings():
        if ql in f["title"].lower() or ql in f["summary"].lower():
            out.append({"kind": "finding", "ref": f["id"], "title": f["title"], "sub": f["status"]})
    for n in s.notes.values():
        if ql in n["text"].lower():
            out.append({"kind": "note", "ref": n["id"], "title": n["text"][:90], "sub": f"on {n['target']}"})
    for qa in p.questionnaire.values():
        if ql in qa["question"].lower() or ql in qa["answer"].lower():
            out.append({"kind": "answer", "ref": qa["id"], "title": qa["question"], "sub": qa["answer"][:100]})
    for m in w.visible_messages(s):
        if ql in m["text"].lower():
            out.append({"kind": "message", "ref": m["id"], "title": f"{m['from']}: {m['text'][:80]}", "sub": m["sent_at"][:10]})
    order = {"line": 0, "finding": 1, "document": 2, "answer": 3, "message": 4, "note": 5}
    out.sort(key=lambda x: order.get(x["kind"], 9))
    return out[:80]


# ---------------------------------------------------------------------- exports (self-contained HTML)
CSS = """body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#1d232b}
h1{font-size:22px}h2{font-size:17px;margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:4px}h3{font-size:14px}
table{border-collapse:collapse;width:100%;margin:8px 0}td,th{border-bottom:1px solid #eee;padding:4px 6px;text-align:left;vertical-align:top}
td.n{text-align:right;font-variant-numeric:tabular-nums}.muted{color:#68707a}.box{background:#f6f7f9;padding:10px 12px;border-radius:6px;white-space:pre-wrap}
code{font-size:12px}.tag{display:inline-block;padding:0 6px;border-radius:4px;background:#eef;font-size:12px}"""


def _money(x) -> str:
    if isinstance(x, (int, float)):
        return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.2f}"
    return html.escape(str(x)) if x is not None else ""


def _names(p) -> str:
    return " and ".join(x["name"] for x in p.people.values() if x["role"] in ("taxpayer", "spouse"))


def _evidence_docs(w: Workpaper, codes: tuple[str, ...]) -> tuple[list[dict], set[str], set[str]]:
    """Findings with these codes, the documents they cite, and the lines they touch."""
    fs = [f for f in w.findings() if f["code"] in codes]
    docs = {d for f in fs for r in f["evidence"] for d in [w.p.doc_for_ref(r)] if d}
    lines = {k for f in fs for k in f["lines"]}
    return fs, docs, lines


def notice_packet(w: Workpaper, notice_id: str) -> str:
    """A self-contained record answering an examination letter: no app needed to read it."""
    p = w.p
    s = w.state()
    n = s.notices.get(notice_id) or next(x for x in p.agency["notices"] if x["id"] == notice_id)
    sealed = s.filing.get("sealed")
    chain = w.store.verify_chain()
    parts = [f"<h1>Response record: {html.escape(n['type'])} - tax year {n['tax_year']}</h1>",
             f"<p class=muted>{html.escape(_names(p))} (client {p.raw['packet']['client_id']}). Letter dated {n['dated']}; response due {n.get('response_due', '')}. "
             f"Prepared by {html.escape(p.firm['name'])} from the sealed workpaper. Log integrity: {'verified' if chain['ok'] else 'BROKEN'} "
             f"({chain['checked']} events, head {chain.get('head', '')[:16]}).</p>"]
    if sealed:
        parts.append(f"<p>Return as filed: fingerprint <code>{sealed['fingerprint']}</code>, sealed {sealed['at'][:10]}.</p>")
    touched: set[str] = set()
    for item in n.get("items_under_examination", []):
        parts.append(f"<h2>{html.escape(item)}</h2>")
        low = item.lower()
        if "noncash" in low:
            parts.append(_section_noncash(w, touched))
        if "gross receipts" in low:
            parts.append(_section_receipts(w, touched))
    parts.append("<h2>Audit trail for the items above</h2><table><tr><th>When</th><th>Who</th><th>What</th></tr>")
    for e in s.events:
        t = e["target"] or ""
        line = e["data"].get("line") if isinstance(e["data"], dict) else None
        if t in touched or (line and line in touched) or (p.doc_for_ref(t) or "") in touched:
            d = w.describe(e)
            parts.append(f"<tr><td>{d['sim_at'][:10]}</td><td>{html.escape(d['actor_name'])}</td><td>{html.escape(d['text'])}</td></tr>")
    parts.append("</table>")
    return f"<!doctype html><html><head><meta charset=utf-8><title>Notice response {notice_id}</title><style>{CSS}</style></head><body>{''.join(parts)}</body></html>"


def _doc_block(w: Workpaper, did: str) -> str:
    d = w.p.docs[did]
    pages = "".join(f"<div class=box><b>Page {pg['page']}</b>\n{html.escape(auth.mask_text(pg['printed_content']))}</div>" for pg in d["pages"])
    return f"<h3>{did} {html.escape(d['title'])}</h3><p class=muted>Received {d['received_at'][:10]} from {d['uploaded_by']} ({html.escape(d['file_name'])})</p>{pages}"


def _section_noncash(w: Workpaper, touched: set[str]) -> str:
    keys = [k for k in w.p.current.order if k.startswith("F8283.")] + ["SchA.12"]
    rows = []
    for k in keys:
        ln = w.p.current.lines[k]
        rows.append(f"<tr><td>{k}</td><td>{html.escape(ln['label'])}</td><td class=n>{_money(ln['value'])}</td><td class=n>{_money(w.value_of(k))}</td></tr>")
    docs = sorted({w.p.values[s]["document_id"] for k in keys for s in w.p.current.lines[k]["sources"] if s in w.p.values})
    fs, fdocs, flines = _evidence_docs(w, ("VEHICLE_GIFT_OVER_PROCEEDS",))
    touched |= set(keys) | set(docs) | flines | {f["id"] for f in fs}
    adj = [a for a in w.active_adjustments() if a["line"] in keys]
    expl = "".join(f"<li>{html.escape(a['reason'])} ({_money(a['delta'])}; authority: {html.escape(a['authority'])})</li>" for a in adj)
    return (f"<table><tr><th>Line</th><th>Item</th><th>Engine</th><th>As filed</th></tr>{''.join(rows)}</table>"
            f"<ul>{expl or '<li>No adjustments were made to these lines.</li>'}</ul>" + "".join(_doc_block(w, d) for d in docs))


def _section_receipts(w: Workpaper, touched: set[str]) -> str:
    """Third-party information returns reconciled to the books and to the return."""
    p = w.p
    vis = w.visible_docs()
    necs = p.docs_of("1099-NEC", vis)
    nec = sum(p.val(d["id"], "box1", 0) for d in necs)
    ks = p.docs_of("1099-K", vis)
    k = sum(p.val(d["id"], "box1a", 0) for d in ks)
    books_doc = p.doc_of("books_profit_loss", vis)
    books = p.val(books_doc["id"], "total_income", 0) if books_doc else 0
    dup_f, dup_docs, _ = _evidence_docs(w, ("CARD_SALES_COUNTED_TWICE",))
    dup = k if dup_f else 0
    detail = p.doc_of("books_transaction_detail", vis)
    m = re.search(r"Deposits from clients who issued no Form 1099: ([\d,.]+) from (\d+) small clients", " ".join(pg["printed_content"] for pg in detail["pages"])) if detail else None
    no_1099 = float(m.group(1).replace(",", "")) if m else books - (nec + k - dup)
    filed = w.value_of("SchC.1")
    rows = [(f"Forms 1099-NEC ({len(necs)} payers)", nec), (f"Form 1099-K ({', '.join(d['issuer'] for d in ks)})", k), ("Third-party total", nec + k)]
    if dup:
        rows.append(("Less: card payments reported on both a payer's 1099-NEC and the 1099-K", -dup))
    rows += [(f"Plus: clients who issued no Form 1099{' (' + m.group(2) + ')' if m else ''}", no_1099), ("Gross receipts per books", books),
             ("Gross receipts on the return as filed (Schedule C line 1)", filed)]
    touched |= {"SchC.1"} | {f["id"] for f in dup_f} | dup_docs
    t = "".join(f"<tr><td>{html.escape(a)}</td><td class=n>{_money(b)}</td></tr>" for a, b in rows)
    why = f"<p>{html.escape(dup_f[0]['summary'])}</p>" if dup_f else ""
    show = sorted(dup_docs | ({detail["id"]} if detail else set()))
    return f"<table>{t}</table>{why}" + "".join(_doc_block(w, d) for d in show)


def _todo(w: Workpaper) -> list[str]:
    """Client actions: outside filings and open decisions the workpaper identified."""
    out = []
    for f in w.findings():
        if f["kind"] in ("outside_filing", "planning") and f["source"] == "check":
            if f["code"] == "OUTSIDE_FILINGS":
                out += [part.strip() for part in f["summary"].split(" | ")]
            else:
                out.append(f["title"])
    return out


def client_copy(w: Workpaper) -> str:
    s = w.state()
    sm = w.summary()["workpaper"]
    sealed = s.filing.get("sealed")
    fed, ca = sm["federal"], sm["california"]
    year = w.p.household["tax_year"]
    lines = "".join(f"<tr><td>{k}</td><td>{html.escape(w.p.current.lines[k]['label'])}</td><td class=n>{_money(w.value_of(k))}</td></tr>"
                    for k in ("F1040.1z", "F1040.2b", "F1040.3b", "F1040.7", "F1040.8", "F1040.11", "F1040.12", "F1040.13", "F1040.15", "F1040.24", "F1040.33", "F1040.37"))
    sub = s.filing.get("submission") or {}
    hist = "".join(f"<li>{h['at'][:10]} {html.escape(h['kind'])}</li>" for h in s.filing.get("history", []))
    todo = "".join(f"<li>{html.escape(t)}</li>" for t in _todo(w)) or "<li>Nothing outstanding.</li>"
    owe = lambda x: ("balance due " + _money(x)) if x > 0 else ("refund " + _money(-x))  # noqa: E731
    return (f"<!doctype html><html><head><meta charset=utf-8><title>Client copy {year}</title><style>{CSS}</style></head><body>"
            f"<h1>{year} tax returns: {html.escape(_names(w.p))}</h1><p class=muted>Prepared by {html.escape(w.p.firm['name'])}. "
            f"{'Filed and accepted; fingerprint ' + sealed['fingerprint'] if sealed else 'DRAFT - not yet filed'}</p>"
            f"<h2>Federal Form 1040</h2><table>{lines}</table><p>Total tax {_money(fed['total_tax'])}; payments {_money(fed['payments'])}; {owe(fed['balance_due'])}.</p>"
            f"<h2>California Form 540NR (part-year resident)</h2><p>California AGI {_money(ca['ca_agi'])}; tax {_money(ca['total_tax'])}; "
            f"payments {_money(ca['payments'])}; {owe(ca['balance_due'])}.</p>"
            f"<h2>E-file history</h2><ul>{hist or '<li>Not transmitted</li>'}</ul><p class=muted>Submission {html.escape(str(sub.get('id', '')))}</p>"
            f"<h2>Things for you to do</h2><ul>{todo}</ul></body></html>")


def rollforward(w: Workpaper) -> dict:
    """What next year's preparer opens: carryovers with their sources, open items, client facts, a plan."""
    p = w.p
    s = w.state()
    sm = w.summary()["workpaper"]
    fed_tax, ca_tax = sm["federal"]["total_tax"], sm["california"]["total_tax"]
    co = dict(p.current.raw["carryovers_out"]["federal"])
    src = {"minimum_tax_credit_from_2025_amt": "F6251.11", "scorp_stock_basis_end": "F7203.15", "ira_nondeductible_basis_ngozi": "F8606.14",
           "sep_contribution_not_deductible_for_2025": "Sch1.16"}
    adds = []
    from .reports import _improvement_assets
    for a in _improvement_assets(w):
        adds.append({"item": f"New asset: {a['label']}, {a['cost']:,.0f}, {a['method']} {a['life']} years, in service {a['in_service']}", "source": a["ref"]})
    open_items = [{"item": f["title"], "status": f["status"], "ref": f["id"]} for f in w.findings()
                  if f["kind"] in ("outside_filing", "planning") or f["status"] in ("open", "waiting_client", "deferred")]
    plan_ref = p.raw["planning_reference_2026"]
    plan = {"federal": {"safe_harbor": plan_ref["federal_safe_harbor"], "installment": round(fed_tax * 1.10 / 4),
                        "due": plan_ref["federal_estimate_due_dates"], "basis": f"110% x this year's total tax {fed_tax:,} / 4"},
            "california": {"safe_harbor": plan_ref["california_safe_harbor"],
                           "installments": [round(ca_tax * 1.10 * x) for x in plan_ref["california_installment_percentages"]],
                           "due": plan_ref["california_estimate_due_dates"],
                           "note": "California taxes only California-source income after the move, so 90% of next year's tax is likely far lower."},
            "changes": plan_ref["known_2026_changes_for_this_household"]}
    facts = []
    res = p.household["residency"][-1]
    facts.append(f"{res['state']} residents from {res['from']}")
    for pid, fx in s.household_fixes.items():
        for fld, v in fx.items():
            facts.append(f"{p.people[pid]['name']}: {fld} corrected to {auth.mask_text(v)} (organizer was wrong)")
    for f in w.findings():
        if f["status"] in ("adjusted", "accepted", "decided") and f["kind"] in ("error", "judgment") and f["source"] == "check":
            facts.append(f"Corrected this year, watch next year: {f['title']}")
    if "F7203.15" in p.current.lines and p.current.lines["F7203.15"]["value"] == 0:
        facts.append("S corporation stock basis is zero: distributions are capital gain until income restores basis")
    return {"carryovers": [{"item": k, "amount": v, "from": src.get(k, "carryovers_out")} for k, v in co.items()],
            "california_carryovers": p.current.raw["carryovers_out"]["california"], "added_by_workpaper": adds,
            "open_items": open_items, "plan_2026": plan, "client_facts": facts,
            "retention": {"filed": (s.filing.get("sealed") or {}).get("at", "")[:10], "destroy_after_years": s.standards.get("retention_years", 7)},
            "history_link": "Every carryover keeps a link to the line, document and event it came from."}


def client_portal(w: Workpaper, uid: str) -> dict:
    s = w.state()
    qs = [q for q in s.questions.values() if q.get("to", "client") == "client"]
    sent = s.filing.get("sent")
    appr = s.filing.get("client_approval")
    return {"questions": [{"id": q["id"], "text": q["text"], "status": q["status"], "at": q["at"], "thread": q["thread"]} for q in qs],
            "sent": sent, "approval": appr, "approval_current": bool(appr and sent and appr["fingerprint"] == sent["fingerprint"]),
            "summary": sent["summary"] if sent else None, "filing": {k: v for k, v in s.filing.items() if k in ("history", "sealed", "delivered")},
            "messages": w.visible_messages(s), "documents": [{"id": d["id"], "title": d["title"], "received_at": d["received_at"]}
                                                             for d in w.p.raw["documents"] if d["id"] in w.visible_docs(s) and d["uploaded_by"] == "client"],
            "uploads": [a for a in s.attachments if a["by"] == uid]}


_ = (json, Any)
