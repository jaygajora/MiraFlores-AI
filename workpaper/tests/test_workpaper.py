"""End-to-end checks of the workpaper: the season from findings to filing to a notice.

Run: python -m unittest discover -s tests -v
"""
import unittest
from pathlib import Path

from app import auth
from app.checks import run_checks
from app.packet import Packet
from app.state import Workpaper
from app.store import EventStore

PACKET = Packet(Path(__file__).resolve().parent.parent / "data" / "okafor_lindqvist_2025_packet.json")
PREP, PREP2, REV, PARTNER, ADMIN, CLIENT = "st-01", "st-04", "st-02", "st-03", "st-05", "cu-01"


_STORES: list[EventStore] = []


def fresh() -> Workpaper:
    store = EventStore(":memory:")
    _STORES.append(store)
    return Workpaper(PACKET, store)


def tearDownModule():
    for s in _STORES:
        s.close()


class PacketTests(unittest.TestCase):
    def test_loads_as_delivered(self):
        self.assertEqual(len(PACKET.docs), 74)
        self.assertEqual(len(PACKET.values), 3012)
        self.assertEqual(set(PACKET.versions), {"v1", "v2", "v3"})

    def test_engine_sums_all_reconcile(self):
        v = PACKET.current
        for key, signs in v.signs.items():
            line = v.lines[key]
            if line["rule"] != "R-SUM":
                continue
            total = sum(sg * (v.lines[i]["value"] if i in v.lines else 0) for i, sg in signs.items())
            self.assertAlmostEqual(total, line["value"], delta=1.01, msg=key)

    def test_every_value_has_a_landing_or_reason(self):
        for ev in PACKET.values:
            land = PACKET.landing_for_value(ev)
            self.assertTrue(land.get("lines") or land.get("reason"), ev)


class LayoutTests(unittest.TestCase):
    def test_every_page_lays_out(self):
        from app.layout import layout
        for d in PACKET.raw["documents"]:
            for p in d["pages"]:
                blocks = layout(p["printed_content"])
                self.assertTrue(blocks, (d["id"], p["page"]))

    def test_w2_boxes_and_anchors(self):
        from app.layout import layout
        from app.views import locate
        text = PACKET.page_text("D08", 1)
        items = [i for b in layout(text) if b["type"] == "fields" for i in b["items"]]
        box1 = next(i for i in items if i["label"] == "Box 1")
        self.assertEqual(box1["value"], "104,600.00")
        span = locate(text, PACKET.values["ev-0016"])
        self.assertTrue(box1["value_span"][0] <= span[0] and span[1] <= box1["value_span"][1])
        self.assertIn("Box 12 W", [i["label"] for i in items])

    def test_lots_and_trips_become_tables(self):
        from app.layout import layout
        lots = [b for b in layout(PACKET.page_text("D74", 2)) if b["type"] == "table"]
        self.assertEqual(len(lots[0]["rows"]), 10)
        self.assertIn("wash sale loss disallowed", [c["key"] for c in lots[0]["columns"]])
        trips = [b for b in layout(PACKET.page_text("D23", 1)) if b["type"] == "table"]
        self.assertEqual(trips[0]["kind"], "trips")
        self.assertEqual(len(trips[0]["rows"]), 20)


class CheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = run_checks(PACKET, set(PACKET.docs), "2026-12-31")
        cls.ids = {f["id"]: f for f in cls.r["findings"]}

    def test_planted_errors_are_found(self):
        for fid in ["F-RSU-BASIS", "F-CA-WAGES", "F-SEHI", "F-1099K-IN-BOOKS", "F-HVAC", "F-EST-CA", "F-EST-FED", "F-PROPTAX",
                    "F-DUPPAGE-D23-3", "F-CAR", "F-DUP-SchB.1.2", "F-MORTINT", "F-MIXED-USE", "F-FX-SchB.1.6", "F-UNREAD-D31",
                    "F-READ-ev-1045", "F-READ-ev-1049", "F-SSN-theo", "F-CRYPTO-C6"]:
            self.assertIn(fid, self.ids, fid)

    def test_effects(self):
        self.assertEqual(self.ids["F-RSU-BASIS"]["effect"]["fed_tax"], -15536)
        self.assertEqual(self.ids["F-EST-FED"]["effect"]["fed_payments"], -1000)
        self.assertEqual(self.ids["F-EST-CA"]["effect"]["ca_payments"], -3500)
        self.assertEqual(self.ids["F-HVAC"]["effect"]["fed_tax"], 3633)  # exact, from the engine's what-if

    def test_second_read_finds_the_transposed_ein(self):
        self.assertIn("74-3829156", self.ids["F-READ-ev-1045"]["summary"])

    def test_late_message_not_used_before_it_arrives(self):
        early = run_checks(PACKET, {d for d, x in PACKET.docs.items() if x["received_at"] <= "2026-06-24"}, "2026-06-24")
        self.assertNotIn("F-CRYPTO-C6", {f["id"] for f in early["findings"]})

    def test_recalculations_pass(self):
        passes = {p["id"] for p in self.r["passes"]}
        for pid in ("P-W2-box1", "P-EXCESS-SS", "P-SUMS", "P-CARRY", "P-PAL", "P-7203", "P-8606"):
            self.assertIn(pid, passes)


