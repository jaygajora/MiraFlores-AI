"""Who can do what. Enforced on the server for every command; the UI only mirrors it."""
from __future__ import annotations

import re

from .packet import Packet

PERMS = {
    "preparer": {"adjust", "verify", "note", "dispose_finding", "dispose_document", "decide", "ask_client", "signoff:preparer",
                 "log_time", "attach", "undo", "fix_household", "resolve_note", "reply"},
    "reviewer": {"adjust", "verify", "note", "dispose_finding", "dispose_document", "decide", "ask_client", "signoff:reviewer",
                 "log_time", "attach", "undo", "approve:reviewer", "fix_household", "resolve_note", "reply", "blocking_note"},
    "partner": {"adjust", "verify", "note", "dispose_finding", "dispose_document", "decide", "ask_client", "signoff:partner",
                "log_time", "attach", "undo", "approve:reviewer", "approve:partner", "send_to_client", "transmit", "amend",
                "fix_household", "resolve_note", "reply", "blocking_note", "respond_notice", "deliver", "advance_clock", "audit"},
    "firm_administrator": {"standards", "assign", "audit", "attach", "note", "reply", "log_time", "reset", "advance_clock"},
    "quality_reviewer": {"note", "reply", "audit", "blocking_note", "resolve_note"},
    "client": {"answer", "client_approve", "attach", "reply", "message"},
}

ROLE_TITLES = {"preparer": "Preparer", "reviewer": "Reviewer", "partner": "Partner", "firm_administrator": "Firm administrator",
               "quality_reviewer": "Quality reviewer", "client": "Client"}


def users(p: Packet) -> list[dict]:
    out = []
    for s in p.firm["staff"]:
        out.append({"id": s["id"], "name": s["name"], "role": s["role"], "role_title": ROLE_TITLES[s["role"]],
                    "credential": s.get("credential"), "clearance": s["sensitive_data_clearance"],
                    "active_from": s["active_from"], "note": s.get("note")})
    for c in p.firm["client_users"]:
        out.append({"id": c["id"], "name": c["name"], "role": "client", "role_title": "Client", "credential": None,
                    "clearance": False, "active_from": "2026-01-01", "note": None})
    return out


def user(p: Packet, uid: str) -> dict | None:
    return next((u for u in users(p) if u["id"] == uid), None)


def can(u: dict, perm: str) -> bool:
    return perm in PERMS.get(u["role"], set())


class Denied(Exception):
    pass


def require(u: dict | None, perm: str, clock: str) -> None:
    if u is None:
        raise Denied("Unknown user")
    if u["active_from"] > clock[:10]:
        raise Denied(f"{u['name']} is not on staff until {u['active_from']}")
    if not can(u, perm):
        raise Denied(f"{u['role_title']}s cannot {perm.replace(':', ' as ').replace('_', ' ')}")


# ---------------------------------------------------------------------- masking
SSN_RE = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
IBAN_RE = re.compile(r"\bSE\d{2}(?: \d{4}){5}\b")
PIN_RE = re.compile(r"(PIN(?: for [^.]*?)? (?:is )?)(\d{5,6})")
LONGNUM_RE = re.compile(r"\b(\d{5})(\d{4,})\b")


def mask_text(t: str) -> str:
    if not t:
        return t
    t = SSN_RE.sub(lambda m: f"•••-••-{m.group(3)}", t)
    t = IBAN_RE.sub(lambda m: "SE•• •••• •••• •••• •••• " + m.group(0)[-4:], t)
    t = PIN_RE.sub(lambda m: m.group(1) + "•" * len(m.group(2)), t)
    return t


def mask_value(value, value_type: str):
    if value_type in ("ssn",) and isinstance(value, str):
        return mask_text(value)
    if value_type in ("account_number",) and isinstance(value, str):
        return "•" * max(0, len(value) - 4) + value[-4:]
    return value


SENSITIVE_HOUSEHOLD = ("ssn", "ip_pin")
