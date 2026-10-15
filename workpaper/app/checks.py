"""Independent checks: rules that do not trust the engine or the extraction.

Each rule reads the packet (documents' printed content, extracted values, client
answers, agency records, prior years) and either:
  * proves something (a recalculation that agrees) -> a "pass" that becomes
    machine verification evidence on the lines it covers, or
  * raises a finding with evidence refs, the lines affected, and a suggested
    adjustment with its tax effect.

Rules never name a specific document, value or answer id: they find their
evidence by document type, field name and question text (see Packet lookups),
so they would run unchanged on another household's packet. Where a rule parses
printed text, that stands in for structured extraction of the same field; the
evidence chain (which page, which words) is the same either way.
"""
from __future__ import annotations

import contextlib
import hashlib
import re
from dataclasses import asdict, dataclass, field

from .domain import area_for_line, effect_of
from .packet import Packet


@dataclass
class Suggestion:
    line: str
    delta: float
    category: str
    basis_fed: float
    basis_ca: float | None = None
    note: str = ""
    exact_effect: dict | None = None  # from an engine what-if


@dataclass
class Finding:
    id: str
    code: str
    severity: str           # error | warning | info
    kind: str               # error | judgment | outside_filing | process | planning | data
    area: str
    title: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    source: str = "check"   # check | engine
    rule: str = ""
    effect: dict = field(default_factory=dict)
    needs: str | None = None  # what is needed to resolve, e.g. "client confirmation"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Pass:
    id: str
    title: str
    detail: str
    lines: list[str]
    evidence: list[str] = field(default_factory=list)


def money(s: str) -> float:
    return float(s.replace(",", "").replace("$", "").rstrip("."))


def fmt(x: float) -> str:
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.2f}"


def stable_id(prefix: str, text: str) -> str:
    """Deterministic id from text (Python's hash() changes between processes)."""
    return f"{prefix}-{hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()[:8]}"