class FlowTests(unittest.TestCase):
    def test_adjustment_effect_and_propagation(self):
        w = fresh()
        w.command(PREP, {"type": "accept_finding", "finding": "F-1099K-IN-BOOKS"})
        self.assertEqual(w.value_of("SchC.1"), 151300)
        self.assertEqual(w.value_of("SchC.31"), 81854 - 12400)
        self.assertEqual(w.value_of("F1040.11"), 445590 - 12400)  # exact through sums and carries
        self.assertIn("SchSE.4a", w.effective()["stale"])           # engine logic: flagged, not faked
        self.assertEqual(w.summary()["workpaper"]["federal"]["total_tax"], 81962 - 4402)

    def test_roles_are_enforced(self):
        w = fresh()
        with self.assertRaises(auth.Denied):
            w.command(CLIENT, {"type": "adjust", "line": "SchC.1", "delta": -1, "reason": "x"})
        with self.assertRaises(auth.Denied):
            w.command(PREP, {"type": "note", "target": "SchC.1", "text": "x", "blocking": True})
        w.command(PREP, {"type": "accept_finding", "finding": "F-MORTINT"})
        adj = w.active_adjustments()[0]
        with self.assertRaises(auth.Denied):
            w.command(PREP, {"type": "approve_adjustment", "adjustment": adj["id"]})  # own work
        w.command(REV, {"type": "approve_adjustment", "adjustment": adj["id"]})
        with self.assertRaises(auth.Denied):
            w.command(PREP2, {"type": "reveal", "target": "D08"})  # no clearance

    def test_large_adjustment_needs_partner(self):
        w = fresh()
        w.command(PREP, {"type": "accept_finding", "finding": "F-SEHI"})
        need = w.approvals_needed()
        self.assertEqual(need[0]["level"], "partner")
        with self.assertRaises(auth.Denied):
            w.command(REV, {"type": "approve_adjustment", "adjustment": need[0]["adjustment"]})
        w.command(PARTNER, {"type": "approve_adjustment", "adjustment": need[0]["adjustment"]})
        self.assertEqual(w.approvals_needed(), [])

    def test_signoff_reopens_when_signed_work_changes(self):
        w = fresh()
        w.command(PREP, {"type": "signoff", "area": "business", "level": "preparer"})
        self.assertTrue(next(a for a in w.area_status() if a["area"] == "business")["signoffs"]["preparer"]["valid"])
        w.command(PREP, {"type": "accept_finding", "finding": "F-MIXED-USE"})
        self.assertFalse(next(a for a in w.area_status() if a["area"] == "business")["signoffs"]["preparer"]["valid"])

    def test_preparer_cannot_review_own_area(self):
        w = fresh()
        w.command(REV, {"type": "accept_finding", "finding": "F-CAR"})
        with self.assertRaises(auth.Denied):
            w.command(REV, {"type": "signoff", "area": "deductions_and_credits", "level": "reviewer"})

    def test_blocking_note_blocks(self):
        w = fresh()
        w.command(REV, {"type": "note", "target": "SchC.1", "text": "Tie receipts to deposits", "blocking": True})
        with self.assertRaises(auth.Denied):
            w.command(REV, {"type": "signoff", "area": "business", "level": "reviewer"})
        self.assertFalse(next(g for g in w.filing_gates() if "blocking" in g["gate"])["ok"])

    def test_bulk_and_undo(self):
        w = fresh()
        base = w.summary()["workpaper"]["federal"]["total_tax"]
        w.command(PREP, {"type": "bulk", "items": [{"type": "accept_finding", "finding": f} for f in ("F-CAR", "F-MORTINT", "F-MIXED-USE")]})
        self.assertNotEqual(w.summary()["workpaper"]["federal"]["total_tax"], base)
        w.command(PREP, {"type": "undo"})
        self.assertEqual(w.summary()["workpaper"]["federal"]["total_tax"], base)
        self.assertEqual(len(w.active_adjustments()), 0)
        self.assertTrue(w.store.verify_chain()["ok"])

    def test_client_question_becomes_evidence(self):
        w = fresh()
        w.command(PREP, {"type": "finding_to_client", "finding": "F-ACK-D64", "text": "Can the parish send a letter that says no goods or services were provided?"})
        q = next(iter(w.state().questions.values()))
        w.command(CLIENT, {"type": "answer", "question": q["id"], "text": "Yes, attached."})
        self.assertEqual(w.finding("F-ACK-D64")["status"], "client_answered")

    def test_whole_season(self):
        w = fresh()
        # 1 resolve every finding
        for f in w.findings():
            if f["status"] != "open":
                continue
            if f["suggestions"]:
                w.command(PREP, {"type": "accept_finding", "finding": f["id"]})
            elif f["id"] == "F-SSN-theo":
                w.command(PREP, {"type": "fix_household", "person": "theo", "field": "ssn", "value": "666-74-3390", "reason": "2024 return D06"})
                w.command(PREP, {"type": "decide", "topic": f["id"], "choice": "corrected", "rationale": "Per 2024 return", "authority": "D06", "finding": f["id"]})
            else:
                w.command(PREP, {"type": "decide", "topic": f["id"], "choice": "noted", "rationale": "Reviewed", "authority": "Firm judgment", "finding": f["id"]})
        self.assertNotIn("F-SSN-theo", {f["id"] for f in w.findings() if f["status"] == "open"})
        # 2 documents, variances, steps, due diligence
        for d in w.document_index():
            if not d["accounted"]:
                w.command(PREP, {"type": "dispose_document", "document": d["id"], "status": "reviewed_not_input", "reason": "Reviewed"})
        from app.checks import variances
        w.command(PREP, {"type": "bulk", "items": [{"type": "explain_variance", "key": v["key"], "text": "Move to Texas, new business year"} for v in variances(PACKET, w.state().standards["variance_review"])]})
        w.command(PREP, {"type": "complete_step", "step": "identity"})
        w.command(PREP, {"type": "complete_step", "step": "prior_year"})
        w.command(PREP, {"type": "decide", "topic": "due_diligence", "choice": "completed"})
        # 3 approvals and sign-offs
        for a in w.approvals_needed():
            w.command(PARTNER if a["level"] == "partner" else REV, {"type": "approve_adjustment", "adjustment": a["adjustment"]})
        for a, _ in [(x["area"], 0) for x in w.area_status() if x["area"] != "partner_review"]:
            w.command(PREP, {"type": "signoff", "area": a, "level": "preparer"})
            w.command(REV, {"type": "signoff", "area": a, "level": "reviewer"})
        w.command(PARTNER, {"type": "signoff", "area": "partner_review", "level": "partner"})
        open_steps = [s["step"] for s in w.required_steps() if not s["done"]]
        self.assertEqual(open_steps, ["Client approval and e-file authorization"])
        # 4 client approval, transmit, acknowledgments, seal
        w.command(PARTNER, {"type": "send_to_client"})
        w.command(CLIENT, {"type": "client_approve"})
        w.command(PARTNER, {"type": "transmit"})
        w.command(ADMIN, {"type": "advance_clock", "to": "2026-07-16T00:00:00Z"})
        st = w.state()
        self.assertEqual(st.filing["submission"]["result"], "accepted")   # SSN fixed before filing: no rejection
        self.assertIn("sealed", st.filing)
        with self.assertRaises(auth.Denied):
            w.command(PREP, {"type": "adjust", "line": "SchC.1", "delta": 1, "reason": "late"})
        w.command(PARTNER, {"type": "start_amendment", "reason": "Corrected 1099 arrived"})
        w.command(PREP, {"type": "adjust", "line": "SchC.1", "delta": 1, "reason": "amended"})
        # 5 years later: the notice
        w.command(ADMIN, {"type": "advance_clock", "to": "2028-02-01T00:00:00Z"})
        self.assertIn("N-2025-L566", w.state().notices)
        from app.views import notice_packet
        html = notice_packet(w, "N-2025-L566")
        self.assertIn("Form 1099-K", html)
        self.assertTrue(w.store.verify_chain()["ok"])

    def test_commands_are_validated(self):
        from app.commands import CommandError
        w = fresh()
        with self.assertRaises(CommandError):
            w.command(PREP, {"type": "adjust", "line": "SchC.1", "delta": 1, "reason": "   "})   # blank reason
        with self.assertRaises(CommandError):
            w.command(PREP, {"type": "log_time", "area": "business", "hours": 99})
        with self.assertRaises(CommandError):
            w.command(PREP, {"type": "nonsense"})
        with self.assertRaises(auth.Denied):
            w.command(PREP, {"type": "advance_clock", "to": "2026-07-01T00:00:00Z"})  # only admin or partner

    def test_finding_ids_are_stable(self):
        a = {f["id"] for f in fresh().findings()}
        b = {f["id"] for f in fresh().findings()}
        self.assertEqual(a, b)
        self.assertTrue(any(i.startswith("F-PRIOR-") for i in a))

    def test_rejection_when_ssn_not_fixed(self):
        w = fresh()
        w.command(PARTNER, {"type": "send_to_client", "force": True})
        w.command(CLIENT, {"type": "client_approve"})
        w.command(PARTNER, {"type": "transmit", "force": True})
        w.command(ADMIN, {"type": "advance_clock", "to": "2026-07-13T18:00:00Z"})
        self.assertEqual(w.state().filing["submission"]["result"], "rejected")


