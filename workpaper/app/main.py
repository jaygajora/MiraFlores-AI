"""HTTP API and static UI. One process: FastAPI + SQLite + compiled TypeScript."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import auth, commands, reports, views
from .checks import ssn_mismatches, variances
from .domain import AREAS, EFFECT_CATEGORIES
from .packet import Packet
from .state import Workpaper
from .store import EventStore

ROOT = Path(__file__).resolve().parent.parent
PACKET = Path(os.environ.get("PACKET_PATH", ROOT / "data" / "okafor_lindqvist_2025_packet.json"))
DB = os.environ.get("DB_PATH", str(ROOT / "var" / "workpaper.db"))

packet = Packet(PACKET)
store = EventStore(DB)
wp = Workpaper(packet, store)
app = FastAPI(title=f"{packet.raw['packet']['name']} workpaper")
PRESENCE: dict[str, dict] = {}


def me(x_user: str | None) -> dict:
    u = auth.user(packet, x_user or "st-01")
    if not u:
        raise HTTPException(401, "Pick a user")
    return u


def staff_only(u: dict):
    if u["role"] == "client":
        raise HTTPException(403, "Clients see the client portal only")


@app.exception_handler(auth.Denied)
async def denied(_: Request, exc: auth.Denied):
    return JSONResponse({"error": str(exc)}, status_code=403)


@app.exception_handler(commands.CommandError)
async def invalid(_: Request, exc: commands.CommandError):
    return JSONResponse({"error": str(exc)}, status_code=422)


@app.exception_handler(ValueError)
async def bad(_: Request, exc: ValueError):
    return JSONResponse({"error": str(exc)}, status_code=400)


# ---------------------------------------------------------------------- security headers
# The app shell loads one bundled script and one stylesheet from this origin, nothing inline.
APP_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; "
           "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    path = request.url.path
    if path.startswith("/api/export/"):
        resp.headers.setdefault("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'")
    elif path.startswith("/api/files/"):
        resp.headers.setdefault("Content-Security-Policy", "sandbox; default-src 'none'")
    elif not path.startswith("/api/"):
        resp.headers.setdefault("Content-Security-Policy", APP_CSP)
    return resp


# ---------------------------------------------------------------------- session
@app.get("/api/bootstrap")
def bootstrap(x_user: str | None = Header(None)):
    u = me(x_user)
    s = wp.state()
    return {"me": u, "users": auth.users(packet), "perms": sorted(auth.PERMS.get(u["role"], [])), "clock": s.clock,
            "packet": packet.raw["packet"], "firm": packet.firm["name"], "household": _household(u), "areas": [{"id": a, "title": t} for a, t in AREAS],
            "reports": [{"id": r, "title": t} for r, t in reports.REPORTS], "standards": s.standards,
            "effect_categories": EFFECT_CATEGORIES, "timeline_next": wp.next_timeline(s)[:12], "head": s.seq,
            "deadlines": packet.firm["deadlines"], "budget": packet.firm["budget_hours"], "renderer": views.RENDERER}


def _household(u: dict, reveal: bool = False) -> dict:
    h = json.loads(json.dumps(packet.household))
    fixes = wp.state().household_fixes
    for person in h["people"]:
        for f, v in fixes.get(person["id"], {}).items():
            person[f] = v
            person.setdefault("corrected", []).append(f)
        if not (reveal and u.get("clearance")):
            if person.get("ssn"):
                person["ssn"] = auth.mask_text(person["ssn"])
            if person.get("ip_pin"):
                person["ip_pin"] = "••••••"
    if not (reveal and u.get("clearance")):
        b = h["bank_account_for_refund_or_payment"]
        b["routing"] = "•••••" + b["routing"][-4:]
        b["account"] = "••••••" + b["account"][-4:]
    return h


@app.get("/api/household")
def household(reveal: int = 0, x_user: str | None = Header(None)):
    u = me(x_user)
    staff_only(u)
    if reveal:
        wp.command(u["id"], {"type": "reveal", "target": "household", "field": "ssn, ip_pin, bank"})
    return _household(u, bool(reveal))


@app.get("/api/overview")
def overview(x_user: str | None = Header(None)):
    u = me(x_user)
    s = wp.state()
    fs = wp.findings()
    sev = {}
    for f in fs:
        if f["status"] in ("open", "client_answered"):
            sev[f["severity"]] = sev.get(f["severity"], 0) + 1
    ch = wp.changes_since(u["id"])
    deadlines = []
    for d in packet.firm["deadlines"]:
        deadlines.append({**d, "days": _days(s.clock, d["date"])})
    now = time.time()
    return {"clock": s.clock, "summary": wp.summary(s), "steps": wp.required_steps(), "areas": wp.area_status(),
            "open_counts": sev, "findings_total": len(fs), "changes": {"count": ch["count"], "since": ch["since"]},
            "filing": _filing_view(u), "deadlines": deadlines, "timeline_next": wp.next_timeline(s)[:8],
            "approvals": wp.approvals_needed(s), "team": [{"id": t, "name": wp.name(t)} for t in s.team],
            "assignments": s.assignments, "presence": [p for p in PRESENCE.values() if now - p["t"] < 30 and p["user"] != u["id"]],
            "notifications": _notifications(u), "head": s.seq, "chain": store.verify_chain()}


def _days(a: str, b: str) -> int:
    from datetime import date
    return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days


def _notifications(u: dict) -> list[dict]:
    s = wp.state()
    out = []
    for n in s.notes.values():
        if n["status"] == "open" and n.get("assignee") == u["id"]:
            out.append({"kind": "note", "text": f"{wp.name(n['by'])} asked you: {n['text'][:90]}", "ref": n["target"], "id": n["id"]})
    if u["role"] in ("reviewer", "partner"):
        need = [a for a in wp.approvals_needed(s) if (a["level"] == "partner") == (u["role"] == "partner") or u["role"] == "partner"]
        need = [a for a in need if a["by"] != u["id"]]
        if need:
            out.append({"kind": "approval", "text": f"{len(need)} adjustment(s) waiting for your approval", "ref": "approvals"})
    for a in wp.area_status():
        for lvl, rec in a["signoffs"].items():
            if rec["by"] == u["id"] and not rec["valid"]:
                out.append({"kind": "reopened", "text": f"Your {lvl} sign-off on {a['title']} reopened: what you signed changed", "ref": a["area"]})
    for q in s.questions.values():
        if q["status"] == "answered" and q["by"] == u["id"] and not q.get("reviewed"):
            out.append({"kind": "answer", "text": f"Client answered: {q['text'][:70]}", "ref": q["id"]})
    for d in packet.firm["deadlines"]:
        dd = _days(s.clock, d["date"])
        if 0 <= dd <= 21:
            out.append({"kind": "deadline", "text": f"{d['what']} in {dd} days ({d['date']})", "ref": "deadlines"})
    if u["role"] == "client":
        out = []
        for q in s.questions.values():
            if q["status"] == "open" and q.get("to", "client") == "client":
                out.append({"kind": "question", "text": f"Your accountant asks: {q['text'][:90]}", "ref": q["id"]})
        if s.filing.get("sent") and not s.filing.get("client_approval"):
            out.append({"kind": "approve", "text": "Your return is ready for your review and signature", "ref": "approve"})
    return out


def _household_fixes(u: dict) -> list[dict]:
    """Corrections the documents agree on (e.g. an SSN typo in the organizer), offered as one-click fixes."""
    s = wp.state()
    out = []
    for pid, mism, _ in ssn_mismatches(packet, set(packet.docs), s.household_fixes):
        values = {v for v, _ in mism}
        if len(values) != 1:
            continue
        value = values.pop()
        refs = [r for _, r in mism]
        person = packet.people[pid]
        out.append({"person": pid, "name": person["name"], "field": "ssn", "evidence": refs,
                    "value": value if u.get("clearance") else None, "shown": auth.mask_text(value),
                    "reason": f"{', '.join(refs)} show {auth.mask_text(value)}; the organizer differs."})
    return out


def _filing_view(u: dict) -> dict:
    s = wp.state()
    f = s.filing
    stage = "preparing"
    if f.get("sent"):
        stage = "awaiting client approval"
    if f.get("client_approval"):
        stage = "client approved"
    sub = f.get("submission")
    if sub:
        stage = {"pending": "transmitted", "rejected": "rejected", "accepted": "accepted"}.get(sub["result"], stage)
    if f.get("sealed"):
        stage = "filed (sealed)"
    if f.get("amendment_open"):
        stage = "amending"
    ca = f.get("client_approval")
    return {"stage": stage, "extension": f.get("extension"), "sent": f.get("sent"), "client_approval": ca,
            "approval_current": bool(ca and ca["fingerprint"] == wp.return_fingerprint(s)), "submission": sub,
            "history": f.get("history", []), "sealed": f.get("sealed"), "delivered": f.get("delivered"), "post_filing": f.get("post_filing", []),
            "gates": wp.filing_gates(s), "fingerprint": wp.return_fingerprint(s), "amendments": s.amendments, "notices": s.notices,
            "rejection": f.get("last_rejection"), "household_fixes": _household_fixes(u)}


@app.get("/api/filing")
def filing(x_user: str | None = Header(None)):
    return _filing_view(me(x_user))


@app.get("/api/open-items")
def open_items(x_user: str | None = Header(None)):
    u = me(x_user)
    staff_only(u)
    return wp.open_items(u["id"])


@app.get("/api/findings")
def findings(x_user: str | None = Header(None)):
    staff_only(me(x_user))
    return {"findings": wp.findings(), "passes": wp.checks()["passes"]}


@app.get("/api/finding/{fid}")
def finding(fid: str, x_user: str | None = Header(None)):
    staff_only(me(x_user))
    f = wp.finding(fid)
    if not f:
        raise HTTPException(404)
    s = wp.state()
    return {**f, "evidence_resolved": [packet.resolve(r) for r in f["evidence"] if r],
            "notes_full": [s.notes[n] for n in f["notes"]], "adjustments_full": [s.adjustments[a] for a in f["adjustments"]],
            "history": [wp.describe(e) for e in s.events if e["target"] == fid or e["data"].get("finding") == fid]}


@app.get("/api/return")
def return_tree(form: str | None = None, box: str | None = None, x_user: str | None = Header(None)):
    staff_only(me(x_user))
    return views.return_tree(wp, form, box)


@app.get("/api/line/{key}")
def line(key: str, x_user: str | None = Header(None)):
    u = me(x_user)
    staff_only(u)
    return views.line_detail(wp, key, u)


@app.get("/api/value/{ev}")
def value(ev: str, reveal: int = 0, x_user: str | None = Header(None)):
    u = me(x_user)
    staff_only(u)
    if ev not in packet.values:
        raise HTTPException(404)
    if reveal:
        wp.command(u["id"], {"type": "reveal", "target": ev})
    return views.value_detail(wp, ev, u, bool(reveal))


@app.get("/api/documents")
def documents(x_user: str | None = Header(None)):
    staff_only(me(x_user))
    return wp.document_index()


@app.get("/api/document/{did}")
def document(did: str, reveal: int = 0, x_user: str | None = Header(None)):
    u = me(x_user)
    staff_only(u)
    if did not in packet.docs or did not in wp.visible_docs():
        raise HTTPException(404, "Not received yet")
    if reveal:
        wp.command(u["id"], {"type": "reveal", "target": did, "field": "page text"})
    return views.document_detail(wp, did, u, bool(reveal))


@app.get("/api/resolve")
def resolve(ref: str, x_user: str | None = Header(None)):
    me(x_user)
    r = packet.resolve(ref)
    for k in ("text", "excerpt"):
        if isinstance(r.get(k), str):
            r[k] = auth.mask_text(r[k])
    return r


@app.get("/api/compare")
def compare(a: str = "v2", b: str = "v3", x_user: str | None = Header(None)):
    staff_only(me(x_user))
    return views.compare(wp, a, b)


@app.get("/api/whatif")
def whatif(x_user: str | None = Header(None)):
    staff_only(me(x_user))
    s = wp.state()
    return {"alternatives": packet.what_if["alternatives"], "extension": packet.what_if["extension"],
            "decisions": {k: v for k, v in s.decisions.items()}}


@app.get("/api/variances")
def get_variances(x_user: str | None = Header(None)):
    staff_only(me(x_user))
    s = wp.state()
    return [{**v, "explanation": s.explanations.get(v["key"])} for v in variances(packet, s.standards.get("variance_review", {}))]


@app.get("/api/changes")
def changes(x_user: str | None = Header(None)):
    u = me(x_user)
    return wp.changes_since(u["id"])


@app.get("/api/history")
def history(target: str | None = None, limit: int = 300, x_user: str | None = Header(None)):
    staff_only(me(x_user))
    s = wp.state()
    evs = [e for e in s.events if not target or e["target"] == target or e["data"].get("line") == target or e["data"].get("finding") == target]
    return [wp.describe(e) for e in evs[-limit:]][::-1]


@app.get("/api/audit")
def audit(x_user: str | None = Header(None)):
    u = me(x_user)
    if not auth.can(u, "audit"):
        raise HTTPException(403, "Audit log: administrator, quality reviewer and partner")
    s = wp.state()
    return {"sensitive_views": [{**v, "name": wp.name(v["by"])} for v in s.sensitive_views][::-1], "chain": store.verify_chain(),
            "events": [wp.describe(e) for e in s.events][::-1][:500], "time": s.time, "standards": s.standards}


@app.get("/api/notes")
def notes(x_user: str | None = Header(None)):
    staff_only(me(x_user))
    s = wp.state()
    return {"notes": list(s.notes.values())[::-1], "questions": list(s.questions.values())[::-1]}


@app.get("/api/reports/{rid}")
def report(rid: str, x_user: str | None = Header(None)):
    staff_only(me(x_user))
    try:
        return reports.build(wp, rid)
    except KeyError:
        raise HTTPException(404) from None


@app.get("/api/search")
def search(q: str, x_user: str | None = Header(None)):
    u = me(x_user)
    staff_only(u)
    return views.search(wp, q, u)


@app.get("/api/client")
def client(x_user: str | None = Header(None)):
    u = me(x_user)
    return views.client_portal(wp, u["id"])


@app.get("/api/rollforward")
def rollforward(x_user: str | None = Header(None)):
    staff_only(me(x_user))
    return views.rollforward(wp)


@app.get("/api/export/notice/{nid}", response_class=HTMLResponse)
def export_notice(nid: str, x_user: str | None = None):
    me(x_user)
    return HTMLResponse(views.notice_packet(wp, nid), headers={"Content-Disposition": f'inline; filename="notice-{nid}.html"'})


@app.get("/api/export/client-copy", response_class=HTMLResponse)
def export_client_copy(x_user: str | None = None):
    me(x_user)
    return HTMLResponse(views.client_copy(wp))


@app.get("/api/export/log")
def export_log(x_user: str | None = None):
    u = me(x_user)
    staff_only(u)
    return Response(json.dumps(store.all(), indent=1), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="workpaper-events.json"'})


# ---------------------------------------------------------------------- writes
@app.post("/api/command")
async def command(request: Request, x_user: str | None = Header(None)):
    u = me(x_user)
    body = await request.json()
    if not isinstance(body, dict):
        raise commands.CommandError("command must be a JSON object")
    commands.parse(body, external=True)  # rejects internal command types before they reach the workpaper
    evs = wp.command(u["id"], body)
    return {"events": [wp.describe(e) for e in evs], "head": store.head()}


MAX_UPLOAD = 8 * 1024 * 1024
INLINE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain"}


def _safe_name(name: str) -> str:
    import re as _re
    base = _re.sub(r"[^A-Za-z0-9._ -]", "_", name.replace("\\", "/").split("/")[-1]).strip(" .") or "file"
    return base[:120]


@app.post("/api/upload")
async def upload(request: Request, x_user: str | None = Header(None)):
    u = me(x_user)
    body = await request.json()
    auth.require(u, "attach", wp.state().clock)
    b64 = body.get("content") or ""
    if len(b64) > MAX_UPLOAD * 4 // 3 + 4:
        raise HTTPException(413, "8 MB limit")
    try:
        content = base64.b64decode(b64, validate=True)
    except ValueError:
        raise HTTPException(400, "content must be base64") from None
    name = _safe_name(str(body.get("name") or "file"))
    mime = str(body.get("mime") or "application/octet-stream")[:100]
    meta = store.put_file(name, mime, content, u["id"])
    evs = wp.command(u["id"], {"type": "attach", "target": str(body.get("target") or "")[:200], "file": meta, "name": name,
                               "note": str(body.get("note") or "")[:500]})
    return {"file": meta, "events": [wp.describe(e) for e in evs]}


@app.get("/api/files/{fid}")
def get_file(fid: str, x_user: str | None = None):
    me(x_user)
    r = store.get_file(fid)
    if not r:
        raise HTTPException(404)
    from urllib.parse import quote
    inline = r["mime"] in INLINE_TYPES
    mime = r["mime"] if inline else "application/octet-stream"
    disp = f"{'inline' if inline else 'attachment'}; filename=\"{_safe_name(r['name'])}\"; filename*=UTF-8''{quote(r['name'])}"
    return Response(r["content"], media_type=mime, headers={"Content-Disposition": disp})


@app.post("/api/presence")
async def presence(request: Request, x_user: str | None = Header(None)):
    u = me(x_user)
    body = await request.json()
    PRESENCE[u["id"]] = {"user": u["id"], "name": u["name"], "where": body.get("where", ""), "t": time.time()}
    return {"ok": True}


@app.post("/api/reset")
def reset(x_user: str | None = Header(None)):
    u = me(x_user)
    if not auth.can(u, "reset") and os.environ.get("ALLOW_ANY_RESET") != "1":
        raise HTTPException(403, "Only the firm administrator can reset the demo")
    wp.reset()
    return {"ok": True, "head": store.head()}


@app.get("/api/stream")
async def stream(request: Request):
    """Server-sent events: the log head. Clients refetch what they show when it moves."""
    async def gen():
        last = -1
        while True:
            if await request.is_disconnected():
                break
            h = store.head()
            if h != last:
                last = h
                yield f"data: {json.dumps({'head': h})}\n\n"
            else:
                yield ": ping\n\n"
            await asyncio.sleep(1.0)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/health")
def health():
    return {"ok": True, "head": store.head(), "packet": packet.raw["packet"]["name"]}


# ---------------------------------------------------------------------- UI
STATIC = ROOT / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