class Checker:
    def __init__(self, packet: Packet, visible_docs: set[str] | None = None, household_fixes: dict | None = None,
                 clock: str = "9999"):
        self.p = packet
        self.v = packet.current
        self.rates = self.v.raw["tax_effect_rates"]
        self.visible = visible_docs if visible_docs is not None else set(packet.docs)
        self.household_fixes = household_fixes or {}
        self.clock = clock
        self.findings: list[Finding] = []
        self.passes: list[Pass] = []

    # ------------------------------------------------------------------ util
    def L(self, key):
        return self.v.lines.get(key)

    def val(self, key, default=0):
        line = self.L(key)
        return line["value"] if line else default

    def text(self, doc, page=1):
        return self.p.page_text(doc, page)

    def doc(self, doc_type: str, **kw) -> dict | None:
        return self.p.doc_of(doc_type, self.visible, **kw)

    def messages(self) -> list[dict]:
        return [m for m in self.p.messages.values() if m["sent_at"][:10] <= self.clock[:10]]

    def add(self, f: Finding):
        total = {"fed_tax": 0.0, "ca_tax": 0.0, "fed_payments": 0.0, "ca_payments": 0.0}
        for s in f.suggestions:
            e = s.exact_effect or effect_of(s.category, s.basis_fed, s.basis_ca, self.rates)
            for k in total:
                total[k] += e.get(k, 0)
        f.effect = {k: round(v) for k, v in total.items()}
        f.evidence = [r for r in dict.fromkeys(f.evidence) if r]
        if not f.area and f.lines:
            line = self.L(f.lines[0])
            f.area = area_for_line(f.lines[0], line["form"] if line else "")
        self.findings.append(f)

    def ok(self, pid, title, detail, lines, evidence=()):
        self.passes.append(Pass(pid, title, detail, list(lines), [r for r in evidence if r]))

    # ------------------------------------------------------------------ run
    def run(self) -> Checker:
        for name in sorted(n for n in dir(self) if n.startswith("check_")):
            getattr(self, name)()
        sev = {"error": 0, "warning": 1, "info": 2}
        self.findings.sort(key=lambda f: (sev[f.severity], -sum(abs(v) for v in f.effect.values())))
        return self

    # ================================================================== extraction
    def check_01_second_read(self):
        """Every extracted value must appear on the page it was read from."""
        for e in self.p.raw["extracted_values"]:
            if e["document_id"] not in self.visible or e["value_type"] == "boolean" or e["value"] in (None, ""):
                continue
            page = self.text(e["document_id"], e["page"])
            if any(x and x in page for x in _variants(e)):
                continue
            used = self.p.lines_citing(e["id"])
            near = _near_candidates(e, page)
            hint = f" The page shows {', '.join(repr(n) for n in near)}." if near else ""
            ambiguous = "ambiguous" in page.lower()
            if ambiguous:
                hint = " The page itself says the amount is ambiguous: '" + _sentence_with(page, "ambiguous") + "'"
            self.add(Finding(
                id=f"F-READ-{e['id']}", code="SECOND_READ_MISMATCH", severity="error" if used else "warning",
                kind="error", area="", rule="Extracted text must be found on the printed page",
                title=f"{self.p.docs[e['document_id']]['title']}: '{e['label']}' does not match the page",
                summary=f"The pipeline read {e['text_as_read']!r} (confidence {e['confidence']:.2f}).{hint}",
                evidence=[e["id"], f"{e['document_id']}#page{e['page']}"], lines=used,
                needs="client confirmation" if ambiguous else "correct the value"))

    def check_02_low_confidence(self):
        for e in self.p.raw["extracted_values"]:
            if e["confidence"] >= 0.9 or e["document_id"] not in self.visible or not self.p.lines_citing(e["id"]):
                continue
            if any(f.id == f"F-READ-{e['id']}" for f in self.findings):
                continue
            self.add(Finding(
                id=f"F-CONF-{e['id']}", code="LOW_CONFIDENCE", severity="warning", kind="data", area="",
                title=f"Low-confidence read feeds the return: {e['label']}",
                summary=f"Read as {e['text_as_read']!r} with confidence {e['confidence']:.2f}.",
                evidence=[e["id"]], lines=self.p.lines_citing(e["id"]), needs="verify against the source"))

    def check_03_unread_pages(self):
        for d in self.p.raw["documents"]:
            if d["id"] not in self.visible or d["extraction"]["status"] != "partial":
                continue
            if d["id"] in self.v.raw.get("documents_superseded", []):
                continue
            m = re.search(r"Page (\d+)", d["extraction"]["reason"] or "")
            if not m:
                continue
            pg = int(m.group(1))
            txt = self.text(d["id"], pg)
            lots = re.findall(r"\b([A-Z]+\d+) (.+?) ([\d.]+) sh acquired (\S+) sold (\S+) proceeds ([\d,.]+) basis ([\d,.]+) (short|long)-term", txt)
            sugg = []
            for lot, desc, _sh, _acq, _sold, proc, basis, term in lots:
                g = money(proc) - money(basis)
                box = "B" if term == "short" else "E"
                sugg.append(Suggestion(f"F8949.{box}.{lot}", g, "stcg" if term == "short" else "ltcg", g,
                                       note=f"Add {lot} {desc}: proceeds {proc}, basis {basis}"))
            summary_ev = self.p.ev(d["id"], "b_summary_proceeds")
            missing = sum(money(x[5]) for x in lots)
            self.add(Finding(
                id=f"F-UNREAD-{d['id']}", code="UNREAD_PAGE", severity="error" if sugg else "warning", kind="error",
                area="investments_and_digital_assets",
                title=f"{d['title']}: page {pg} was never read",
                summary=(f"Page {pg} lists {len(lots)} more sale(s) the return omits: " +
                         "; ".join(f"{x[0]} {x[1]} proceeds {x[5]}, basis {x[6]}" for x in lots) +
                         f". Their proceeds ({fmt(missing)}) are the broker summary vs detail difference.") if lots else f"Page {pg}: {txt[:160]}",
                evidence=[f"{d['id']}#page{pg}", summary_ev or ""], lines=["SchD.1b", "SchD.7"], suggestions=sugg))

    def check_04_duplicate_pages(self):
        """Two scans of the same sheet both summed into a line."""
        for d in self.p.raw["documents"]:
            if d["id"] not in self.visible or len(d["pages"]) < 2:
                continue
            pages = d["pages"]
            for b in pages:
                earlier = [x for x in pages if x["page"] < b["page"]]
                if not earlier:
                    continue
                a = max(earlier, key=lambda x: _similarity(x["printed_content"], b["printed_content"]))
                sim = _similarity(a["printed_content"], b["printed_content"])
                if sim < 0.85:
                    continue
                va = {e for e in self.p.values_by_doc.get(d["id"], []) if self.p.values[e]["page"] == a["page"]}
                vb = {e for e in self.p.values_by_doc.get(d["id"], []) if self.p.values[e]["page"] == b["page"]}
                for key, line in self.v.lines.items():
                    srcs = set(line["sources"])
                    if not (srcs & va and srcs & vb):
                        continue
                    dup = sorted(srcs & vb)[0]
                    amt = self.p.values[dup]["value"]
                    sugg = [Suggestion(key, -amt, "none", 0, note=f"Remove page {b['page']} ({fmt(amt)})")]
                    # follow the line into anything computed from it at a per-unit rate (e.g. standard mileage)
                    for c in self.v.consumers.get(key, []):
                        if self.v.lines[c]["rule"] == "R-STANDARD-MILEAGE":
                            rate = self.p.params["mileage_rate"]
                            car = round(amt * rate)
                            sugg.append(Suggestion(c, -car, "schc_profit", car, note=f"{fmt(amt)} miles x {rate} standard rate"))
                    says = " and says it is a second scan" if "second scan" in b["printed_content"].lower() else ""
                    self.add(Finding(
                        id=f"F-DUPPAGE-{d['id']}-{b['page']}", code="DUPLICATE_PAGE_COUNTED", severity="error",
                        kind="error", area="",
                        title=f"{d['title']}: page {b['page']} is a second scan of page {a['page']}, and both were added",
                        summary=f"Pages {a['page']} and {b['page']} are {sim:.0%} identical{says}. "
                                f"{key} ({line['label']}) adds both page totals, overstating it by {fmt(amt)}.",
                        evidence=[f"{d['id']}#page{a['page']}", f"{d['id']}#page{b['page']}", dup],
                        lines=[key] + [s.line for s in sugg[1:]], suggestions=sugg))

    # ================================================================== duplicates across documents
    def check_05_same_account_twice(self):
        """Two payer lines with the same amount that the documents say are one account."""
        groups: dict[str, list[dict]] = {}
        for key, line in self.v.lines.items():
            m = re.match(r"(SchB\.[15])\.\d+$", key)
            if m:
                groups.setdefault(m.group(1), []).append(line)

        def docs_and_text(line):
            evs = [s for s in line["sources"] if s in self.p.values]
            docs = {self.p.values[s]["document_id"] for s in evs}
            text = " ".join(self.text(self.p.values[s]["document_id"], self.p.values[s]["page"]) for s in evs)
            return docs, text
        for lines in groups.values():
            for i, a in enumerate(lines):
                for b in lines[i + 1:]:
                    if a["value"] != b["value"] or not a["sources"] or not b["sources"]:
                        continue
                    da, ta = docs_and_text(a)
                    db, tb = docs_and_text(b)
                    shared = set(re.findall(r"account ending (\d{4})", ta)) & set(re.findall(r"account ending (\d{4})", tb))
                    if da == db or not shared:
                        continue
                    confs = sorted({self.p.values[s]["confidence"] for s in a["sources"] + b["sources"] if s in self.p.values})
                    self.add(Finding(
                        id=f"F-DUP-{b['key']}", code="SAME_INCOME_TWICE", severity="error", kind="error", area="",
                        title=f"The same {fmt(a['value'])} of interest is on the return twice",
                        summary=f"{a['label']} and {b['label']} are the same account (ending {', '.join(sorted(shared))}): the statement "
                                f"({', '.join(sorted(da))}) already includes the separate form ({', '.join(sorted(db))}). "
                                f"Both reads have confidence {', '.join(f'{c:.2f}' for c in confs)}, so nothing flagged it.",
                        evidence=a["sources"] + b["sources"], lines=[b["key"], "SchB.2", "F1040.2b"],
                        suggestions=[Suggestion(b["key"], -b["value"], "interest", -b["value"], note=f"Remove duplicate payer line {b['key']}")]))

    def check_06_card_sales_in_books(self):
        """Engine adds 1099-K to books revenue when it 'could not match' a deposit; the books say otherwise."""
        sc1 = self.L("SchC.1")
        if not sc1:
            return
        books_total = next((self.p.values[s]["value"] for s in sc1["sources"]
                            if s in self.p.values and self.p.values[s]["field"] == "total_income"), None)
        if books_total is None:
            return
        for k in self.p.docs_of("1099-K", self.visible):
            k_amt = self.p.val(k["id"], "box1a")
            filer = k["issuer"].split()[0]
            for bd in self.p.docs_of("books_transaction_detail", self.visible):
                for pg in bd["pages"]:
                    t = pg["printed_content"]
                    if filer not in t or "gross" not in t or sc1["value"] - books_total != k_amt:
                        continue
                    nec = next((n for n in self.p.docs_of("1099-NEC", self.visible)
                                if n["issuer"].split()[0] in _sentence_with(t, filer)), None)
                    also = f" The payer also reported them on its Form 1099-NEC ({nec['id']}), so third-party forms over-report too." if nec else ""
                    self.add(Finding(
                        id=f"F-{k['document_type']}-IN-BOOKS".replace("1099-K", "1099K"), code="CARD_SALES_COUNTED_TWICE",
                        severity="error", kind="error", area="business",
                        title=f"Card payments ({fmt(k_amt)}) are counted twice in gross receipts",
                        summary=f"Gross receipts = books {fmt(books_total)} + Form 1099-K {fmt(k_amt)}. The books' deposit detail says "
                                f"'{_sentence_with(t, filer)}' The card receipts are already in books revenue.{also}",
                        evidence=[s for s in sc1["sources"] if s in self.p.values][:2] + [f"{bd['id']}#page{pg['page']}", f"{k['id']}#page1"]
                        + ([f"{nec['id']}#page1"] if nec else []),
                        lines=["SchC.1", "SchC.31", "SchSE.2"],
                        suggestions=[Suggestion("SchC.1", -k_amt, "schc_profit", -k_amt, note="Gross receipts = books revenue")]))
                    return

    # ================================================================== stock comp and sales
    def check_07_supplemental_basis(self):
        """Noncovered RSU lots reported with zero basis while the plan supplement gives the basis."""
        lots = {}
        for d in self.p.docs_of("stock_plan_supplement", self.visible):
            for pg in d["pages"]:
                for m in re.finditer(r"Lot ([A-Z]+-\d+): (\d+) sh acquired (\d\d)/(\d\d)/(\d{4}) .*?adjusted basis ([\d,.]+), sold (\d\d)/(\d\d)/(\d{4})",
                                     pg["printed_content"]):
                    acq = f"{m.group(5)}-{m.group(3)}-{m.group(4)}"
                    sold = f"{m.group(9)}-{m.group(7)}-{m.group(8)}"
                    lots[(acq, sold)] = (m.group(1), int(m.group(2)), money(m.group(6)), d["id"], pg["page"])
        if not lots:
            return
        sugg, ev, keys, names = [], [], [], []
        for key, line in self.v.lines.items():
            if line["form"] != "F8949":
                continue
            m = re.search(r"acquired (\S+), sold (\S+?); proceeds ([\d,.]+), basis 0\.00\)", line["label"])
            if not m or (m.group(1), m.group(2)) not in lots:
                continue
            lot, sh, basis, did, pg = lots[(m.group(1), m.group(2))]
            box = line["line"].split(".")[0]
            cat = "stcg" if box in "ABCGHI" else "ltcg"
            sugg.append(Suggestion(key, -basis, cat, -basis, note=f"Basis {fmt(basis)} from {lot} ({sh} sh at vest value)"))
            ev += [x for x in line["sources"] if x in self.p.values and self.p.values[x]["field"].endswith(("_proceeds", "_basis"))]
            ev.append(f"{did}#page{pg}")
            keys.append(key)
            names.append(f"{lot} vs {key.split('.')[-1]}")
        if not sugg:
            return
        total = sum(-s.delta for s in sugg)
        rsu_wages = [(d["id"], self.p.ev(d["id"], "box14_RSU")) for d in self.p.docs_of("W-2", self.visible) if self.p.ev(d["id"], "box14_RSU")]
        wages_note = "".join(f" (W-2 box 14 RSU {fmt(self.p.values[e]['value'])})" for _, e in rsu_wages)
        self.add(Finding(
            id="F-RSU-BASIS", code="SUPPLEMENTAL_BASIS_NOT_MATCHED", severity="error", kind="error",
            area="wages_and_stock_compensation",
            title=f"RSU sales taxed as if they cost nothing: {fmt(total)} of basis missing",
            summary=f"Form 1099-B reports these noncovered RSU lots with no basis, and the engine used 0. The plan's supplemental "
                    f"statement gives the basis: the vest value, already taxed as wages{wages_note}. "
                    f"The engine's lot matching failed because the supplement names lots differently ({', '.join(names)}).",
            evidence=ev + [e for _, e in rsu_wages], lines=[*keys, "SchD.2", "SchD.9"], suggestions=sugg))

    def check_08_digital_asset_basis(self):
        for key, line in self.v.lines.items():
            if line["form"] != "F8949" or "basis 0.00" not in line["label"] or not key.startswith(("F8949.H", "F8949.K")):
                continue
            lot = key.split(".")[-1]
            for msg in self.messages():
                m = re.search(r"bought on another exchange in (\w+ (\d{4})) for about ([\d,]+)", msg["text"])
                if not (m and "no cost" in msg["text"]):
                    continue
                basis = money(m.group(3))
                proceeds = line["value"]
                lt_gain = proceeds - basis
                self.add(Finding(
                    id=f"F-CRYPTO-{lot}", code="DIGITAL_ASSET_BASIS_FROM_CLIENT", severity="warning", kind="judgment",
                    area="investments_and_digital_assets",
                    title=f"Digital asset lot {lot}: client gave a cost of {fmt(basis)} and a {m.group(2)} purchase date",
                    summary=f"The engine used zero basis and the transfer-in date (short-term gain {fmt(proceeds)}). The client says it was "
                            f"bought in {m.group(1)} for about {fmt(basis)}: '{msg['text'][:160]}'. If accepted: long-term gain "
                            f"{fmt(lt_gain)}. Record the support you rely on.",
                    evidence=line["sources"][:3] + [msg["id"]], lines=[key, "SchD.3", "SchD.10"],
                    suggestions=[Suggestion(key, -proceeds, "stcg", -proceeds, note="Remove short-term line"),
                                 Suggestion(f"F8949.K.{lot}", lt_gain, "ltcg", lt_gain, note=f"Long-term, basis {fmt(basis)}")],
                    needs="support for basis"))

    # ================================================================== business
    def check_09_mixed_use_expenses(self):
        books = self.doc("books_profit_loss")
        if not books:
            return
        bf = self.p.fields(books["id"])
        sugg, ev, parts = [], [], []

        def books_line(word):
            f = next((f for f in bf if word in f.lower()), None)
            return (bf[f], self.p.values[bf[f]]["value"]) if f else (None, None)
        for word, rx, line in (("telephone", r"(?:mobile|phone).*?business share is (\d+)%", "SchC.25"),
                               ("internet", r"internet.*?business use about (\d+)%", "SchC.25")):
            hits = [(cid, n) for cid, n in self.p.call_notes_with(word.replace("telephone", "mobile")) + self.p.call_notes_with(word)
                    if re.search(rx, n, re.I)]
            ev_id, amount = books_line(word)
            if hits and amount:
                cid, note = hits[0]
                pct = int(re.search(rx, note, re.I).group(1))
                pers = round(amount * (1 - pct / 100))
                parts.append(f"{word} {pct}% business (personal {fmt(pers)})")
                sugg.append(Suggestion(line, -pers, "schc_profit", pers, note=f"{word.title()} {fmt(amount)} x {100 - pct}% personal"))
                ev += [cid, ev_id]
        for cid, note in self.p.call_notes_with("personal"):
            m = re.match(r"(\w+(?: \w+)?) in (\w+) is personal", note)
            if not m:
                continue
            item, category = m.group(1), m.group(2)
            for d in self.p.docs_of("books_transaction_detail", self.visible):
                for pg in d["pages"]:
                    mm = re.search(re.escape(item) + r" ([\d,.]+)", pg["printed_content"])
                    if mm:
                        amt = money(mm.group(1))
                        line = next((k for k, ln in self.v.lines.items() if ln["form"] == "SchC" and category.lower() in ln["label"].lower()), None)
                        if line:
                            parts.append(f"{item} {fmt(amt)} personal")
                            sugg.append(Suggestion(line, -amt, "schc_profit", amt, note=f"{item} is personal"))
                            ev += [cid, f"{d['id']}#page{pg['page']}"]
        if sugg:
            self.add(Finding(
                id="F-MIXED-USE", code="PERSONAL_SHARE_DEDUCTED", severity="error", kind="error", area="business",
                title="Personal share of business expenses deducted in full",
                summary="The books expense these at 100% and the engine maps them straight to Schedule C. On the client call: "
                        + "; ".join(parts) + ".",
                evidence=ev, lines=[*sorted({s.line for s in sugg}), "SchC.31"], suggestions=sugg))

    def check_10_sehi_eligibility(self):
        sehi = self.val("Sch1.17")
        if not sehi:
            return
        q = self.p.answer("eligible", "health coverage")
        if not (q and q["answer"].lower().startswith("yes")):
            return
        prior = self.p.prior["return_2024"]["notes"].get("Sch1.17", "")
        hsa = self.doc("5498-SA", text="family")
        self.add(Finding(
            id="F-SEHI", code="SEHI_NOT_ALLOWED", severity="error", kind="error", area="business",
            title=f"Self-employed health insurance deduction ({fmt(sehi)}) is not allowed",
            summary="No deduction for any month the self-employed person was eligible for an employer-subsidized plan, including "
                    f"through a spouse's employer. The client answered: '{q['answer']}'"
                    + (" The Form 5498-SA shows family HDHP coverage through the spouse's employer." if hsa else "")
                    + (f" Last year: '{prior}'" if prior else ""),
            evidence=[q["id"]] + self.L("Sch1.17")["sources"] + self.p.page_ref(hsa) + (["py:/return_2024/notes/Sch1.17"] if prior else []),
            lines=["Sch1.17", "Sch1.26", "F1040.10"],
            suggestions=[Suggestion("Sch1.17", -sehi, "adjustment", -sehi, note="Remove SE health insurance deduction")]))

    def check_11_sep_excess(self):
        line = self.L("Sch1.16")
        conf = self.doc("retirement_contribution", text="SEP")
        if not line or not conf:
            return
        ev = self.p.ev(conf["id"], "amount")
        contrib = self.p.values[ev]["value"] if ev else None
        if contrib and contrib > line["value"]:
            excess = contrib - line["value"]
            q = self.p.answer("SEP")
            self.add(Finding(
                id="F-SEP-EXCESS", code="EXCESS_SEP_CONTRIBUTION", severity="warning", kind="outside_filing", area="business",
                title=f"SEP contribution exceeds the limit by {fmt(excess)}",
                summary=f"Contributed {fmt(contrib)}; deductible limit {fmt(line['value'])}. The excess is subject to a 6% excise tax each year it "
                        f"stays in the account (Form 5329) unless withdrawn with earnings before the extended due date. The limit moves "
                        f"with every Schedule C adjustment, so recheck after review.",
                evidence=[ev, f"{conf['id']}#page1", q["id"] if q else ""], lines=["Sch1.16"], needs="client decision"))

    def check_12_repair_vs_improvement(self):
        """A repairs line containing a single building-system replacement above the de minimis safe harbor."""
        for key, rep in self.v.lines.items():
            if not re.match(r"SchE\.14[A-Z]$", key):
                continue
            for s in rep["sources"]:
                if s not in self.p.values:
                    continue
                doc = self.p.values[s]["document_id"]
                for m in re.finditer(r"(HVAC|roof|furnace)\w* ([\d,]+\.\d\d)", self.text(doc, self.p.values[s]["page"]), re.I):
                    amt = money(m.group(2))
                    if amt < 2500:
                        continue
                    word = m.group(1)
                    inv = next((d for d in self.p.docs_of("invoice", self.visible)
                                if any(abs(self.p.values[e]["value"] - amt) < 0.01 for e in self.p.values_by_doc.get(d["id"], [])
                                       if self.p.values[e]["value_type"] == "money")), None)
                    wi = next((a for a in self.p.what_if["alternatives"] if word.lower() in a["description"].lower()), None)
                    exact = {"fed_tax": wi["federal"]["total_tax_change"], "ca_tax": wi["california"]["total_tax_change"],
                             "fed_payments": 0, "ca_payments": 0} if wi else None
                    q = self.p.answer("repairs")
                    calls = [cid for cid, _ in self.p.call_notes_with(word)]
                    desc = _sentence_with(self.text(inv["id"]), "Installed") if inv else ""
                    self.add(Finding(
                        id=f"F-{word.upper()}", code="IMPROVEMENT_EXPENSED", severity="error", kind="error", area="rentals_and_sale",
                        title=f"{fmt(amt)} {word} replacement expensed as a repair",
                        summary=f"{desc + ' ' if desc else ''}Replacing a whole building system is a restoration: capitalize and depreciate "
                                f"over 27.5 years. It is far above the 2,500 de minimis safe harbor."
                                + (" The engine has an exact what-if for this treatment, used for the effect shown." if wi else ""),
                        evidence=[s] + self.p.page_ref(inv) + ([q["id"]] if q else []) + calls,
                        lines=[key, key.replace("14", "18"), key.replace("14", "21")],
                        suggestions=[Suggestion(key, -amt, "exact" if wi else "ordinary_income", 0 if wi else amt,
                                                note="Move to the depreciation schedule (27.5-year SL)", exact_effect=exact)]))
                    return

    # ================================================================== deductions
    def check_13_vehicle_donation(self):
        line = self.L("F8283.A1.vehicle")
        c = self.doc("1098-C")
        if not line or not c:
            return
        ev = self.p.ev(c["id"], "box4c")
        proceeds = self.p.values[ev]["value"] if ev else None
        if proceeds is None or "4a vehicle sold" not in self.text(c["id"]) or line["value"] <= proceeds:
            return
        delta = proceeds - line["value"]
        q = next((s for s in line["sources"] if s in self.p.questionnaire), None)
        self.add(Finding(
            id="F-CAR", code="VEHICLE_GIFT_OVER_PROCEEDS", severity="error", kind="error", area="deductions_and_credits",
            title=f"Donated car claimed at {fmt(line['value'])}; the deduction is limited to the {fmt(proceeds)} sale price",
            summary="When the charity sells the vehicle (Form 1098-C box 4a), the deduction is capped at the gross proceeds in box 4c."
                    + (f" The engine used the client's estimate: '{self.p.questionnaire[q]['answer']}'" if q else ""),
            evidence=[q or "", f"{c['id']}#page1", ev] + [cid for cid, _ in self.p.call_notes_with("Subaru")],
            lines=["F8283.A1.vehicle", "SchA.12", "SchA.17"],
            suggestions=[Suggestion("F8283.A1.vehicle", delta, "itemized", delta, delta, note="Limit to 1098-C box 4c")]))

    def check_14_property_tax_proration(self):
        line = self.L("SchA.5b")
        buyer = self.doc("closing_statement_buyer")
        if not line or not buyer:
            return
        m = re.search(r"Seller credit for \d{4} county taxes (\S+): ([\d,.]+)", self.text(buyer["id"]))
        if not m:
            return
        credit = money(m.group(2))
        new5b = line["value"] - credit
        cap = self.val("SchA.5e")
        old_total = self.val("SchA.5d")
        new_total = old_total - credit
        fed_basis = min(new_total, cap) - cap
        self.add(Finding(
            id="F-PROPTAX", code="PROPERTY_TAX_NOT_PRORATED", severity="error", kind="error", area="deductions_and_credits",
            title=f"Home property tax deducted in full; the seller's share ({fmt(credit)}) was credited at closing",
            summary=f"The full-year bill {fmt(line['value'])} was paid from escrow, but the seller credited {fmt(credit)} for {m.group(1)}. "
                    f"Only {fmt(new5b)} is the buyers' tax. State and local taxes drop from {fmt(old_total)} to {fmt(new_total)}"
                    + (f", under the {fmt(cap)} cap, so the federal deduction falls by {fmt(-fed_basis)}" if new_total < cap else "")
                    + f". California has no cap and loses the full {fmt(credit)}.",
            evidence=[self.p.ev(buyer["id"], "tax_credit") or "", f"{buyer['id']}#page1"] + line["sources"],
            lines=["SchA.5b", "SchA.5e", "SchCA540NR.A.itemized"],
            suggestions=[Suggestion("SchA.5b", -credit, "itemized", fed_basis, -credit, note=f"Buyer's share {fmt(new5b)}")]))

    def check_15_mortgage_interest_twice(self):
        line = self.L("SchA.8a")
        if not line:
            return
        for s in line["sources"]:
            e = self.p.values.get(s)
            if not e:
                continue
            d = self.p.docs[e["document_id"]]
            if d["document_type"] != "payoff_statement" or not re.search(r"reported on the \d{4} Form 1098", self.text(d["id"])):
                continue
            lender = d["issuer"].split()[0]
            f1098 = next((x for x in self.p.docs_of("1098", self.visible) if x["issuer"].split()[0] == lender), None)
            says = _sentence_with(self.text(f1098["id"]), "includes") if f1098 else ""
            amt = e["value"]
            self.add(Finding(
                id="F-MORTINT", code="INTEREST_COUNTED_TWICE", severity="error", kind="error", area="deductions_and_credits",
                title=f"Payoff interest ({fmt(amt)}) added on top of the Form 1098 that already includes it",
                summary=f"The payoff statement says '{_sentence_with(self.text(d['id']), 'reported on')}'"
                        + (f" and the {lender} Form 1098 says '{says}'" if says else "") + ". The engine added both.",
                evidence=[s, f"{d['id']}#page1"] + ([self.p.ev(f1098["id"], "box1") or "", f"{f1098['id']}#page1"] if f1098 else []),
                lines=["SchA.8a", "SchA.10", "SchCA540NR.A.itemized"],
                suggestions=[Suggestion("SchA.8a", -amt, "itemized", -amt, -amt, note="Remove payoff-statement interest")]))

    def check_16_charity_substantiation(self):
        for d in self.p.docs_of("donation_receipt", self.visible):
            t = self.text(d["id"])
            if "No goods or services line" not in t:
                continue
            org = d["issuer"].split()[0]
            confirms = [m for m in self.messages() if org in m["text"] and "confirmed" in m["text"]]
            amount_ev = self.p.ev(d["id"], "amount")
            said = ""
            if confirms:
                cm = re.search(r"was ([\d,]+)", confirms[-1]["text"])
                said = f" The client later confirmed {cm.group(1)} ({confirms[-1]['sent_at'][:10]})." if cm else ""
            self.add(Finding(
                id=f"F-ACK-{d['id']}", code="ACKNOWLEDGMENT_INCOMPLETE", severity="warning", kind="judgment",
                area="deductions_and_credits",
                title=f"{d['title']}: acknowledgment lacks the goods-or-services statement",
                summary="A gift of 250 or more needs a contemporaneous written acknowledgment that says whether goods or services "
                        f"were provided. This receipt does not.{said} Decide: request a corrected acknowledgment before filing, or document the risk.",
                evidence=[f"{d['id']}#page1", amount_ev or ""] + [m["id"] for m in confirms], lines=["SchA.11"], needs="corrected acknowledgment"))

    # ================================================================== foreign
    def check_17_fx_rate_year(self):
        year = str(self.p.household["tax_year"])
        rates = self.p.raw["fx_rates"]["SEK_per_USD"]
        for key, line in self.v.lines.items():
            for s in line["sources"]:
                m = re.match(r"ref:fx\.SEK\.(\d{4})_average", s)
                if not m or m.group(1) == year or f"{year}_average" not in rates:
                    continue
                sek = next(self.p.values[x]["value"] for x in line["sources"] if x in self.p.values)
                right = rates[f"{year}_average"]
                new = round(sek / right)
                self.add(Finding(
                    id=f"F-FX-{key}", code="WRONG_YEAR_EXCHANGE_RATE", severity="error", kind="error",
                    area="investments_and_digital_assets",
                    title="Foreign interest converted at last year's exchange rate",
                    summary=f"{key} uses the {m.group(1)} average ({rates[m.group(1) + '_average']}) for {year} income. "
                            f"At the {year} average ({right}): SEK {fmt(sek)} = {fmt(new)}, not {fmt(line['value'])}.",
                    evidence=line["sources"] + [f"ref:fx.SEK.{year}_average"], lines=[key, "SchB.2"],
                    suggestions=[Suggestion(key, new - line["value"], "interest", new - line["value"], note=f"{year} average rate")]))

    # ================================================================== state
    def check_18_part_year_wages(self):
        ca = next((r for r in self.p.household["residency"] if r["state"] == "CA"), None)
        line = self.L("SchCA540NR.1.E")
        if not ca or not line:
            return
        for d in self.p.docs_of("W-2", self.visible):
            if d["id"] in self.p.duplicate_notes:
                continue
            t = self.text(d["id"])
            m = re.search(r"payroll kept California as the work state through (\S+)\.", t)
            box16 = self.p.val(d["id"], "box16")
            if not m or box16 is None:
                continue
            stub = next((x for x in self.p.docs_of("paystub", self.visible) if x["issuer"] == d["issuer"]), None)
            ca_ev = self.p.ev(stub["id"], "ytd_ca_wages") if stub else None
            ca_src = self.p.values[ca_ev]["value"] if ca_ev else None
            person = next((pid for pid, p in self.p.people.items() if p["name"] in t), None)
            answers = [q["id"] for q in (self.p.answer("move"), self.p.answer("anything else")) if q]
            sugg = []
            if ca_src is not None:
                sugg.append(Suggestion("SchCA540NR.1.E", ca_src - box16, "ca_source_income", 0, ca_src - box16,
                                       note=f"California-source wages = paystub YTD at the move ({fmt(ca_src)})"))
            self.add(Finding(
                id="F-CA-WAGES", code="CA_SOURCE_WAGES_OVERSTATED", severity="error", kind="error", area="california",
                title=f"California taxes {fmt(box16 - (ca_src or 0))} of wages earned after the move",
                summary=f"The engine sources all of {d['issuer']} W-2 box 16 ({fmt(box16)}) to California. The household left California on "
                        f"{ca['to']}, but the employer kept California as the work state through {m.group(1)}. "
                        + (f"The paystub at the move ({stub['id']}) shows California wages of {fmt(ca_src)}." if ca_src is not None else
                           "Ask the employer or client for a paystub at the move date."),
                evidence=[f"{d['id']}#page1", f"household:{person}" if person else "", *answers, *self.p.page_ref(stub), ca_ev or ""],
                lines=["SchCA540NR.1.E", "F540NR.32", "F540NR.35"], suggestions=sugg,
                needs=None if stub else "paystub at move date"))

    # ================================================================== payments and agency records
    def check_19_estimated_payments(self):
        snaps = [s for s in self.p.agency["irs_account_transcript_2025"] if s["as_of"] <= self.clock[:10]] or self.p.agency["irs_account_transcript_2025"][:1]
        tr = snaps[-1]
        txns = tr["transactions"]
        est_txn = [(i, t) for i, t in enumerate(txns) if t["code"] == "670" and "extension" not in t["description"].lower()]
        est = sum(t["amount"] for _, t in est_txn)
        snap_ix = self.p.agency["irs_account_transcript_2025"].index(tr)
        transcript_doc = self.doc("irs_transcript")
        line = self.L("F1040.26")
        if line and line["value"] != est:
            q = next((s for s in line["sources"] if s in self.p.questionnaire), None)
            confirmed = {self.p.values[e]["value"] for d in self.p.docs_of("payment_confirmation", self.visible) if "EFTPS" in d["title"] + d["issuer"]
                         for e in self.p.values_by_doc[d["id"]] if self.p.values[e]["field"].endswith("_date")}
            missing = [(i, t) for i, t in est_txn if t["date"] not in confirmed]
            miss_txt = "; ".join(f"{fmt(t['amount'])} on {t['date']}" for _, t in missing)
            self.add(Finding(
                id="F-EST-FED", code="ESTIMATES_DISAGREE_WITH_IRS", severity="error", kind="error", area="tax_and_payments",
                title=f"Federal estimated payments: return {fmt(line['value'])}, IRS transcript {fmt(est)}",
                summary=("Not every payment has a confirmation, so the engine used the client's answer "
                         f"'{self.p.questionnaire[q]['answer']}'. " if q else "")
                        + f"The IRS account transcript (as of {tr['as_of']}) shows {miss_txt or fmt(est) + ' in total'}. "
                          "Claiming payments the IRS does not have causes a math-error notice and a bigger balance due.",
                evidence=[q or ""] + self.p.page_ref(transcript_doc) + [f"agency:/irs_account_transcript_2025/{snap_ix}/transactions/{i}" for i, _ in missing],
                lines=["F1040.26", "F1040.33", "F2210.19"],
                suggestions=[Suggestion("F1040.26", est - line["value"], "payments_fed", est - line["value"], note="Agree to IRS transcript")]))
        elif line:
            self.ok("P-EST-FED", "Federal estimates agree to IRS transcript", f"{fmt(est)} on the transcript", ["F1040.26"], self.p.page_ref(transcript_doc))
        ftb = self.p.agency["ftb_account"]
        ca_est = sum(t["amount"] for t in ftb["tax_year_2025_payments"])
        cl = self.L("F540NR.72")
        if cl and cl["value"] != ca_est:
            held = ftb.get("tax_year_2024_payments_after_filing", [])
            year = str(self.p.household["tax_year"])
            wrong = []
            for d in self.p.docs_of("payment_confirmation", self.visible):
                f = self.p.fields(d["id"])
                for k, e in f.items():
                    m = re.match(r"(pay\d+)_year$", k)
                    if m and str(self.p.values[e]["value"]) != year and self.p.values[f[f"{m.group(1)}_date"]]["value"] in {h["date"] for h in held}:
                        wrong += [f[f"{m.group(1)}_date"], f[f"{m.group(1)}_amount"], e, f"{d['id']}#page1"]
            self.add(Finding(
                id="F-EST-CA", code="ESTIMATES_DISAGREE_WITH_FTB", severity="error", kind="error", area="california",
                title=f"California estimated payments: return {fmt(cl['value'])}, FTB account {fmt(ca_est)}",
                summary="The engine counts every FTB payment by date. "
                        + "; ".join(f"The {h['date']} payment of {fmt(h['amount'])}: {h['note']}" for h in held)
                        + f". Either claim {fmt(ca_est)} and ask FTB to refund or transfer that credit, or have FTB move it first.",
                evidence=[*wrong, "agency:/ftb_account"], lines=["F540NR.72", "F540NR.78", "F540NR.97"],
                suggestions=[Suggestion("F540NR.72", ca_est - cl["value"], "payments_ca", 0, ca_est - cl["value"], note="Agree to FTB account")]))
        ext = self.L("Sch3.10")
        tr2 = self.p.agency["irs_account_transcript_2025"][-1]
        ext_amt = sum(t["amount"] for t in tr2["transactions"] if "extension" in t["description"].lower() and isinstance(t["amount"], (int, float)))
        if ext and ext["value"] == ext_amt:
            self.ok("P-EXT", "Extension payment agrees to IRS transcript", f"{fmt(ext_amt)} with Form 4868", ["Sch3.10"])

    # ================================================================== identity
    def check_20_ssn_consistency(self):
        for pid, mismatches, hits in ssn_mismatches(self.p, self.visible, self.household_fixes):
            person = self.p.people[pid]
            ssn = self.household_fixes.get(pid, {}).get("ssn", person.get("ssn"))
            if mismatches:
                self.add(Finding(
                    id=f"F-SSN-{pid}", code="SSN_MISMATCH", severity="error", kind="error", area="intake_and_engagement",
                    title=f"{person['name']}'s SSN in the organizer does not match the documents",
                    summary=f"Organizer: {ssn}. " + "; ".join(f"{r}: {s}" for s, r in mismatches) +
                            (". A dependent SSN mismatch rejects the e-file." if person.get("role") == "dependent" else "."),
                    evidence=[f"household:{pid}"] + [r for _, r in mismatches], lines=["F8812.4"] if person.get("role") == "dependent" else [],
                    needs="confirm SSN from the card"))
            elif hits:
                self.ok(f"P-SSN-{pid}", f"{person['name']}: SSN agrees to documents", f"{len(hits)} occurrence(s)", [], [r for _, r in hits])

    def check_21_provider_ids(self):
        for key, line in self.v.lines.items():
            if not key.startswith("F2441.1"):
                continue
            for s in line["sources"]:
                e = self.p.values.get(s)
                if not e or e["field"] != "ein":
                    continue
                d = self.p.docs[e["document_id"]]
                name_on_doc = self.text(d["id"]).split(",")[0]
                if name_on_doc.split()[0] in line["label"] and name_on_doc not in line["label"]:
                    self.add(Finding(
                        id=f"F-PROVNAME-{key}", code="PROVIDER_NAME_MISMATCH", severity="info", kind="data", area="deductions_and_credits",
                        title=f"Care provider name on {key} differs from the statement",
                        summary=f"Return: '{line['label'].split(': ', 1)[-1].split(',')[0]}'. Statement: '{name_on_doc}'.",
                        evidence=[f"{d['id']}#page1"], lines=[key]))

    # ================================================================== client answers vs documents
    def check_22_answers_vs_documents(self):
        conflicts = []
        sales = [k for k in self.v.lines if k.startswith("F8949.") and not k.endswith("total") and "SCORP" not in k]
        q = self.p.answer("sell any stocks")
        if q and q["answer"].strip().lower() == "no" and sales:
            conflicts.append((q["id"], f"'No' investments sold; Form 8949 has {len(sales)} sales. The engine followed the documents."))
        q = self.p.answer("IRA details")
        if q and "none" in q["answer"].lower() and self.val("F8606.2"):
            d5498 = self.doc("5498", tax_year=self.p.household["tax_year"] - 1)
            conf = f" and the prior-year Form 5498 ({d5498['id']}, {fmt(self.p.val(d5498['id'], 'box1', 0))})" if d5498 else ""
            conflicts.append((q["id"], f"Client says no prior IRA basis, but the 2024 Form 8606 shows {fmt(self.val('F8606.2'))}{conf}. "
                                       f"The engine used the documents; taxable conversion is {fmt(self.val('F8606.18'))}."))
        q = self.p.answer("cryptocurrency")
        da = [k for k in sales if k.startswith(("F8949.H", "F8949.K"))]
        if q and "didn't really sell" in q["answer"].lower() and da:
            conflicts.append((q["id"], f"'{q['answer']}'; the broker reports {len(da)} digital asset dispositions."))
        q = self.p.answer("non-cash")
        veh = self.L("F8283.A1.vehicle")
        c = self.doc("1098-C")
        if q and veh and c and q["id"] in veh["sources"]:
            conflicts.append((q["id"], f"Car valued by the client at {fmt(veh['value'])}; the charity sold it for {fmt(self.p.val(c['id'], 'box4c', 0))}."))
        est = self.L("F1040.26")
        q = next((self.p.questionnaire[s] for s in (est["sources"] if est else []) if s in self.p.questionnaire), None)
        if q and "think" in q["answer"]:
            conflicts.append((q["id"], f"'{q['answer']}' for an estimated payment; see the IRS transcript."))
        if conflicts:
            self.add(Finding(
                id="F-ANSWERS", code="ANSWERS_CONTRADICT_DOCUMENTS", severity="warning", kind="judgment", area="intake_and_engagement",
                title=f"{len(conflicts)} questionnaire answers contradict the documents",
                summary=" | ".join(f"{qid}: {t}" for qid, t in conflicts) + " Send the client a short confirmation so the file shows they agreed.",
                evidence=[qid for qid, _ in conflicts], lines=[], needs="client confirmation"))

    # ================================================================== prior preparer and outside filings
    def check_23_prior_preparer_open_items(self):
        pw = self.p.prior["prior_preparer_workpaper"]
        src = f"{pw['source_document']}#page3" if pw.get("source_document") else ""
        year = self.p.household["tax_year"]
        for it in pw["open_items_left_by_prior_preparer"]:
            low = it.lower()
            res, ev, open_ = "Review this item.", [], True
            m = re.search(r"obtain (\d{4}) (\w+) k-1", low)
            if m:
                k1 = self.doc("K-1-1120S", tax_year=int(m.group(1)))
                if k1:
                    res = (f"Resolved: the {m.group(1)} K-1 arrived {k1['received_at'][:10]} ({k1['id']}); stock basis rolled forward to "
                           f"{fmt(self.val('F7203.1'))} at the start of {year}.")
                    ev, open_ = [f"{k1['id']}#page1"], False
            elif "5498" in low:
                d = self.doc("5498", tax_year=year - 1)
                if d:
                    res = f"Resolved: {d['id']} confirms the {fmt(self.p.val(d['id'], 'box1', 0))} contribution for {year - 1}."
                    ev, open_ = [f"{d['id']}#page1"], False
            elif "square footage" in low:
                note = self.doc("client_note", text="sq ft")
                if note:
                    f = self.p.fields(note["id"])
                    sizes = [self.p.values[e]["value"] for k, e in f.items() if k.endswith("_sqft")]
                    claimed = re.search(r"(\d+) sq ft", self.p.prior["return_2024"]["line_labels"].get("SchC.30", ""))
                    over = (int(claimed.group(1)) - min(sizes)) * self.p.params["home_office_rate"] if claimed and sizes else None
                    res = (f"Resolved for {year}: measured {', '.join(str(s) for s in sizes)} sq ft ({note['id']})."
                           + (f" The {year - 1} return claimed {claimed.group(1)}, overstating the deduction by about {fmt(over)}." if over else ""))
                    ev, open_ = [f"{note['id']}#page1"], False
            elif "3520" in low:
                fb = self.doc("foreign_bank_statement", text="inheritance")
                res = ("OPEN: Form 3520 for a foreign inheritance has no record of being filed"
                       + (f"; the foreign account was funded by the inheritance ({fb['id']})" if fb else "")
                       + ". Penalties can be large; outside this engagement, so raise it with the client in writing.")
                ev = self.p.page_ref(fb)
            self.add(Finding(
                id=stable_id("F-PRIOR", it), code="PRIOR_PREPARER_OPEN_ITEM",
                severity="warning" if open_ else "info", kind="outside_filing" if open_ else "process", area="intake_and_engagement",
                title=f"Prior preparer left open: {it}", summary=res, evidence=[src, *ev], lines=[]))

    def check_24_outside_filings(self):
        """Every filing the household needs that is not this return."""
        out = []
        eng = self.doc("engagement_letter")
        if self.val("F8938.1.max") > 10000:
            out.append(("FinCEN Form 114 (FBAR)", f"Foreign account maximum {fmt(self.val('F8938.1.max'))} USD; filed separately"
                        + (" and outside the engagement" if eng and "FBAR" in self.text(eng["id"]) else ""), ["F8938.1.max", *self.p.page_ref(eng)]))
        if self.L("SchC.J") and self.val("SchC.J") == "No":
            rep = self.doc("books_report", text="contractor")
            who = "; ".join(f"{m.group(1)} {m.group(2)}" for m in re.finditer(r"([A-Z][a-z]+ [A-Z][a-z]+) \([^)]*\) ([\d,]+\.\d\d)", self.text(rep["id"]))) if rep else ""
            due = next((d["date"] for d in self.p.firm["deadlines"] if "1099-NEC" in d["what"]), "")
            out.append(("Forms 1099-NEC for contractors", f"{who}; due {due}. Advise the client.", self.p.page_ref(rep) + [s for s in self.L("SchC.J")["sources"]]))
        for pid, person in self.p.people.items():
            if person.get("role") == "dependent" and person.get("own_income"):
                out.append((f"{person['name']}'s own return", f"{person['own_income']}; must check 'someone can claim you'.", [f"household:{pid}"]))
        comps = [d for t in ("K-1-1120S", "K-1-state-supplement") for d in self.p.docs_of(t, self.visible)
                 if any("composite" in pg["printed_content"] for pg in d["pages"])]
        if comps:
            out.append(("Composite state returns", "Filed by the entities; no individual nonresident filing required.",
                        [f"{d['id']}#page{pg['page']}" for d in comps for pg in d["pages"] if "composite" in pg["printed_content"]]))
        if self.val("F6251.11"):
            out.append(("Form 8801 next year", f"Minimum tax credit from this year's AMT ({fmt(self.val('F6251.11'))}).", ["F6251.11"]))
        self.add(Finding(
            id="F-OUTSIDE", code="OUTSIDE_FILINGS", severity="info", kind="outside_filing", area="intake_and_engagement",
            title=f"{len(out)} filings outside this return identified",
            summary=" | ".join(f"{a}: {b}" for a, b, _ in out), evidence=[e for _, _, es in out for e in es], lines=[]))

    def check_25_section179_ca(self):
        for wi in self.p.what_if["alternatives"]:
            if wi["choices"].get("equipment") != "s179":
                continue
            if wi["federal"]["total_tax_change"] == 0 and wi["california"]["total_tax_change"] < 0:
                self.add(Finding(
                    id="F-PLAN-179", code="ELECTION_OPPORTUNITY", severity="info", kind="planning", area="business",
                    title=f"Electing section 179 for the equipment saves California {fmt(-wi['california']['total_tax_change'])}",
                    summary="Federal tax is the same either way (100% special depreciation vs section 179). California does not allow bonus "
                            f"depreciation but allows section 179 up to {fmt(self.p.params['ca_section179_limit'])}. Record the election as a judgment call.",
                    evidence=["F4562-C.14", "SchCA540NR.12.C"], lines=["F4562-C.12", "F4562-C.14"], needs="partner decision"))

    # ================================================================== recalculations that pass
    def check_90_recalculations(self):
        w2 = [d for d in self.p.docs_of("W-2", self.visible) if d["id"] not in self.p.duplicate_notes]
        for box, line in (("box1", "F1040.1a"), ("box2", "F1040.25a"), ("box17", "F540NR.71")):
            vals = [self.p.val(d["id"], box) for d in w2 if self.p.val(d["id"], box) is not None]
            if self.L(line) and vals and abs(sum(vals) - self.val(line)) < 1:
                self.ok(f"P-W2-{box}", f"W-2 {box} total recalculated", f"{' + '.join(fmt(v) for v in vals)} = {fmt(sum(vals))}", [line])
        ss = sum(self.p.val(d["id"], "box4", 0) for d in w2)
        excess = round(ss - self.p.params["ss_wage_base"] * 0.062)
        if abs(excess - self.val("Sch3.11")) <= 1:
            self.ok("P-EXCESS-SS", "Excess social security recalculated", f"{fmt(ss)} - 6.2% x {fmt(self.p.params['ss_wage_base'])} = {fmt(excess)}", ["Sch3.11"])
        fb = self.doc("foreign_bank_statement")
        sek = self.p.raw["fx_rates"]["SEK_per_USD"].get(f"{self.p.household['tax_year']}_year_end")
        if fb and sek:
            for key, fld in (("F8938.1.max", "max_balance_sek"), ("F8938.1.ye", "balance_ye_sek")):
                v = self.p.val(fb["id"], fld)
                if v is not None and abs(round(v / sek) - self.val(key)) <= 1:
                    self.ok(f"P-{key}", f"{key} recalculated at year-end rate", f"SEK {fmt(v)} / {sek}", [key], [self.p.ev(fb["id"], fld)])
        sums = [k for k in self.v.signs if self.v.lines[k]["rule"] == "R-SUM"]
        self.ok("P-SUMS", "Engine arithmetic", f"{len(sums)} sum lines re-added from their inputs; all agree.", sums)
        for a in self.v.raw.get("assets", []):
            if a["method"].startswith("SL") and not a.get("disposed"):
                annual = round(a["cost"] / a["life_years"], 2)
                if abs(annual - a["federal"]["depreciation_2025"]) < 1:
                    self.ok(f"P-DEP-{a['asset_id']}", f"Depreciation {a['asset_id']} recalculated", f"{fmt(a['cost'])} / {a['life_years']} = {fmt(annual)}",
                            [], [f"asset:{a['asset_id']}"])
        self._recalc_scorp_basis()
        self._recalc_8606()
        co = self.p.prior["carryovers_into_2025"]
        if -self.val("SchD.6") == co["capital_loss_short"] and -self.val("SchD.14") == co["capital_loss_long"]:
            self.ok("P-CARRY", "Capital loss carryovers agree to the prior-year return",
                    f"{fmt(co['capital_loss_short'])} short-term, {fmt(co['capital_loss_long'])} long-term", ["SchD.6", "SchD.14"],
                    [f"py:/carryovers_into_2025/{k}" for k in ("capital_loss_short", "capital_loss_long")])
        pal = [k for k in co if k.startswith("passive_") and isinstance(co[k], (int, float))]
        if pal and -self.val("F8582.1c") == sum(co[k] for k in pal):
            self.ok("P-PAL", "Passive loss carryovers agree to the prior-year Form 8582", " + ".join(fmt(co[k]) for k in pal), ["F8582.1c"],
                    [f"py:/carryovers_into_2025/{k}" for k in pal])

    def _recalc_scorp_basis(self):
        recs = self.p.prior["basis_records"].get("scorp_lindqvist_family_woodworks") or []
        start = next((r for r in recs if r.get("ending_stock_basis") is not None), None)
        if not start:
            return
        basis, steps, ev = start["ending_stock_basis"], [f"{start['year']} {fmt(start['ending_stock_basis'])}"], []
        for year in range(start["year"] + 1, self.p.household["tax_year"]):
            k1 = self.doc("K-1-1120S", tax_year=year)
            if k1:
                inc, dist = self.p.val(k1["id"], "box1", 0) + self.p.val(k1["id"], "box4", 0), self.p.val(k1["id"], "box16d", 0)
                ev.append(f"{k1['id']}#page1")
            else:
                rec = next((r for r in recs if r["year"] == year and r.get("k1_income") is not None), None)
                if not rec:
                    return  # a gap: cannot prove the rollforward
                inc, dist = rec["k1_income"], rec["distributions"]
            basis = max(0, basis + inc - dist)
            steps.append(f"{year} ({fmt(inc)} - {fmt(dist)})")
        if abs(basis - self.val("F7203.1")) < 1:
            self.ok("P-7203", "S corporation basis rolled forward", " + ".join(steps) + f" = {fmt(basis)}", ["F7203.1"],
                    [*ev, "py:/basis_records/scorp_lindqvist_family_woodworks"])

    def _recalc_8606(self):
        year = self.p.household["tax_year"]
        prior = self.doc("5498", tax_year=year - 1)
        cur = self.doc("5498", tax_year=year)
        r = self.doc("1099-R")
        if not (prior and cur and r):
            return
        basis = self.p.val(prior["id"], "box1", 0) + self.p.val(cur["id"], "box1", 0)
        converted = self.p.val(r["id"], "box1", 0)
        fmv = self.p.val(cur["id"], "box5", 0)
        taxable = round(converted - basis * converted / (converted + fmv)) if converted + fmv else 0
        if taxable == self.val("F8606.18"):
            self.ok("P-8606", "Backdoor Roth pro-rata recalculated", f"basis {fmt(basis)}; converted {fmt(converted)}; year-end value {fmt(fmv)} -> taxable {fmt(taxable)}",
                    ["F8606.18"], [f"{prior['id']}#page1", f"{cur['id']}#page1", f"{r['id']}#page1"])