class ApiTests(unittest.TestCase):
    """HTTP behaviour: validation, uploads, security headers. Skipped when FastAPI is not installed."""

    @classmethod
    def setUpClass(cls):
        try:
            import os
            import tempfile
            os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
            from fastapi.testclient import TestClient

            from app.main import app
        except ImportError as e:  # pragma: no cover
            raise unittest.SkipTest(f"FastAPI not installed: {e}") from e
        cls.c = TestClient(app)
        cls.H = {"X-User": PREP}

    def test_invalid_command_is_422(self):
        r = self.c.post("/api/command", headers=self.H, json={"type": "adjust", "line": "SchC.1", "delta": 1})
        self.assertEqual(r.status_code, 422)
        self.assertIn("reason", r.json()["error"])

    def test_internal_command_rejected(self):
        r = self.c.post("/api/command", headers=self.H, json={"type": "attach", "target": "SchC.1", "file": {"id": "f-x"}})
        self.assertEqual(r.status_code, 422)

    def test_uploaded_html_is_downloaded_not_rendered(self):
        import base64
        r = self.c.post("/api/upload", headers=self.H, json={"target": "SchC.1", "name": "../evil.html", "mime": "text/html",
                                                          "content": base64.b64encode(b"<script>alert(1)</script>").decode()})
        self.assertEqual(r.status_code, 200)
        f = r.json()["file"]
        self.assertEqual(f["name"], "evil.html")
        g = self.c.get(f"/api/files/{f['id']}?x_user={PREP}")
        self.assertTrue(g.headers["content-disposition"].startswith("attachment"))
        self.assertEqual(g.headers["content-type"], "application/octet-stream")
        self.assertEqual(g.headers["x-content-type-options"], "nosniff")
        self.assertIn("sandbox", g.headers["content-security-policy"])

    def test_app_has_csp(self):
        r = self.c.get("/")
        csp = r.headers["content-security-policy"]
        self.assertIn("script-src 'self';", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotIn("https://", r.text, "the app shell loads nothing from other origins")

    def test_household_fix_offered_from_documents(self):
        r = self.c.get("/api/filing", headers={"X-User": PREP}).json()
        fixes = {f["person"]: f for f in r["household_fixes"]}
        self.assertIn("theo", fixes)
        self.assertTrue(fixes["theo"]["evidence"])
        self.assertTrue(fixes["theo"]["shown"].startswith("•••-••-"))
        r2 = self.c.get("/api/filing", headers={"X-User": PREP2}).json()
        self.assertIsNone({f["person"]: f for f in r2["household_fixes"]}["theo"]["value"], "no clearance, no full SSN")

    def test_masking_without_clearance(self):
        r = self.c.get("/api/document/D08?reveal=1", headers={"X-User": PREP2})
        self.assertEqual(r.status_code, 403)
        r = self.c.get("/api/document/D08", headers={"X-User": PREP2})
        self.assertNotIn("666-41-2287", r.text)


if __name__ == "__main__":
    unittest.main()
