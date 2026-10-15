"""The workpaper: commands in, events out, state as a projection of the log.

Commands are validated against roles and firm standards, then appended to the
event store. Reads fold the log into a State (cached by log head), then derive
everything else (effective values, findings status, sign-off validity, open
items) from State + the read-only packet.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import auth, commands
from .checks import run_checks, ssn_mismatches, variances
from .domain import AREA_TITLES, AREAS, area_for_line, category_for_line, effect_of, profit_sign
from .packet import Packet
from .store import EventStore

INITIAL_CLOCK = "2026-06-24T09:00:00Z"
SYSTEM = "system"


def H(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


@dataclass
class State:
    seq: int = 0
    clock: str = INITIAL_CLOCK
    adjustments: dict = field(default_factory=dict)
    verifications: dict = field(default_factory=dict)     # target -> list
    notes: dict = field(default_factory=dict)
    questions: dict = field(default_factory=dict)          # client questions
    finding_disp: dict = field(default_factory=dict)
    doc_disp: dict = field(default_factory=dict)
    decisions: dict = field(default_factory=dict)
    signoffs: dict = field(default_factory=dict)           # area -> level -> record
    steps: dict = field(default_factory=dict)              # manual step completions
    assignments: dict = field(default_factory=dict)
    team: list = field(default_factory=list)
    time: list = field(default_factory=list)
    filing: dict = field(default_factory=dict)
    household_fixes: dict = field(default_factory=dict)
    attachments: list = field(default_factory=list)
    standards: dict = field(default_factory=dict)
    seen: dict = field(default_factory=dict)
    sensitive_views: list = field(default_factory=list)
    explanations: dict = field(default_factory=dict)       # variance key -> record
    timeline_done: set = field(default_factory=set)
    undone: set = field(default_factory=set)
    events: list = field(default_factory=list)
    notices: dict = field(default_factory=dict)
    amendments: list = field(default_factory=list)


STEP_DOC_TYPES = {
    "engagement": ("engagement_letter", "consent_7216"),
    "identity": ("identity_document", "irs_ip_pin_notice"),
    "prior_year": ("prior_year_return", "prior_workpaper"),
}


class Workpaper:
    def __init__(self, packet: Packet, store: EventStore):
        self.p = packet
        self.store = store
        self._cache: tuple[int, State] | None = None
        self._derived: dict[tuple[int, str], Any] = {}
        if store.head() == 0:
            self.bootstrap()

    # ================================================================== bootstrap
    def bootstrap(self) -> None:
        p = self.p
        std = p.firm["starter_standards"]
        opened = min(d["received_at"] for d in p.raw["documents"])
        self.store.append(actor=SYSTEM, kind="workpaper.opened", sim_at=opened, target=p.raw["packet"]["client_id"],
                          data={"packet": p.raw["packet"], "standards": {
                              "verification_types": std["verification_types"], "variance_review": std["variance_review"],
                              "review_levels": std["review_levels"], "rules": std["rules"], "required_steps": std["required_steps"],
                              "partner_signoff_over": 1000, "retention_years": 7}})
        self.store.append(actor=SYSTEM, kind="assignment.set", sim_at=opened, target="engagement",
                          data={"assignments": p.firm["assignment_at_start"]})
        self._replay_timeline(None, INITIAL_CLOCK)
        self.store.append(actor=SYSTEM, kind="clock.set", sim_at=INITIAL_CLOCK, data={"to": INITIAL_CLOCK,
                          "note": "Workpaper opened the morning after v3 was computed; later timeline events replay forward."})

    def reset(self) -> None:
        self.store.reset()
        self._cache = None
        self._derived.clear()
        self.bootstrap()

    def _replay_timeline(self, frm: str | None, to: str) -> list[dict]:
        out = []
        for t in self.p.timeline:
            if (frm is None or t["at"] > frm) and t["at"] <= to:
                out.append(self.store.append(actor=t["actor"] or SYSTEM, kind=f"timeline.{t['event']}", sim_at=t["at"], target=t["id"],
                                             data={"item": t}))
                out += self._timeline_side_effects(t)
        return out

    def _timeline_side_effects(self, t: dict) -> list[dict]:
        """Scripted season events that change workpaper state."""
        ev = []
        e = t["event"]
        if e == "extension_filed_with_payment":
            ev.append(self.store.append(actor=t["actor"] or SYSTEM, kind="filing.extension_filed", sim_at=t["at"], target="F4868",
                                        data={"federal_paid": 36000, "california_paid": 0, "based_on": "v2", "detail": t["detail"]}))
        elif e == "staff_joined_engagement":
            ev.append(self.store.append(actor=SYSTEM, kind="assignment.joined", sim_at=t["at"], target="st-04",
                                        data={"staff": "st-04", "role": "preparer"}))
        elif e == "client_approved_and_signed_8879":
            st = self.state()
            sent = st.filing.get("sent")
            fp = self.return_fingerprint(st)
            ev.append(self.store.append(actor="cu-01", kind="filing.client_approved", sim_at=t["at"], target="F8879",
                                        data={"fingerprint": sent["fingerprint"] if sent else fp, "via": "timeline",
                                              "presented": bool(sent), "pins": "taxpayer and spouse PINs on file (masked)"}))
        elif e in ("efile_rejected", "efile_accepted_federal", "efile_accepted_california"):
            ev += self._agency_response(t)
        elif e == "quality_review_selected_return":
            ev.append(self.store.append(actor=SYSTEM, kind="assignment.joined", sim_at=t["at"], target="st-06",
                                        data={"staff": "st-06", "role": "quality_reviewer"}))
        elif e == "notice_received":
            n = self.p.agency["notices"][1]
            ev.append(self.store.append(actor=SYSTEM, kind="notice.received", sim_at=t["at"], target=n["id"], data={"notice": n}))
        elif e == "federal_balance_paid":
            ev.append(self.store.append(actor=SYSTEM, kind="filing.payment", sim_at=t["at"], target="federal",
                                        data={"jurisdiction": "federal", "detail": t["detail"]}))
        elif e == "california_refund_issued":
            ev.append(self.store.append(actor=SYSTEM, kind="filing.refund", sim_at=t["at"], target="california",
                                        data={"jurisdiction": "california", "detail": t["detail"]}))
        return ev

    def _agency_response(self, t: dict) -> list[dict]:
        """Scripted e-file acknowledgments, applied to the firm's actual submission."""
        st = self.state()
        sub = st.filing.get("submission")
        if not sub or sub.get("result") in ("accepted",):
            return [self.store.append(actor=SYSTEM, kind="filing.ack_pending", sim_at=t["at"], target=t["id"],
                                      data={"note": "Agency acknowledgment arrived in the script, but nothing was transmitted yet; it will apply on transmit."})]
        return self._acknowledge(sub, t["at"])

    def _acknowledge(self, sub: dict, at: str) -> list[dict]:
        st = self.state()
        # The agency matches every TIN against its records: simulate that with the SSN rule over all documents.
        bad = [pid for pid, mism, _ in ssn_mismatches(self.p, set(self.p.docs), st.household_fixes) if mism]
        out = []
        if sub["jurisdiction_state"].get("federal") == "transmitted":
            if bad:
                rec = self.p.agency["efile"][0]
                out.append(self.store.append(actor=SYSTEM, kind="filing.rejected", sim_at=at, target=sub["id"],
                                             data={"jurisdiction": "federal", "errors": rec["errors"], "agency_submission": rec["submission_id"]}))
                out.append(self.store.append(actor=SYSTEM, kind="filing.rejected", sim_at=at, target=sub["id"],
                                             data={"jurisdiction": "california", "errors": self.p.agency["efile"][1]["errors"],
                                                   "agency_submission": self.p.agency["efile"][1]["submission_id"]}))
                return out
            out.append(self.store.append(actor=SYSTEM, kind="filing.accepted", sim_at=at, target=sub["id"],
                                         data={"jurisdiction": "federal", "agency_submission": self.p.agency["efile"][2]["submission_id"]}))
            out.append(self.store.append(actor=SYSTEM, kind="filing.accepted", sim_at=at, target=sub["id"],
                                         data={"jurisdiction": "california", "agency_submission": self.p.agency["efile"][3]["submission_id"]}))
            st2 = self.state()
            out.append(self.store.append(actor=SYSTEM, kind="filing.sealed", sim_at=at, target=sub["id"], data={
                "fingerprint": self.return_fingerprint(st2), "log_head": self.store.verify_chain().get("head"),
                "summary": self.summary(st2)["workpaper"], "seq": self.store.head()}))
        return out

    # ================================================================== projection
    def state(self) -> State:
        head = self.store.head()
        if self._cache and self._cache[0] == head:
            return self._cache[1]
        events = self.store.all()
        s = State()
        undone = set()
        for e in events:
            if e["kind"] == "action.undone":
                undone |= set(e["data"]["events"])
        s.undone = undone
        for e in events:
            s.seq = e["seq"]
            s.events.append(e)
            if e["id"] in undone:
                continue
            self._apply(s, e)
        self._cache = (head, s)
        return s

    def _apply(self, s: State, e: dict) -> None:
        k, d, t = e["kind"], e["data"], e["target"]
        if k == "workpaper.opened":
            s.standards = copy.deepcopy(d["standards"])
        elif k in ("clock.set", "clock.advanced"):
            s.clock = d["to"]
        elif k == "standards.changed":
            cur = s.standards
            parts = d["path"].split(".")
            for part in parts[:-1]:
                cur = cur.setdefault(part, {})
            cur[parts[-1]] = d["value"]
        elif k == "assignment.set":
            s.assignments.update(d["assignments"])
            for _r, sid in d["assignments"].items():
                if sid not in s.team:
                    s.team.append(sid)
        elif k == "assignment.joined":
            if d["staff"] not in s.team:
                s.team.append(d["staff"])
        elif k == "adjustment.recorded":
            s.adjustments[e["id"]] = {**d, "id": e["id"], "by": e["actor"], "at": e["sim_at"], "status": "recorded",
                                      "approvals": [], "batch": e["batch"], "amendment": s.filing.get("amendment_open")}
        elif k == "adjustment.reverted":
            a = s.adjustments.get(d["adjustment"])
            if a:
                a["status"] = "reverted"
                a["reverted_by"], a["revert_reason"] = e["actor"], d.get("reason")
        elif k == "adjustment.approved":
            a = s.adjustments.get(d["adjustment"])
            if a:
                a["approvals"].append({"by": e["actor"], "level": d["level"], "at": e["sim_at"]})
        elif k == "verification.recorded":
            s.verifications.setdefault(t, []).append({**d, "id": e["id"], "by": e["actor"], "at": e["sim_at"], "batch": e["batch"]})
        elif k == "note.opened":
            s.notes[e["id"]] = {**d, "id": e["id"], "target": t, "by": e["actor"], "at": e["sim_at"], "status": "open",
                                "thread": [{"by": e["actor"], "at": e["sim_at"], "text": d["text"]}]}
        elif k == "note.replied":
            n = s.notes.get(d["note"]) or s.questions.get(d["note"])
            if n:
                n["thread"].append({"by": e["actor"], "at": e["sim_at"], "text": d["text"], "attachments": d.get("attachments", [])})
        elif k == "note.resolved":
            n = s.notes.get(d["note"])
            if n:
                n["status"], n["resolved_by"], n["resolved_at"] = "resolved", e["actor"], e["sim_at"]
        elif k == "note.reopened":
            n = s.notes.get(d["note"])
            if n:
                n["status"] = "open"
        elif k == "question.asked":
            s.questions[e["id"]] = {**d, "id": e["id"], "target": t, "by": e["actor"], "at": e["sim_at"], "status": "open",
                                    "thread": [{"by": e["actor"], "at": e["sim_at"], "text": d["text"]}]}
        elif k == "question.answered":
            q = s.questions.get(d["question"])
            if q:
                q["thread"].append({"by": e["actor"], "at": e["sim_at"], "text": d["text"], "attachments": d.get("attachments", [])})
                q["status"], q["answer"], q["answered_by"], q["answered_at"] = "answered", d["text"], e["actor"], e["sim_at"]
        elif k == "question.reviewed":
            q = s.questions.get(d["question"])
            if q:
                q["reviewed"] = True
                q["thread"].append({"by": e["actor"], "at": e["sim_at"], "text": d.get("text", "Answer reviewed.")})
        elif k == "finding.dispositioned":
            s.finding_disp[t] = {**d, "id": e["id"], "by": e["actor"], "at": e["sim_at"]}
        elif k == "document.dispositioned":
            s.doc_disp[t] = {**d, "id": e["id"], "by": e["actor"], "at": e["sim_at"]}
        elif k == "decision.recorded":
            s.decisions[t] = {**d, "id": e["id"], "by": e["actor"], "at": e["sim_at"]}
        elif k == "variance.explained":
            s.explanations[t] = {**d, "id": e["id"], "by": e["actor"], "at": e["sim_at"]}
        elif k == "signoff.recorded":
            s.signoffs.setdefault(t, {})[d["level"]] = {**d, "id": e["id"], "by": e["actor"], "at": e["sim_at"]}
        elif k == "signoff.withdrawn":
            s.signoffs.get(t, {}).pop(d["level"], None)
        elif k == "step.completed":
            s.steps[t] = {**d, "id": e["id"], "by": e["actor"], "at": e["sim_at"]}
        elif k == "time.logged":
            s.time.append({**d, "id": e["id"], "by": e["actor"], "at": e["sim_at"]})
        elif k == "household.corrected":
            s.household_fixes.setdefault(t, {})[d["field"]] = d["value"]
        elif k == "file.attached":
            s.attachments.append({**d, "id": e["id"], "target": t, "by": e["actor"], "at": e["sim_at"]})
        elif k == "user.seen":
            s.seen[e["actor"]] = d["seq"]
        elif k == "sensitive.viewed":
            s.sensitive_views.append({**d, "target": t, "by": e["actor"], "at": e["at"], "sim_at": e["sim_at"]})
        elif k.startswith("timeline."):
            s.timeline_done.add(t)
        elif k == "filing.extension_filed":
            s.filing["extension"] = {**d, "at": e["sim_at"]}
        elif k == "filing.sent_to_client":
            s.filing["sent"] = {**d, "at": e["sim_at"], "by": e["actor"]}
            s.filing.pop("client_approval", None)
        elif k == "filing.client_approved":
            s.filing["client_approval"] = {**d, "at": e["sim_at"], "by": e["actor"]}
        elif k == "filing.transmitted":
            s.filing["submission"] = {**d, "id": e["id"], "at": e["sim_at"], "by": e["actor"],
                                      "jurisdiction_state": {"federal": "transmitted", "california": "transmitted"}, "result": "pending"}
            s.filing.setdefault("history", []).append({"kind": "transmitted", "at": e["sim_at"], "by": e["actor"]})
        elif k == "filing.rejected":
            sub = s.filing.get("submission")
            if sub:
                sub["jurisdiction_state"][d["jurisdiction"]] = "rejected"
                sub["result"] = "rejected"
                sub.setdefault("errors", []).extend(d["errors"])
            s.filing.setdefault("history", []).append({"kind": f"rejected ({d['jurisdiction']})", "at": e["sim_at"], "errors": d["errors"]})
            s.filing["last_rejection"] = {"at": e["sim_at"], "errors": d["errors"]} if d["jurisdiction"] == "federal" else s.filing.get("last_rejection")
        elif k == "filing.accepted":
            sub = s.filing.get("submission")
            if sub:
                sub["jurisdiction_state"][d["jurisdiction"]] = "accepted"
                if all(v == "accepted" for v in sub["jurisdiction_state"].values()):
                    sub["result"] = "accepted"
            s.filing.setdefault("history", []).append({"kind": f"accepted ({d['jurisdiction']})", "at": e["sim_at"],
                                                       "agency_submission": d.get("agency_submission")})
        elif k == "filing.sealed":
            s.filing["sealed"] = {**d, "at": e["sim_at"], "event": e["id"]}
        elif k == "filing.delivered":
            s.filing["delivered"] = {**d, "at": e["sim_at"], "by": e["actor"]}
        elif k == "filing.payment":
            s.filing.setdefault("post_filing", []).append({**d, "at": e["sim_at"], "kind": "payment"})
        elif k == "filing.refund":
            s.filing.setdefault("post_filing", []).append({**d, "at": e["sim_at"], "kind": "refund"})
        elif k == "amendment.started":
            s.filing["amendment_open"] = e["id"]
            s.amendments.append({**d, "id": e["id"], "at": e["sim_at"], "by": e["actor"]})
        elif k == "notice.received":
            s.notices[t] = {**d["notice"], "received_at": e["sim_at"], "responses": []}
        elif k == "notice.responded" and t in s.notices:
            s.notices[t]["responses"].append({**d, "at": e["sim_at"], "by": e["actor"]})

    # ================================================================== derived (cached per head)
    def _memo(self, name, fn):
        key = (self.store.head(), name)
        if key not in self._derived:
            if len(self._derived) > 200:
                self._derived.clear()
            self._derived[key] = fn()
        return self._derived[key]

    def visible_docs(self, s: State | None = None) -> set[str]:
        s = s or self.state()
        return {d["id"] for d in self.p.raw["documents"] if d["received_at"] <= s.clock}

    def visible_messages(self, s: State | None = None) -> list[dict]:
        s = s or self.state()
        return [m for m in self.p.raw["client"]["messages"] if m["sent_at"] <= s.clock]

    def checks(self) -> dict:
        def run():
            s = self.state()
            return run_checks(self.p, self.visible_docs(s), s.clock, s.household_fixes)
        return self._memo("checks", run)

    def active_adjustments(self, s: State | None = None) -> list[dict]:
        s = s or self.state()
        return [a for a in s.adjustments.values() if a["status"] != "reverted"]

    def effective(self) -> dict:
        """Line values after adjustments, propagated exactly through sums and carries.

        Propagation stops at lines computed by engine logic (tax tables, limits,
        phase-outs); those are flagged 'needs engine recompute' and their tax
        consequence is carried by the adjustment's rate-based effect instead.
        """
        def run():
            s = self.state()
            ver = self.p.current
            delta: dict[str, float] = {}
            direct: dict[str, list[str]] = {}
            stale: dict[str, list[str]] = {}
            added: dict[str, dict] = {}
            for a in self.active_adjustments(s):
                key = a["line"]
                if key not in ver.lines:
                    added[key] = {"key": key, "label": a.get("label") or a.get("note") or key, "value": 0, "added_by": a["id"]}
                direct.setdefault(key, []).append(a["id"])
                frontier = [(key, a["delta"])]
                seen = set()
                while frontier:
                    k, dlt = frontier.pop()
                    if (k, dlt) in seen:
                        continue
                    seen.add((k, dlt))
                    delta[k] = delta.get(k, 0) + dlt
                    consumers = list(ver.consumers.get(k, []))
                    if k not in ver.lines:
                        m = re.match(r"(F8949\.[A-Z])\.", k)
                        if m:
                            consumers.append(f"{m.group(1)}.total")
                    if k.endswith(".E") and k.startswith("SchCA540NR.") and k != "SchCA540NR.22.E":
                        consumers.append("SchCA540NR.22.E")
                    for c in dict.fromkeys(consumers):
                        sg = ver.signs.get(c, {}).get(k)
                        if sg is None and c.endswith(".total") and c.startswith("F8949"):
                            sg = 1
                        if sg is None and c == "SchCA540NR.22.E":
                            sg = 1
                        if sg is None:
                            stale.setdefault(c, []).append(a["id"])
                        else:
                            frontier.append((c, dlt * sg))
            return {"delta": delta, "direct": direct, "stale": stale, "added": added}
        return self._memo("effective", run)

    def value_of(self, key: str) -> Any:
        line = self.p.current.lines.get(key)
        base = line["value"] if line else 0
        d = self.effective()["delta"].get(key)
        if d is None or not isinstance(base, (int, float)):
            return base
        return round(base + d, 2)

    def summary(self, s: State | None = None) -> dict:
        s = s or self.state()
        base = self.p.current.raw["summary"]
        fed = dict(base["federal"])
        ca = dict(base["california"])
        tot = {"fed_tax": 0, "ca_tax": 0, "fed_payments": 0, "ca_payments": 0}
        for a in self.active_adjustments(s):
            for k in tot:
                tot[k] += a["effect"].get(k, 0)
        wf = dict(fed)
        wf["total_tax"] = fed["total_tax"] + tot["fed_tax"]
        wf["payments"] = fed["payments"] + tot["fed_payments"]
        wf["balance_due"] = wf["total_tax"] - wf["payments"]
        wc = dict(ca)
        wc["total_tax"] = ca["total_tax"] + tot["ca_tax"]
        wc["payments"] = ca["payments"] + tot["ca_payments"]
        wc["balance_due"] = wc["total_tax"] - wc["payments"]
        eff = self.effective()["delta"]
        for k, line in (("agi", "F1040.11"), ("taxable_income", "F1040.15")):
            if line in eff:
                wf[k] = round(fed[k] + eff[line])
        if "F540NR.32" in eff:
            wc["ca_agi"] = round(ca["ca_agi"] + eff["F540NR.32"])
        if "F540NR.17" in eff:
            wc["total_agi"] = round(ca["total_agi"] + eff["F540NR.17"])
        return {"engine": {"federal": fed, "california": ca, "version": "v3"},
                "workpaper": {"federal": wf, "california": wc}, "effects": tot,
                "prior_year": {"federal": {"agi": self.p.prior_line("F1040.11"), "taxable_income": self.p.prior_line("F1040.15"),
                                           "total_tax": self.p.prior_line("F1040.24"), "payments": self.p.prior_line("F1040.33")},
                               "california": {"ca_agi": self.p.prior_line("CA540.17"), "total_tax": self.p.prior_line("CA540.64")}},
                "basis": "Engine v3 plus the rate-based tax effect of each recorded adjustment (README: multiply the change by tax_effect_rates)."}

    def return_fingerprint(self, s: State | None = None) -> str:
        s = s or self.state()
        eff = self.effective()
        return H({"delta": {k: round(v, 2) for k, v in sorted(eff["delta"].items())}, "household": s.household_fixes,
                  "adjustments": sorted(a["id"] for a in self.active_adjustments(s))})

    # ------------------------------------------------------------------ findings with status
    def findings(self) -> list[dict]:
        def run():
            s = self.state()
            out = []
            for f in self.checks()["findings"]:
                f = dict(f)
                disp = s.finding_disp.get(f["id"])
                f["status"] = "open"
                if disp:
                    f["status"] = disp["disposition"]
                    f["disposition"] = disp
                    if disp["disposition"] == "waiting_client":
                        q = s.questions.get(disp.get("question"))
                        if q and q["status"] == "answered":
                            f["status"] = "client_answered"
                            f["client_answer"] = q.get("answer")
                f["adjustments"] = [a["id"] for a in self.active_adjustments(s) if a.get("finding") == f["id"]]
                f["notes"] = [n["id"] for n in s.notes.values() if n["target"] == f["id"]]
                out.append(f)
            return out
        return self._memo("findings", run)

    def finding(self, fid: str) -> dict | None:
        return next((f for f in self.findings() if f["id"] == fid), None)

    # ------------------------------------------------------------------ verification
    def line_verification(self, key: str, s: State | None = None) -> dict:
        s = s or self.state()
        recs = s.verifications.get(key, [])
        cur = self.value_of(key)
        valid = [r for r in recs if r.get("value") == cur or r.get("value") is None]
        stale = [r for r in recs if r not in valid]
        machine = [x for x in self.checks()["passes"] if key in x["lines"]]
        status = "verified" if valid else "recalculated" if machine else "stale" if stale else "unverified"
        return {"status": status, "records": recs, "valid": valid, "stale": stale, "machine": machine}

    # ------------------------------------------------------------------ areas and sign-offs
    def area_lines(self, area: str) -> list[str]:
        return [k for k, ln in self.p.current.lines.items() if area_for_line(k, ln["form"]) == area]

    def area_fingerprint(self, area: str, s: State | None = None) -> str:
        s = s or self.state()
        if area == "partner_review":
            return self.return_fingerprint(s)
        eff = self.effective()["delta"]
        keys = set(self.area_lines(area))
        fids = [f["id"] for f in self.findings() if f["area"] == area]
        return H({"lines": {k: eff[k] for k in sorted(keys) if k in eff},
                  "adjustments": sorted(a["id"] for a in self.active_adjustments(s) if area_for_line(a["line"], a["line"].split(".")[0]) == area),
                  "findings": {f: s.finding_disp.get(f, {}).get("disposition") for f in sorted(fids)},
                  "docs": {d: s.doc_disp.get(d, {}).get("status") for d in sorted(s.doc_disp) if self.doc_area(d) == area}})

    def area_status(self) -> list[dict]:
        def run():
            s = self.state()
            out = []
            budget = self.p.firm["budget_hours"]
            for area, title in AREAS:
                fp = self.area_fingerprint(area, s)
                so = {}
                for lvl, rec in s.signoffs.get(area, {}).items():
                    so[lvl] = {**rec, "valid": rec["fingerprint"] == fp}
                fs = [f for f in self.findings() if f["area"] == area]
                out.append({"area": area, "title": title, "signoffs": so,
                            "open_findings": sum(1 for f in fs if f["status"] in ("open", "client_answered")),
                            "findings": len(fs),
                            "open_notes": sum(1 for n in s.notes.values() if n["status"] == "open" and self.target_area(n["target"]) == area),
                            "adjustments": sum(1 for a in self.active_adjustments(s) if area_for_line(a["line"], a["line"].split(".")[0]) == area),
                            "hours": round(sum(t["hours"] for t in s.time if t["area"] == area), 2),
                            "budget": budget.get(area),
                            "lines": len(self.area_lines(area)),
                            "docs": sum(1 for d in self.visible_docs(s) if self.doc_area(d) == area)})
            return out
        return self._memo("areas", run)

    def doc_area(self, did: str) -> str:
        """Where a document's values land; for a document the engine ignored, the area of the findings that cite it."""
        def run():
            out = dict(self.p.doc_areas)
            for d in self.p.raw["documents"]:
                if any(self.p.current.landings.get(e) for e in self.p.values_by_doc.get(d["id"], [])):
                    continue
                cited = [f["area"] for f in self.checks()["findings"] if f["source"] == "check" and f["area"]
                         and any(self.p.doc_for_ref(r) == d["id"] for r in f["evidence"])]
                if cited:
                    out[d["id"]] = max(set(cited), key=cited.count)
            return out
        return self._memo("doc_areas", run)[did]

    def target_area(self, target: str) -> str:
        if target in self.p.current.lines:
            return area_for_line(target, self.p.current.lines[target]["form"])
        d = self.p.doc_for_ref(target)
        if d:
            return self.doc_area(d)
        f = next((f for f in self.checks()["findings"] if f["id"] == target), None)
        if f:
            return f["area"]
        if target in AREA_TITLES:
            return target
        return "intake_and_engagement"

    # ------------------------------------------------------------------ documents accounted for
    def document_index(self) -> list[dict]:
        def run():
            s = self.state()
            vis = self.visible_docs(s)
            out = []
            for d in self.p.raw["documents"]:
                if d["id"] not in vis:
                    continue
                vals = self.p.values_by_doc.get(d["id"], [])
                land = [self.p.landing_for_value(v) for v in vals]
                used = sum(1 for x in land if x["status"] == "used")
                lines = sorted({ln for x in land for ln in x.get("lines", [])})
                engine_status = "used" if used else (
                    "superseded" if d["id"] in self.p.current.raw["documents_superseded"] else
                    "duplicate" if d["id"] in self.p.duplicate_notes else
                    "reference" if d["extraction"]["status"] == "not_extracted" else
                    "not_used" if d["id"] not in self.p.current.raw["documents_used"] else "context")
                disp = s.doc_disp.get(d["id"])
                fs = [f["id"] for f in self.findings() if any(self.p.doc_for_ref(r) == d["id"] for r in f["evidence"])]
                auto = None
                if not disp and engine_status not in ("used", "superseded", "duplicate"):
                    closed = [f for f in self.findings() if f["id"] in fs and f["status"] not in ("open", "client_answered")]
                    step = next((k for k, types in STEP_DOC_TYPES.items() if d["document_type"] in types), None)
                    if step and (step == "engagement" or step in s.steps):
                        auto = "Evidence for a completed required step"
                    elif any(any(self.p.doc_for_ref(r) == d["id"] for r in x["evidence"]) for x in self.checks()["passes"]):
                        auto = "Evidence for an independent check that passed"
                    elif closed:
                        auto = f"Evidence for finding {closed[0]['id']} ({closed[0]['status']})"
                accounted = bool(disp) or bool(auto) or engine_status in ("used", "superseded", "duplicate")
                out.append({"id": d["id"], "title": d["title"], "type": d["document_type"], "issuer": d["issuer"],
                            "belongs_to": d["belongs_to"], "received_at": d["received_at"], "pages": d["page_count"],
                            "extraction": d["extraction"], "values": len(vals), "values_used": used, "lines": lines[:40],
                            "line_count": len(lines), "engine_status": engine_status, "disposition": disp,
                            "accounted": accounted, "auto_accounted": auto, "area": self.doc_area(d["id"]), "findings": fs,
                            "low_confidence": sum(1 for v in vals if self.p.values[v]["confidence"] < 0.9)})
            return out
        return self._memo("docindex", run)

    # ------------------------------------------------------------------ steps
    def required_steps(self) -> list[dict]:
        def run():
            s = self.state()
            fs = self.findings()
            areas = self.area_status()
            docs = self.document_index()
            var = variances(self.p, s.standards.get("variance_review", {}))
            passes = {x["id"] for x in self.checks()["passes"]}
            vis = self.visible_docs(s)
            approval_needed = self.approvals_needed(s)
            out = []
            for i, step in enumerate(s.standards.get("required_steps", [])):
                auto, done, why, ev = None, False, "", []
                low = step.lower()
                if low.startswith("engagement letter"):
                    ds = self._step_docs("engagement", vis)
                    done = len({d["document_type"] for d in ds}) == len(STEP_DOC_TYPES["engagement"])
                    why, ev, auto = f"Signed engagement letter and 7216 consent on file ({', '.join(d['id'] for d in ds) or 'missing'}).", [f"{d['id']}#page1" for d in ds], True
                elif low.startswith("identity"):
                    ds = self._step_docs("identity", vis)
                    done = bool(ds) and "identity" in s.steps
                    why, ev, auto = f"Identity documents and IP PIN notice ({', '.join(d['id'] for d in ds)}); a preparer confirms.", [f"{d['id']}#page1" for d in ds], False
                elif low.startswith("prior-year return"):
                    ds = self._step_docs("prior_year", vis)
                    done = "prior_year" in s.steps
                    why, ev, auto = f"Prior-year return and prior preparer file ({', '.join(d['id'] for d in ds)}) reviewed by a preparer.", [f"{d['id']}#page1" for d in ds], False
                elif low.startswith("all documents"):
                    left = [d["id"] for d in docs if not d["accounted"]]
                    done = not left
                    why, auto = ("Every document is used, superseded, duplicate or dispositioned." if done else
                                 f"{len(left)} document(s) not yet accounted for: {', '.join(left[:8])}{'...' if len(left) > 8 else ''}"), True
                elif low.startswith("prior-year variances"):
                    left = [v["key"] for v in var if v["key"] not in s.explanations]
                    done = not left
                    why, auto = (f"All {len(var)} variances explained." if done else f"{len(left)} of {len(var)} variances unexplained."), True
                elif low.startswith("carryovers"):
                    done = {"P-CARRY", "P-PAL"} <= passes
                    pv = [x for x in self.checks()["passes"] if x["id"] in ("P-CARRY", "P-PAL")]
                    why, auto, ev = "Capital loss and passive loss carryovers recalculated against the prior-year return.", True, [r for x in pv for r in x["evidence"]]
                elif low.startswith("estimated payments"):
                    open_ = [f["id"] for f in fs if f["id"] in ("F-EST-FED", "F-EST-CA") and f["status"] in ("open", "client_answered")]
                    done = not open_
                    why, auto = ("Payments agree to IRS transcript and FTB account (or differences adjusted)." if done else
                                 "Payment differences with IRS/FTB still open."), True
                elif low.startswith("due diligence"):
                    done = "due_diligence" in s.decisions
                    why, auto = "Form 8867 checklist for CTC/ODC completed by the preparer.", False
                elif low.startswith("diagnostics"):
                    open_ = [f for f in fs if f["status"] in ("open", "client_answered") and f["severity"] != "info"]
                    done = not open_
                    why, auto = (f"All {len(fs)} findings dispositioned." if done else f"{len(open_)} findings open (errors and warnings)."), True
                elif low.startswith("reviewer sign-off"):
                    left = [a["title"] for a in areas if a["area"] != "partner_review" and not a["signoffs"].get("reviewer", {}).get("valid")]
                    done = not left and not [a for a in approval_needed if a["level"] == "reviewer"]
                    why, auto = ("Every area signed by the reviewer and still valid." if done else
                                 f"Reviewer sign-off missing or reopened: {', '.join(left[:4])}{'...' if len(left) > 4 else ''}"), True
                elif low.startswith("partner sign-off"):
                    pr = next(a for a in areas if a["area"] == "partner_review")
                    big = [a for a in approval_needed if a["level"] == "partner"]
                    done = bool(pr["signoffs"].get("partner", {}).get("valid")) and not big
                    why, auto = ("Partner signed the whole return and approved large adjustments." if done else
                                 f"Partner sign-off {'reopened' if pr['signoffs'].get('partner') else 'missing'}; {len(big)} adjustment(s) await partner approval."), True
                elif low.startswith("client approval"):
                    ca = s.filing.get("client_approval")
                    done = bool(ca and ca["fingerprint"] == self.return_fingerprint(s))
                    why, auto = ("Client approved the return as it stands and signed Forms 8879." if done else
                                 "Client approved an earlier version; numbers changed since." if ca else "Not yet sent to / approved by the client."), True
                out.append({"n": i + 1, "step": step, "done": done, "auto": auto, "why": why, "evidence": ev,
                            "manual": s.steps.get(self._step_key(step))})
            return out
        return self._memo("steps", run)

    def _step_docs(self, step: str, visible: set[str]) -> list[dict]:
        return [d for d in self.p.raw["documents"] if d["document_type"] in STEP_DOC_TYPES[step] and d["id"] in visible]

    @staticmethod
    def _step_key(step: str) -> str:
        low = step.lower()
        return "identity" if low.startswith("identity") else "prior_year" if low.startswith("prior-year return") else low[:20]

    def approvals_needed(self, s: State | None = None) -> list[dict]:
        s = s or self.state()
        thr = s.standards.get("partner_signoff_over", 1000)
        out = []
        for a in self.active_adjustments(s):
            eff = a["effect"]
            size = max(abs(eff.get("fed_tax", 0)), abs(eff.get("ca_tax", 0)), abs(eff.get("fed_payments", 0)), abs(eff.get("ca_payments", 0)))
            if a.get("group_effect") is not None:
                size = max(size, a["group_effect"])
            level = "partner" if size > thr else "reviewer"
            levels = {x["level"] for x in a["approvals"]}
            if level == "partner" and "partner" not in levels:
                out.append({"adjustment": a["id"], "level": "partner", "size": size, "line": a["line"], "by": a["by"]})
            elif level == "reviewer" and not levels:
                out.append({"adjustment": a["id"], "level": "reviewer", "size": size, "line": a["line"], "by": a["by"]})
        return out

    # ------------------------------------------------------------------ open items queue
    def open_items(self, uid: str | None = None) -> list[dict]:
        s = self.state()
        u = auth.user(self.p, uid) if uid else None
        items = []
        weight = {"error": 3, "warning": 2, "info": 1}
        for f in self.findings():
            if f["status"] in ("open", "client_answered"):
                e = f["effect"]
                impact = abs(e["fed_tax"]) + abs(e["ca_tax"]) + abs(e["fed_payments"]) + abs(e["ca_payments"])
                items.append({"type": "finding", "id": f["id"], "title": f["title"], "summary": f["summary"], "area": f["area"],
                              "severity": f["severity"], "kind": f["kind"], "impact": impact, "effect": e,
                              "score": weight[f["severity"]] * 1e6 + impact, "status": f["status"], "source": f["source"],
                              "lines": f["lines"], "needs": f.get("needs")})
        for a in self.approvals_needed(s):
            adj = s.adjustments[a["adjustment"]]
            items.append({"type": "approval", "id": a["adjustment"], "title": f"Approve adjustment to {adj['line']}: {adj.get('reason', '')[:80]}",
                          "summary": f"Needs {a['level']} approval (effect {a['size']:,.0f}). Recorded by {self.name(adj['by'])}.",
                          "area": area_for_line(adj["line"], adj["line"].split(".")[0]), "severity": "warning", "impact": a["size"],
                          "score": 2.5e6 + a["size"], "level": a["level"], "by": adj["by"], "lines": [adj["line"]]})
        for n in s.notes.values():
            if n["status"] == "open":
                items.append({"type": "note", "id": n["id"], "title": n["text"][:110], "summary": f"{'Blocking review note' if n.get('blocking') else 'Note'} by {self.name(n['by'])} on {n['target']}",
                              "area": self.target_area(n["target"]), "severity": "error" if n.get("blocking") else "info",
                              "impact": 0, "score": (3.5e6 if n.get("blocking") else 1.5e6), "assignee": n.get("assignee"),
                              "blocking": n.get("blocking"), "target": n["target"]})
        for q in s.questions.values():
            if q["status"] == "answered" and not q.get("reviewed"):
                items.append({"type": "client_answer", "id": q["id"], "title": f"Client answered: {q['text'][:80]}",
                              "summary": q.get("answer", "")[:160], "area": self.target_area(q["target"] or ""), "severity": "warning",
                              "impact": 0, "score": 2.2e6, "target": q["target"]})
            elif q["status"] == "open":
                items.append({"type": "client_question", "id": q["id"], "title": f"Waiting on client: {q['text'][:90]}",
                              "summary": f"Asked by {self.name(q['by'])} on {q['at'][:10]}", "area": self.target_area(q["target"] or ""),
                              "severity": "info", "impact": 0, "score": 0.5e6, "target": q["target"]})
        for d in self.document_index():
            if not d["accounted"]:
                items.append({"type": "document", "id": d["id"], "title": f"Account for {d['id']}: {d['title']}",
                              "summary": f"Engine status: {d['engine_status']}. Mark how it was used or why it is not needed.",
                              "area": d["area"], "severity": "info", "impact": 0, "score": 0.8e6})
        for a in self.area_status():
            for lvl, rec in a["signoffs"].items():
                if not rec["valid"]:
                    items.append({"type": "reopened", "id": f"{a['area']}:{lvl}", "title": f"Sign-off reopened: {a['title']} ({lvl})",
                                  "summary": f"Signed by {self.name(rec['by'])} on {rec['at'][:10]}; what was signed has changed since.",
                                  "area": a["area"], "severity": "warning", "impact": 0, "score": 2.4e6})
        if u and u["role"] != "client":
            for it in items:
                it["mine"] = self._is_mine(it, u)
        items.sort(key=lambda x: -x["score"])
        return items

    @staticmethod
    def _is_mine(it: dict, u: dict) -> bool:
        """Whether an open item is this person's to act on, by role."""
        role, kind = u["role"], it["type"]
        if kind == "approval":
            can_approve = it["level"] == "reviewer" and role in ("reviewer", "partner") or it["level"] == "partner" and role == "partner"
            return can_approve and it["by"] != u["id"]
        if kind == "note":
            return it.get("assignee") == u["id"]
        if role == "preparer":
            return kind in ("finding", "document", "client_answer", "reopened")
        if role == "reviewer":
            return kind == "reopened" or (kind == "finding" and it["severity"] == "error")
        return False

    def name(self, uid: str | None) -> str:
        if not uid:
            return "-"
        if uid == SYSTEM:
            return "System"
        u = auth.user(self.p, uid)
        return u["name"] if u else uid

    # ================================================================== commands
    def command(self, uid: str, cmd: dict) -> list[dict]:
        cmd = commands.parse(cmd)
        s = self.state()
        u = auth.user(self.p, uid)
        t = cmd.get("type")
        handler = getattr(self, f"_cmd_{t}", None)
        if handler is None:
            raise ValueError(f"Unknown command {t}")
        out = handler(u, s, cmd)
        return out if isinstance(out, list) else [out]

    def _ev(self, u, kind, target=None, data=None, batch=None):
        return self.store.append(actor=u["id"] if isinstance(u, dict) else u, kind=kind, sim_at=self.state().clock,
                                 target=target, data=data or {}, batch=batch)

    def _sealed_guard(self, s: State):
        if s.filing.get("sealed") and not s.filing.get("amendment_open"):
            raise auth.Denied("The return is filed and sealed. Start an amendment to change it.")

    # -- adjustments ---------------------------------------------------
    def _make_adjustment(self, u, s, line, delta, reason, authority, category=None, basis_fed=None, basis_ca=None,
                         finding=None, exact_effect=None, label=None, batch=None, note="", group_effect=None):
        if not reason or not reason.strip():
            raise ValueError("Every adjustment needs a reason")
        form = line.split(".")[0]
        cat = category or category_for_line(line, form)
        if basis_fed is None:
            basis_fed = delta * profit_sign(line, form) if cat not in ("payments_fed", "payments_ca", "ca_source_income", "none") else delta
            if cat == "ca_source_income":
                basis_fed = 0
        rates = self.p.current.raw["tax_effect_rates"]
        eff = exact_effect or effect_of(cat, basis_fed, basis_ca if basis_ca is not None else (delta if cat == "ca_source_income" else None), rates)
        base = self.p.current.lines.get(line)
        data = {"line": line, "delta": delta, "engine_value": base["value"] if base else None,
                "new_value": (base["value"] + delta) if base and isinstance(base["value"], (int, float)) else delta,
                "reason": reason, "authority": authority or "", "category": cat, "basis_fed": basis_fed, "basis_ca": basis_ca,
                "effect": {k: round(v) for k, v in eff.items()}, "finding": finding, "label": label, "note": note,
                "rates_version": "v3", "group_effect": group_effect}
        return self._ev(u, "adjustment.recorded", line, data, batch)

    def _cmd_adjust(self, u, s, c):
        auth.require(u, "adjust", s.clock)
        self._sealed_guard(s)
        line = c["line"]
        base = self.p.current.lines.get(line)
        if "new_value" in c and base is not None:
            delta = float(c["new_value"]) - float(base["value"]) - self.effective()["delta"].get(line, 0)
        else:
            delta = float(c["delta"])
        return self._make_adjustment(u, s, line, delta, c.get("reason", ""), c.get("authority"), c.get("category"),
                                     c.get("basis_fed"), c.get("basis_ca"))

    def _cmd_revert_adjustment(self, u, s, c):
        auth.require(u, "adjust", s.clock)
        self._sealed_guard(s)
        a = s.adjustments.get(c["adjustment"])
        if not a:
            raise ValueError("No such adjustment")
        return self._ev(u, "adjustment.reverted", a["line"], {"adjustment": a["id"], "reason": c.get("reason", "")})

    def _cmd_approve_adjustment(self, u, s, c):
        need = next((x for x in self.approvals_needed(s) if x["adjustment"] == c["adjustment"]), None)
        a = s.adjustments.get(c["adjustment"])
        if not a or not need:
            raise ValueError("Nothing to approve")
        auth.require(u, f"approve:{need['level']}", s.clock)
        if a["by"] == u["id"]:
            raise auth.Denied("A person may not review or approve work they prepared.")
        return self._ev(u, "adjustment.approved", a["line"], {"adjustment": a["id"], "level": need["level"]})

    def _cmd_accept_finding(self, u, s, c):
        """Accept a finding: record its suggested adjustments (optionally edited) and disposition it."""
        auth.require(u, "dispose_finding", s.clock)
        self._sealed_guard(s)
        f = self.finding(c["finding"])
        if not f:
            raise ValueError("No such finding")
        batch = c.get("batch") or f"b-{uuid.uuid4().hex[:10]}"
        evs = []
        rates_note = c.get("reason") or f"Per finding: {f['title']}"
        group = abs(f["effect"]["fed_tax"]) + abs(f["effect"]["ca_tax"]) + abs(f["effect"]["fed_payments"]) + abs(f["effect"]["ca_payments"])
        for sg in f["suggestions"]:
            e = self._make_adjustment(u, s, sg["line"], sg["delta"], rates_note, c.get("authority") or f.get("rule") or f["code"],
                                      sg["category"], sg["basis_fed"], sg["basis_ca"], f["id"], sg.get("exact_effect"),
                                      label=sg.get("note"), batch=batch, note=sg.get("note", ""), group_effect=group)
            evs.append(e)
        evs.append(self._ev(u, "finding.dispositioned", f["id"], {"disposition": "adjusted" if f["suggestions"] else "accepted",
                                                                  "reason": c.get("reason", ""), "authority": c.get("authority", ""),
                                                                  "adjustments": [e["id"] for e in evs]}, batch))
        return evs

    def _cmd_dismiss_finding(self, u, s, c):
        auth.require(u, "dispose_finding", s.clock)
        if not c.get("reason"):
            raise ValueError("Dismissing a finding needs a reason (and the authority relied on)")
        return self._ev(u, "finding.dispositioned", c["finding"], {"disposition": c.get("disposition", "dismissed"),
                                                                  "reason": c["reason"], "authority": c.get("authority", "")}, c.get("batch"))

    def _cmd_finding_to_client(self, u, s, c):
        auth.require(u, "ask_client", s.clock)
        f = self.finding(c["finding"])
        q = self._ev(u, "question.asked", c["finding"], {"text": c["text"], "to": c.get("to", "client"), "finding": c["finding"]})
        d = self._ev(u, "finding.dispositioned", c["finding"], {"disposition": "waiting_client", "question": q["id"],
                                                               "reason": "Asked the client", "authority": ""})
        _ = f
        return [q, d]

    def _cmd_bulk(self, u, s, c):
        """Act on many items at once; one batch id so the whole action undoes together."""
        batch = f"b-{uuid.uuid4().hex[:10]}"
        out = []
        for item in c["items"]:
            item = {**item, "batch": batch}
            t = item["type"]
            if t == "verify":
                out += self._cmd_verify(u, self.state(), item)
            elif t == "accept_finding":
                out += self._cmd_accept_finding(u, self.state(), item)
            elif t == "dismiss_finding":
                out.append(self._cmd_dismiss_finding(u, self.state(), item))
            elif t == "dispose_document":
                out.append(self._cmd_dispose_document(u, self.state(), item))
            elif t == "explain_variance":
                out.append(self._cmd_explain_variance(u, self.state(), item))
            else:
                raise ValueError(f"Bulk does not support {t}")
        return out

    def _cmd_undo(self, u, s, c):
        auth.require(u, "undo", s.clock)
        undoable = ("adjustment.recorded", "verification.recorded", "finding.dispositioned", "document.dispositioned",
                    "decision.recorded", "variance.explained", "household.corrected", "adjustment.approved", "signoff.recorded")
        if c.get("batch"):
            evs = [e for e in s.events if e["batch"] == c["batch"] and e["kind"] in undoable and e["id"] not in s.undone]
        elif c.get("event"):
            evs = [e for e in s.events if e["id"] == c["event"] and e["kind"] in undoable and e["id"] not in s.undone]
        else:  # the user's most recent action (batch or single)
            mine = [e for e in s.events if e["actor"] == u["id"] and e["kind"] in undoable and e["id"] not in s.undone]
            if not mine:
                raise ValueError("Nothing to undo")
            last = mine[-1]
            evs = [e for e in mine if last["batch"] and e["batch"] == last["batch"]] or [last]
        if not evs:
            raise ValueError("Nothing to undo")
        if any(e["actor"] != u["id"] for e in evs) and u["role"] not in ("partner",):
            raise auth.Denied("You can only undo your own actions")
        if s.filing.get("sealed") and any(e["seq"] < s.filing["sealed"].get("seq", 0) for e in evs):
            raise auth.Denied("Actions before filing are sealed")
        return self._ev(u, "action.undone", None, {"events": [e["id"] for e in evs],
                                                    "summary": f"Undid {len(evs)} event(s): {', '.join(sorted({e['kind'] for e in evs}))}"})

    # -- evidence ------------------------------------------------------
    def _cmd_verify(self, u, s, c):
        auth.require(u, "verify", s.clock)
        method = c["method"]
        if method not in s.standards.get("verification_types", []):
            raise ValueError(f"Unknown verification type {method}")
        targets = c.get("targets") or [c["target"]]
        out = []
        for t in targets:
            val = self.value_of(t) if t in self.p.current.lines else (self.p.values[t]["value"] if t in self.p.values else None)
            out.append(self._ev(u, "verification.recorded", t, {"method": method, "note": c.get("note", ""), "value": val,
                                                                "evidence": c.get("evidence", [])}, c.get("batch")))
        return out

    def _cmd_attach(self, u, s, c):
        auth.require(u, "attach", s.clock)
        return self._ev(u, "file.attached", c["target"], {"file": c["file"], "name": c.get("name"), "note": c.get("note", "")})

    def _cmd_dispose_document(self, u, s, c):
        auth.require(u, "dispose_document", s.clock)
        if not c.get("reason"):
            raise ValueError("Say why")
        return self._ev(u, "document.dispositioned", c["document"], {"status": c["status"], "reason": c["reason"]}, c.get("batch"))

    def _cmd_fix_household(self, u, s, c):
        auth.require(u, "fix_household", s.clock)
        self._sealed_guard(s)
        if not c.get("reason"):
            raise ValueError("Say why (cite the document)")
        return self._ev(u, "household.corrected", c["person"], {"field": c["field"], "value": c["value"], "reason": c["reason"],
                                                               "evidence": c.get("evidence", [])})

    # -- people --------------------------------------------------------
    def _cmd_note(self, u, s, c):
        auth.require(u, "note", s.clock)
        if c.get("blocking"):
            auth.require(u, "blocking_note", s.clock)
        return self._ev(u, "note.opened", c["target"], {"text": c["text"], "blocking": bool(c.get("blocking")),
                                                        "assignee": c.get("assignee"), "kind": c.get("kind", "review")})

    def _cmd_reply(self, u, s, c):
        auth.require(u, "reply", s.clock)
        return self._ev(u, "note.replied", c["note"], {"note": c["note"], "text": c["text"], "attachments": c.get("attachments", [])})

    def _cmd_resolve_note(self, u, s, c):
        auth.require(u, "resolve_note", s.clock)
        n = s.notes.get(c["note"])
        if not n:
            raise ValueError("No such note")
        if n.get("blocking") and n["by"] != u["id"] and u["role"] not in ("partner",):
            raise auth.Denied("Only the author (or the partner) can clear a blocking review note")
        evs = []
        if c.get("text"):
            evs.append(self._ev(u, "note.replied", c["note"], {"note": c["note"], "text": c["text"]}))
        evs.append(self._ev(u, "note.resolved", c["note"], {"note": c["note"]}))
        return evs

    def _cmd_reopen_note(self, u, s, c):
        auth.require(u, "note", s.clock)
        return self._ev(u, "note.reopened", c["note"], {"note": c["note"]})

    def _cmd_ask_client(self, u, s, c):
        auth.require(u, "ask_client", s.clock)
        return self._ev(u, "question.asked", c.get("target"), {"text": c["text"], "to": c.get("to", "client")})

    def _cmd_answer(self, u, s, c):
        auth.require(u, "answer", s.clock)
        q = s.questions.get(c["question"])
        if not q:
            raise ValueError("No such question")
        return self._ev(u, "question.answered", q["target"], {"question": q["id"], "text": c["text"], "attachments": c.get("attachments", [])})

    def _cmd_review_answer(self, u, s, c):
        auth.require(u, "verify", s.clock)
        if c["question"] not in s.questions:
            raise ValueError("No such question")
        return self._ev(u, "question.reviewed", c["question"], {"question": c["question"], "text": c.get("text", "Answer reviewed.")})

    def _cmd_signoff(self, u, s, c):
        area, level = c["area"], c["level"]
        auth.require(u, f"signoff:{level}", s.clock)
        so = s.signoffs.get(area, {})
        prepared_here = any(a["by"] == u["id"] for a in self.active_adjustments(s)
                            if area == "partner_review" or area_for_line(a["line"], a["line"].split(".")[0]) == area)
        if level in ("reviewer", "partner") and (so.get("preparer", {}).get("by") == u["id"] or prepared_here and level == "reviewer"):
            raise auth.Denied("A person may not review or sign off on work they prepared.")
        if level == "reviewer" and area != "partner_review" and not (so.get("preparer") and so["preparer"]["fingerprint"] == self.area_fingerprint(area, s)):
            raise auth.Denied("The preparer signs this area first (or their sign-off reopened)")
        if level == "partner" and area == "partner_review":
            missing = [a["title"] for a in self.area_status() if a["area"] != "partner_review" and not a["signoffs"].get("reviewer", {}).get("valid")]
            if missing:
                raise auth.Denied(f"Reviewer sign-off still needed: {', '.join(missing[:3])}{'...' if len(missing) > 3 else ''}")
        blocking = [n for n in s.notes.values() if n["status"] == "open" and n.get("blocking") and
                    (self.target_area(n["target"]) == area or area == "partner_review")]
        if blocking and level != "preparer":
            raise auth.Denied(f"{len(blocking)} open blocking review note(s) in this area")
        if level == "partner" and area == "partner_review":
            big = [a for a in self.approvals_needed(s) if a["level"] == "partner"]
            if big:
                raise auth.Denied(f"Approve {len(big)} adjustment(s) over the partner threshold first")
        return self._ev(u, "signoff.recorded", area, {"level": level, "fingerprint": self.area_fingerprint(area, s), "note": c.get("note", "")})

    def _cmd_withdraw_signoff(self, u, s, c):
        rec = s.signoffs.get(c["area"], {}).get(c["level"])
        if not rec or rec["by"] != u["id"]:
            raise auth.Denied("Only the signer can withdraw a sign-off")
        return self._ev(u, "signoff.withdrawn", c["area"], {"level": c["level"]})

    def _cmd_complete_step(self, u, s, c):
        auth.require(u, "verify", s.clock)
        return self._ev(u, "step.completed", c["step"], {"note": c.get("note", ""), "evidence": c.get("evidence", [])})

    def _cmd_decide(self, u, s, c):
        auth.require(u, "decide", s.clock)
        if not c.get("authority") and c["topic"] != "due_diligence":
            raise ValueError("Every judgment call records the authority relied on")
        evs = [self._ev(u, "decision.recorded", c["topic"], {"choice": c["choice"], "rationale": c.get("rationale", ""),
                                                             "authority": c.get("authority", ""), "answers": c.get("answers"),
                                                             "what_if": c.get("what_if"), "finding": c.get("finding")})]
        if c.get("finding"):
            evs.append(self._ev(u, "finding.dispositioned", c["finding"], {"disposition": "decided", "reason": c.get("rationale", ""),
                                                                           "authority": c.get("authority", ""), "decision": c["topic"]}))
        return evs

    def _cmd_explain_variance(self, u, s, c):
        auth.require(u, "verify", s.clock)
        if not c.get("text"):
            raise ValueError("Explain the change")
        return self._ev(u, "variance.explained", c["key"], {"text": c["text"], "evidence": c.get("evidence", [])}, c.get("batch"))

    def _cmd_log_time(self, u, s, c):
        auth.require(u, "log_time", s.clock)
        return self._ev(u, "time.logged", c["area"], {"area": c["area"], "hours": float(c["hours"]), "note": c.get("note", "")})

    def _cmd_assign(self, u, s, c):
        auth.require(u, "assign", s.clock)
        return self._ev(u, "assignment.set", "engagement", {"assignments": {c["role"]: c["staff"]}})

    def _cmd_standard(self, u, s, c):
        auth.require(u, "standards", s.clock)
        return self._ev(u, "standards.changed", c["path"], {"path": c["path"], "value": c["value"], "reason": c.get("reason", "")})

    def _cmd_seen(self, u, s, c):
        return self._ev(u, "user.seen", None, {"seq": int(c.get("seq") or self.store.head())})

    def _cmd_reveal(self, u, s, c):
        if not u.get("clearance"):
            raise auth.Denied(f"{u['name']} has no sensitive-data clearance")
        return self._ev(u, "sensitive.viewed", c["target"], {"field": c.get("field", ""), "reason": c.get("reason", "")})

    # -- filing --------------------------------------------------------
    def filing_gates(self, s: State | None = None) -> list[dict]:
        s = s or self.state()
        steps = self.required_steps()
        blocking = [n for n in s.notes.values() if n["status"] == "open" and n.get("blocking")]
        gates = [{"gate": st["step"], "ok": st["done"], "why": st["why"]} for st in steps if not st["step"].lower().startswith("client approval")]
        gates.append({"gate": "No open blocking review notes", "ok": not blocking, "why": f"{len(blocking)} open" if blocking else "None open"})
        return gates

    def _cmd_send_to_client(self, u, s, c):
        auth.require(u, "send_to_client", s.clock)
        not_ok = [g for g in self.filing_gates(s) if not g["ok"]]
        if not_ok and not c.get("force"):
            raise auth.Denied("Not ready: " + "; ".join(g["gate"] for g in not_ok[:4]))
        return self._ev(u, "filing.sent_to_client", "F8879", {"fingerprint": self.return_fingerprint(s), "summary": self.summary(s)["workpaper"]})

    def _cmd_client_approve(self, u, s, c):
        auth.require(u, "client_approve", s.clock)
        sent = s.filing.get("sent")
        if not sent:
            raise ValueError("Nothing has been sent for approval")
        return self._ev(u, "filing.client_approved", "F8879", {"fingerprint": sent["fingerprint"], "via": "portal",
                                                               "pin_entered": True, "presented": True})

    def _cmd_transmit(self, u, s, c):
        auth.require(u, "transmit", s.clock)
        sub = s.filing.get("submission")
        if sub and sub["result"] in ("pending",):
            raise ValueError("A submission is already pending")
        if sub and sub["result"] == "accepted":
            raise ValueError("Already accepted")
        not_ok = [g for g in self.filing_gates(s) if not g["ok"]]
        ca = s.filing.get("client_approval")
        if not ca or ca["fingerprint"] != self.return_fingerprint(s):
            not_ok.append({"gate": "Client approval of this exact return"})
        if not_ok and not c.get("force"):
            raise auth.Denied("Cannot transmit: " + "; ".join(g["gate"] for g in not_ok[:5]))
        ev = self._ev(u, "filing.transmitted", "efile", {"fingerprint": self.return_fingerprint(s), "forced": bool(c.get("force")),
                                                          "open_gates": [g["gate"] for g in not_ok]})
        out = [ev]
        # agency acknowledgments already due in the season script apply immediately
        due = [t for t in self.p.timeline if t["event"].startswith("efile_") and t["at"] <= s.clock]
        if due:
            out += self._acknowledge(self.state().filing["submission"], s.clock)
        return out

    def _cmd_deliver(self, u, s, c):
        auth.require(u, "deliver", s.clock)
        if not s.filing.get("sealed"):
            raise ValueError("Deliver the client copy after acceptance")
        return self._ev(u, "filing.delivered", "client_copy", {"fingerprint": s.filing["sealed"]["fingerprint"]})

    def _cmd_start_amendment(self, u, s, c):
        auth.require(u, "amend", s.clock)
        if not s.filing.get("sealed"):
            raise ValueError("Nothing filed to amend")
        if not c.get("reason"):
            raise ValueError("Why amend?")
        return self._ev(u, "amendment.started", "F1040X", {"reason": c["reason"], "base_fingerprint": s.filing["sealed"]["fingerprint"]})

    def _cmd_respond_notice(self, u, s, c):
        auth.require(u, "respond_notice", s.clock)
        return self._ev(u, "notice.responded", c["notice"], {"text": c.get("text", ""), "packet_hash": c.get("packet_hash")})

    # -- clock (season replay) -----------------------------------------
    def _cmd_advance_clock(self, u, s, c):
        auth.require(u, "advance_clock", s.clock)
        to = c["to"]
        if to <= s.clock:
            raise ValueError("The clock only moves forward (replay). Reset the demo to start over.")
        evs = self._replay_timeline(s.clock, to)
        evs.append(self.store.append(actor=u["id"], kind="clock.advanced", sim_at=to, data={"from": s.clock, "to": to}))
        return evs

    def next_timeline(self, s: State | None = None) -> list[dict]:
        s = s or self.state()
        return [t for t in self.p.timeline if t["at"] > s.clock]

    # ================================================================== change feed
    def changes_since(self, uid: str) -> dict:
        s = self.state()
        base = next((e["seq"] for e in s.events if e["kind"] == "clock.set"), 0)
        since = max(s.seen.get(uid, 0), base)
        evs = [e for e in s.events if e["seq"] > since and e["actor"] != uid and e["kind"] not in ("user.seen", "sensitive.viewed")]
        return {"since": since, "head": s.seq, "events": [self.describe(e) for e in evs[-200:]], "count": len(evs)}

    def describe(self, e: dict) -> dict:
        k, d = e["kind"], e["data"]
        s = self.state()
        txt = k
        if k == "adjustment.recorded":
            txt = f"Adjusted {d['line']} by {d['delta']:+,.0f}: {d['reason']}"
        elif k == "adjustment.reverted":
            txt = f"Reverted adjustment {d['adjustment']}: {d.get('reason', '')}"
        elif k == "adjustment.approved":
            txt = f"Approved adjustment {d['adjustment']} ({d['level']})"
        elif k == "verification.recorded":
            txt = f"Verified {e['target']} ({d['method'].replace('_', ' ')})"
        elif k == "note.opened":
            txt = f"{'Blocking review note' if d.get('blocking') else 'Note'} on {e['target']}: {d['text']}"
        elif k == "note.replied":
            txt = f"Replied: {d['text']}"
        elif k == "note.resolved":
            txt = "Resolved a note"
        elif k == "question.asked":
            txt = f"Asked the client: {d['text']}"
        elif k == "question.answered":
            txt = f"Client answered: {d['text']}"
        elif k == "finding.dispositioned":
            txt = f"Finding {e['target']} -> {d['disposition']}" + (f": {d['reason']}" if d.get("reason") else "")
        elif k == "document.dispositioned":
            txt = f"{e['target']} marked {d['status']}: {d['reason']}"
        elif k == "decision.recorded":
            txt = f"Decision {e['target']}: {d['choice']}"
        elif k == "signoff.recorded":
            txt = f"Signed off {AREA_TITLES.get(e['target'], e['target'])} as {d['level']}"
        elif k.startswith("timeline."):
            it = d["item"]
            txt = f"Season: {it['event'].replace('_', ' ')}" + (f" ({', '.join(it['refs'])})" if it.get("refs") else "")
            if it.get("detail"):
                txt += f" - {auth.mask_text(it['detail'])}"
        elif k == "clock.advanced":
            txt = f"Clock advanced to {d['to'][:10]}"
        elif k == "action.undone":
            txt = d.get("summary", "Undo")
        elif k == "household.corrected":
            txt = f"Corrected {e['target']} {d['field']}: {d['reason']}"
        elif k == "variance.explained":
            txt = f"Explained variance on {e['target']}: {d['text']}"
        elif k.startswith("filing."):
            txt = {"filing.extension_filed": "Extension filed with payment (Form 4868 36,000; FTB 3519 0)",
                   "filing.sent_to_client": "Return sent to the client for approval",
                   "filing.client_approved": "Client approved and signed Forms 8879",
                   "filing.transmitted": "E-file transmitted", "filing.rejected": f"E-file rejected ({d.get('jurisdiction')}): {'; '.join(x['message'] for x in d.get('errors', []))}",
                   "filing.accepted": f"E-file accepted ({d.get('jurisdiction')})", "filing.sealed": "Return sealed at filing",
                   "filing.delivered": "Client copy delivered", "filing.payment": f"Payment: {d.get('detail', '')}",
                   "filing.refund": f"Refund: {d.get('detail', '')}", "filing.ack_pending": d.get("note", "")}.get(k, k)
        elif k == "time.logged":
            txt = f"Logged {d['hours']}h on {AREA_TITLES.get(d['area'], d['area'])}"
        elif k == "notice.received":
            txt = f"IRS notice received: {d['notice']['type']}"
        elif k == "standards.changed":
            txt = f"Firm standard {d['path']} -> {d['value']}"
        return {"seq": e["seq"], "id": e["id"], "kind": k, "actor": e["actor"], "actor_name": self.name(e["actor"]), "at": e["at"],
                "sim_at": e["sim_at"], "target": e["target"], "text": txt, "batch": e["batch"], "undone": e["id"] in s.undone}