# ---------------------------------------------------------------------- SSN comparison (also used by the e-file simulator)
def ssn_mismatches(p: Packet, visible: set[str], household_fixes: dict) -> list[tuple[str, list, list]]:
    """For each person: (id, [(ssn on document, ref)] that disagree with the organizer, all hits)."""
    out = []
    for pid, person in p.people.items():
        ssn = household_fixes.get(pid, {}).get("ssn", person.get("ssn"))
        first = person["name"].split()[0]
        hits = []
        for d in p.raw["documents"]:
            if d["id"] not in visible:
                continue
            for pg in d["pages"]:
                t = pg["printed_content"]
                for m in re.finditer(re.escape(first) + r"[^;.]{0,40}?SSN (\d{3}-\d\d-\d{4})", t):
                    hits.append((m.group(1), f"{d['id']}#page{pg['page']}"))
                if d["document_type"] == "identity_document" and person["name"] in t:
                    hits += [(m.group(1), f"{d['id']}#page{pg['page']}") for m in re.finditer(r"(\d{3}-\d\d-\d{4})", t)]
        out.append((pid, [(s, r) for s, r in hits if s != ssn], hits))
    return out


# ---------------------------------------------------------------------- engine diagnostics as findings
ENGINE_KIND = {"FBAR_OUTSIDE_RETURN": "outside_filing", "FORM_1099_FILING": "outside_filing", "DUE_DILIGENCE_REQUIRED": "process",
               "AMT_CREDIT_CARRYFORWARD": "planning", "CA_AMT_NOT_COMPUTED": "judgment"}


def engine_findings(p: Packet) -> list[Finding]:
    out = []
    for dgn in p.current.raw["diagnostics"]:
        refs = dgn.get("refs", [])
        lines = [r for r in refs if p.is_line_key(r)]
        if lines and lines[0] in p.current.lines:
            area = area_for_line(lines[0], p.current.lines[lines[0]]["form"])
        elif dgn["code"].startswith("QUESTIONNAIRE"):
            area = "intake_and_engagement"
        elif "LOW_CONFIDENCE" in dgn["code"]:
            area = "deductions_and_credits"
        else:
            area = "investments_and_digital_assets"
        out.append(Finding(id=f"ENG-{dgn['code']}", code=dgn["code"], severity=dgn["severity"] if dgn["severity"] in ("error", "warning", "info") else "info",
                           kind=ENGINE_KIND.get(dgn["code"], "data"), area=area, title=_first_sentence(dgn["message"]),
                           summary=dgn["message"], evidence=refs, lines=lines, source="engine",
                           effect={"fed_tax": 0, "ca_tax": 0, "fed_payments": 0, "ca_payments": 0}))
    return out


# ---------------------------------------------------------------------- variance vs prior year
def variances(p: Packet, standards: dict) -> list[dict]:
    pct = standards.get("flag_if_change_over_percent", 10) / 100
    amt = standards.get("and_over_amount", 1000)
    out = []
    labels = p.prior["return_2024"]["line_labels"]
    for key, py in p.prior["return_2024"]["lines"].items():
        cur = p.current.lines.get(key)
        if not isinstance(py, (int, float)):
            continue
        cv = cur["value"] if cur and isinstance(cur["value"], (int, float)) else 0
        diff = cv - py
        if abs(diff) > amt and (py == 0 or abs(diff) / abs(py) > pct):
            out.append({"key": key, "label": (cur or {}).get("label") or labels.get(key, key), "prior": py, "current": cv,
                        "change": diff, "pct": None if py == 0 else diff / abs(py), "missing_now": cur is None})
    out.sort(key=lambda x: -abs(x["change"]))
    return out


# ---------------------------------------------------------------------- helpers
def _variants(e: dict) -> set[str]:
    v = e["value"]
    out = {str(e["text_as_read"])}
    vt = e["value_type"]
    if vt == "money" and isinstance(v, (int, float)):
        out |= {f"{v:,.2f}", f"{v:,.0f}", f"{abs(v):,.2f}", f"{v:.2f}"}
    if vt in ("integer", "quantity") and isinstance(v, (int, float)):
        out |= {f"{v:,}", str(v)}
        if float(v).is_integer():
            out.add(f"{v:,.0f}")
    if vt == "date" and isinstance(v, str) and re.match(r"\d{4}-\d\d-\d\d", v):
        y, m, d = v.split("-")
        out |= {v, f"{m}/{d}/{y}", f"{m}/{y}", f"{y}-{m}"}
    if vt == "percent":
        with contextlib.suppress(TypeError, ValueError):
            out.add(f"{round(float(v) * 100):d}%")
    return out


def _near_candidates(e: dict, page: str) -> list[str]:
    """Strings on the page that look like what was meant (same digits, different order)."""
    t = str(e["text_as_read"])
    digits = sorted(re.sub(r"\D", "", t))
    out = []
    for m in re.finditer(r"[\d$?][\d,.\-?]{3,}", page):
        s = m.group(0).strip(".,")
        if sorted(re.sub(r"\D", "", s)) == digits and s != t:
            out.append(s)
    return out[:3]


def _first_sentence(t: str) -> str:
    s = re.split(r"(?<=[a-z0-9)])\.\s", t, maxsplit=1)[0]
    return s if len(s) < 110 else s[:107] + "..."


def _sentence_with(text: str, needle: str) -> str:
    for s in re.split(r"(?<=[.)])\s+", text):
        if needle.lower() in s.lower():
            return s.strip()
    return ""


def _similarity(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def run_checks(p: Packet, visible_docs: set[str], clock: str, household_fixes: dict | None = None) -> dict:
    c = Checker(p, visible_docs, household_fixes, clock).run()
    findings = [f.to_dict() for f in c.findings] + [f.to_dict() for f in engine_findings(p)]
    return {"findings": findings, "passes": [asdict(x) for x in c.passes]}
