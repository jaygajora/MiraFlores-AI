"""Records a CPA expects, generated from the graph and the log (never typed in).

Every report returns the same shape so one UI component renders them all:
  {id, title, subtitle, sections: [{title, note, columns: [{key, label, type}], rows: [...]}]}
Row cells of type "ref" are clickable into the trace view.
"""
from __future__ import annotations

import re

from .checks import variances
from .domain import AREA_TITLES, profit_sign
from .state import Workpaper

REPORTS = [
    ("summary", "Return summary vs last year"), ("tax", "Tax computation"), ("areas", "Area summaries"),
    ("documents", "Document index"), ("depreciation", "Depreciation by asset"), ("sales", "Sales detail"),
    ("books", "Books to tax (Schedule C)"), ("rentals", "Rentals and passive losses"), ("k1", "K-1 lines"),
    ("retirement_foreign", "Retirement and foreign items"), ("deductions", "Deductions and credits with limits"),
    ("payments", "Payments"), ("state", "State split (California 540NR)"), ("carryovers", "Carryovers"),
    ("basis", "Basis by year"), ("prior_vs_us", "Prior preparer vs what we changed"), ("variances", "Variances vs last year"),
    ("outside", "Outside filings and completeness"),
]

C = lambda key, label, type="text": {"key": key, "label": label, "type": type}  # noqa: E731


def _line_rows(w: Workpaper, keys, with_prior=False):
    rows = []
    eff = w.effective()
    for k in keys:
        line = w.p.current.lines.get(k)
        if not line and k not in eff["added"]:
            continue
        base = line["value"] if line else 0
        d = eff["delta"].get(k)
        row = {"ref": k, "label": (line or eff["added"].get(k, {})).get("label", k), "engine": base,
               "adj": d if d else None, "workpaper": w.value_of(k) if line else d,
               "stale": k in eff["stale"], "verify": w.line_verification(k)["status"] if line else "unverified"}
        if with_prior:
            py = w.p.prior_line(k)
            row["prior"] = py
            if isinstance(py, (int, float)) and isinstance(row["workpaper"], (int, float)):
                row["change"] = row["workpaper"] - py
        rows.append(row)
    return rows


LINE_COLS = [C("ref", "Line", "ref"), C("label", "Description"), C("engine", "Engine v3", "money"), C("adj", "Adjustments", "money"),
             C("workpaper", "Workpaper", "money"), C("verify", "Verified", "status")]
LINE_COLS_PY = [C("ref", "Line", "ref"), C("label", "Description"), C("prior", "2024", "money"), C("engine", "Engine v3", "money"),
                C("adj", "Adjustments", "money"), C("workpaper", "Workpaper", "money"), C("change", "Change vs 2024", "money")]


def build(w: Workpaper, rid: str) -> dict:
    fn = globals().get(f"r_{rid}")
    if not fn:
        raise KeyError(rid)
    out = fn(w)
    out["id"] = rid
    out.setdefault("title", dict(REPORTS)[rid])
    return out


def r_summary(w):
    s = w.summary()
    eng, wp, py = s["engine"]["federal"], s["workpaper"]["federal"], s["prior_year"]["federal"]
    rows = []
    for k, lab in (("agi", "Adjusted gross income"), ("taxable_income", "Taxable income"), ("total_tax", "Total tax"),
                   ("payments", "Payments"), ("balance_due", "Balance due (refund)")):
        rows.append({"label": lab, "prior": py.get(k) if k != "balance_due" else (py["total_tax"] - py["payments"]),
                     "engine": eng.get(k), "workpaper": wp.get(k)})
    ce, cw = s["engine"]["california"], s["workpaper"]["california"]
    crow = []
    for k, lab in (("total_agi", "Total AGI (CA law)"), ("ca_agi", "California AGI"), ("total_tax", "California tax"),
                   ("payments", "Payments"), ("balance_due", "Balance due (refund)")):
        crow.append({"label": lab, "prior": s["prior_year"]["california"].get(k), "engine": ce.get(k), "workpaper": cw.get(k)})
    cols = [C("label", ""), C("prior", "2024 filed", "money"), C("engine", "Engine v3", "money"), C("workpaper", "Workpaper", "money")]
    keys = ["F1040.1z", "F1040.2b", "F1040.3b", "F1040.4b", "F1040.7", "F1040.8", "F1040.9", "F1040.10", "F1040.11", "F1040.12",
            "F1040.13", "F1040.15", "F1040.16", "F1040.17", "F1040.19", "F1040.22", "F1040.23", "F1040.24", "F1040.33", "F1040.37"]
    return {"subtitle": s["basis"], "sections": [
        {"title": "Federal", "columns": cols, "rows": rows},
        {"title": "California", "columns": cols, "rows": crow,
         "note": "2024 was a full-year California 540; 2025 is a part-year 540NR."},
        {"title": "Form 1040 lines", "columns": LINE_COLS_PY, "rows": _line_rows(w, keys, True)}]}


def r_tax(w):
    fed = ["F1040.11", "F1040.12", "F1040.13", "F1040.15", "F1040.16", "F6251.4", "F6251.5", "F6251.7", "F6251.11", "F1040.17",
           "F1040.18", "F8812.8", "F8812.11", "F1040.19", "Sch3.1", "F1040.22", "SchSE.12", "F8959.18", "F8960.17", "F1040.23",
           "F1040.24", "F1040.33", "F1040.37", "F2210.8", "F2210.19", "F1040.38"]
    ca = ["F540NR.17", "F540NR.18", "F540NR.19", "F540NR.31", "F540NR.32", "F540NR.34", "F540NR.35", "F540NR.36", "F540NR.37",
          "F540NR.39", "F540NR.40", "ScheduleS.credit", "F540NR.61", "F540NR.64", "F540NR.78", "F540NR.97"]
    p = w.p.params
    return {"subtitle": "Lines computed by engine logic are marked when an upstream adjustment means they need a recompute.",
            "sections": [{"title": "Federal", "columns": LINE_COLS, "rows": _line_rows(w, fed)},
                         {"title": "California", "columns": LINE_COLS, "rows": _line_rows(w, ca)},
                         {"title": "Parameters the engine used", "columns": [C("label", "Parameter"), C("value", "Value")],
                          "rows": [{"label": k, "value": str(v)} for k, v in p.items() if not isinstance(v, (list, dict))]}]}


def r_areas(w):
    rows = []
    for a in w.area_status():
        so = a["signoffs"]
        rows.append({"label": a["title"], "lines": a["lines"], "docs": a["docs"], "findings": f"{a['open_findings']} open / {a['findings']}",
                     "adjustments": a["adjustments"], "notes": a["open_notes"],
                     "preparer": _so(w, so.get("preparer")), "reviewer": _so(w, so.get("reviewer")), "partner": _so(w, so.get("partner")),
                     "hours": f"{a['hours']} / {a['budget'] if a['budget'] is not None else '-'}"})
    return {"sections": [{"title": "Areas", "columns": [C("label", "Area"), C("lines", "Lines"), C("docs", "Docs"), C("findings", "Findings"),
                                                         C("adjustments", "Adjustments"), C("notes", "Open notes"), C("preparer", "Preparer"),
                                                         C("reviewer", "Reviewer"), C("partner", "Partner"), C("hours", "Hours / budget")],
                          "rows": rows}]}


def _so(w, rec):
    if not rec:
        return "-"
    return f"{w.name(rec['by'])} {rec['at'][:10]}" + ("" if rec["valid"] else " (REOPENED)")


def r_documents(w):
    rows = []
    for d in w.document_index():
        rows.append({"ref": d["id"], "label": d["title"], "type": d["type"], "received": d["received_at"][:10],
                     "values": f"{d['values_used']}/{d['values']}", "status": d["disposition"]["status"] if d["disposition"] else (d["auto_accounted"] or d["engine_status"]),
                     "accounted": "yes" if d["accounted"] else "NO", "lines": ", ".join(d["lines"][:6]) + ("..." if d["line_count"] > 6 else "")})
    return {"subtitle": "Every document: where it landed, or why it did not.",
            "sections": [{"title": f"{len(rows)} documents", "columns": [C("ref", "Doc", "ref"), C("label", "Title"), C("type", "Type"),
                                                                         C("received", "Received"), C("values", "Values used"), C("status", "Status"),
                                                                         C("accounted", "Accounted"), C("lines", "Lands on")], "rows": rows}]}


def _improvement_assets(w) -> list[dict]:
    """Assets the workpaper added by capitalizing an expensed improvement (27.5-year SL, mid-month)."""
    out = []
    for a in w.active_adjustments():
        f = w.finding(a["finding"]) if a.get("finding") else None
        if not f or f["code"] != "IMPROVEMENT_EXPENSED":
            continue
        cost = -a["delta"]
        inv_date = next((w.p.values[e]["value"] for r in f["evidence"] for d in [w.p.doc_for_ref(r)] if d and w.p.docs[d]["document_type"] == "invoice"
                         for e in w.p.values_by_doc.get(d, []) if w.p.values[e]["field"] == "date"), None)
        months = 12 - int(inv_date[5:7]) + 0.5 if inv_date else 0
        dep = round(cost / 27.5 * months / 12, 2)
        prop = w.p.current.lines.get(a["line"][:-3] + "1" + a["line"][-1], {}).get("value", "")
        out.append({"ref": f["id"], "label": f"{prop} - {f['title'].split(' replacement')[0].split(' ', 1)[1]} (workpaper addition)", "activity": f"Rental: {prop}",
                    "in_service": inv_date or "", "method": "SL / mid-month", "life": 27.5, "cost": cost, "fed_prior": 0, "fed_2025": dep, "fed_end": dep,
                    "ca_2025": dep, "ca_end": dep, "amt_diff": 0, "disposed": ""})
    return out


def r_depreciation(w):
    rows = []
    for a in w.p.current.raw["assets"]:
        rows.append({"ref": f"asset:{a['asset_id']}", "label": a["description"], "activity": a["activity"], "in_service": a["placed_in_service"],
                     "method": a["method"], "life": a["life_years"], "cost": a["cost"],
                     "fed_prior": a["federal"]["prior_accumulated"], "fed_2025": a["federal"]["depreciation_2025"], "fed_end": a["federal"]["accumulated_end"],
                     "ca_2025": a["california"]["depreciation_2025"], "ca_end": a["california"]["accumulated_end"],
                     "amt_diff": a["amt"]["difference_from_regular"], "disposed": a.get("disposed") or ""})
    rows += _improvement_assets(w)
    sold = next((a for a in w.p.current.raw["assets"] if a.get("disposed")), None)
    rec = _line_rows(w, ["F4797.21", "F4797.22", "F4797.23", "F4797.24", "F4797.25", "F4797.26g", "SchD.19"])
    return {"subtitle": "Federal vs California vs AMT, with disposals and recapture.", "sections": [
        {"title": "Assets", "columns": [C("ref", "Asset", "ref"), C("label", "Description"), C("in_service", "In service"), C("method", "Method"),
                                        C("life", "Life"), C("cost", "Cost", "money"), C("fed_prior", "Fed prior", "money"), C("fed_2025", "Fed 2025", "money"),
                                        C("fed_end", "Fed accum.", "money"), C("ca_2025", "CA 2025", "money"), C("ca_end", "CA accum.", "money"),
                                        C("amt_diff", "AMT diff", "money"), C("disposed", "Disposed")], "rows": rows},
        {"title": f"Disposal{' of ' + sold['activity'].split(': ', 1)[-1] if sold else ''} (Form 4797) and recapture", "columns": LINE_COLS, "rows": rec},
        {"title": "California basis differences carried forward", "columns": [C("label", "Asset"), C("value", "Remaining CA difference", "money")],
         "rows": [{"label": k, "value": v} for k, v in w.p.current.raw["carryovers_out"]["california"]["depreciation_basis_differences"].items()]}]}


def r_sales(w):
    lines = w.p.current.lines
    eff = w.effective()
    groups: dict[str, dict] = {}
    for k, ln in lines.items():
        if ln["form"] != "F8949" or k.endswith(".total"):
            continue
        doc = next((w.p.values[s]["document_id"] for s in ln["sources"] if s in w.p.values), None)
        broker = w.p.docs[doc]["issuer"] if doc else ("Distributions in excess of basis" if not ln["sources"] else "Other")
        g = groups.setdefault(broker, {"n": 0, "gain": 0.0, "wash": 0, "zero_basis": 0, "adjusted": 0, "flagged": [], "lots": []})
        g["n"] += 1
        g["gain"] += ln["value"]
        g["lots"].append(ln)
        if "adjustment W" in ln["label"]:
            g["wash"] += 1
        if "basis 0.00" in ln["label"]:
            g["zero_basis"] += 1
            g["flagged"].append(k)
        if k in eff["delta"]:
            g["adjusted"] += 1
    for k in eff["added"]:
        if k.startswith("F8949"):
            g = groups.setdefault("Added by workpaper", {"n": 0, "gain": 0.0, "wash": 0, "zero_basis": 0, "adjusted": 0, "flagged": [], "lots": []})
            g["n"] += 1
            g["gain"] += eff["delta"].get(k, 0)
    rows = [{"label": b, "lots": g["n"], "gain": round(g["gain"], 2), "wash": g["wash"], "zero": g["zero_basis"], "adjusted": g["adjusted"],
             "exceptions": ", ".join(g["flagged"][:6])} for b, g in groups.items()]
    # each broker's own summary figures vs the lots on the return
    rec = []
    for d in w.p.docs_of("1099-composite", w.visible_docs()):
        if d["id"] in w.p.current.raw.get("documents_superseded", []):
            continue
        f = {w.p.values[e]["field"]: w.p.values[e]["value"] for e in w.p.values_by_doc.get(d["id"], [])}
        mine = [ln for ln in lines.values() if ln["form"] == "F8949" and not ln["key"].endswith(".total")
                and any(w.p.values.get(s, {}).get("document_id") == d["id"] for s in ln["sources"])]
        for term, boxes in (("st", "ABC"), ("lt", "DEF")):
            if f"{term}_proceeds" in f:
                doc_gain = f[f"{term}_proceeds"] - f[f"{term}_basis"] + f.get(f"{term}_wash", 0)
                det = sum(ln["value"] for ln in mine if ln["line"][0] in boxes)
                rec.append({"label": f"{d['issuer']} {'short' if term == 'st' else 'long'}-term: proceeds - basis + wash", "doc": round(doc_gain, 2), "detail": round(det, 2)})
        if "b_summary_proceeds" in f:
            det = sum(float(m.group(1).replace(",", "")) for ln in mine for m in [re.search(r"proceeds ([\d,.]+)", ln["label"])] if m)
            rec.append({"label": f"{d['issuer']} proceeds: 1099-B summary vs lots on the return", "doc": f["b_summary_proceeds"], "detail": round(det, 2)})
    for r in rec:
        r["diff"] = round(r["doc"] - r["detail"], 2)
    unread = [f for f in w.findings() if f["code"] == "UNREAD_PAGE"]
    totals = _line_rows(w, [k for k in w.p.current.order if k.startswith("F8949.") and k.endswith(".total")] + ["SchD.7", "SchD.15", "SchD.16"])
    return {"subtitle": f"{sum(g['n'] for g in groups.values())} sales summarized by broker; open the trace for any lot. Exceptions are listed, not buried.",
            "sections": [
                {"title": "By broker", "columns": [C("label", "Broker"), C("lots", "Sales"), C("gain", "Gain (loss)", "money"), C("wash", "Wash-sale lots"),
                                                   C("zero", "Zero basis"), C("adjusted", "Adjusted"), C("exceptions", "Exceptions")], "rows": rows},
                {"title": "Broker totals reconciled to lot detail", "columns": [C("label", ""), C("doc", "Broker summary", "money"),
                                                                                 C("detail", "Lots on return", "money"), C("diff", "Difference", "money")], "rows": rec,
                 "note": " ".join(f["summary"] for f in unread) or None},
                {"title": "Form 8949 and Schedule D totals", "columns": LINE_COLS, "rows": totals}]}


def r_books(w):
    """Book net income to Schedule C, each step computed from a books line and the return line it becomes."""
    books = w.p.doc_of("books_profit_loss")
    if not books:
        return {"sections": []}
    bf = {w.p.values[e]["field"]: w.p.values[e]["value"] for e in w.p.values_by_doc[books["id"]]}
    L = lambda k: w.p.current.lines.get(k, {}).get("value", 0)  # noqa: E731
    pick = lambda word: next((v for k, v in bf.items() if word in k.lower()), 0)  # noqa: E731
    net_books = bf.get("net_income", 0)
    rows = [{"label": "Net income per books", "ref": f"{books['id']}#page1", "amount": net_books}]
    recon = [
        ("Gross receipts on the return vs books revenue", "SchC.1", L("SchC.1") - bf.get("total_income", 0)),
        ("Remove books depreciation", "SchC.13", pick("depreciation")),
        ("Tax depreciation", "F4562-C.22", -L("F4562-C.22")),
        ("Remove books vehicle costs; use the standard mileage rate", "SchC.9", pick("car and truck") - L("SchC.9")),
        ("Remove health insurance (it moves to Schedule 1)", "Sch1.17", pick("insurance - health")),
        ("Meals: only 50% deductible", "SchC.24b", pick("meals") - L("SchC.24b")),
        ("Home office (simplified method)", "SchC.30", -L("SchC.30")),
    ]
    total = net_books
    for lab, ref, amt in recon:
        if amt:
            rows.append({"label": lab, "ref": ref, "amount": amt})
            total += amt
    engine = L("SchC.31")
    rows.append({"label": "Net profit per engine (Schedule C line 31)", "ref": "SchC.31", "amount": round(total), "check": engine})
    wp_rows = []
    for a in w.active_adjustments():
        if a["line"].startswith(("SchC", "F4562-C")):
            wp_rows.append({"label": a["reason"][:90], "ref": a["line"], "amount": a["delta"] * profit_sign(a["line"], a["line"].split(".")[0])})
    wp_rows.append({"label": "Net profit per workpaper", "ref": "SchC.31", "amount": w.value_of("SchC.31")})
    gap = round(total) - engine
    return {"subtitle": "From the client's books to taxable business income, every step tied to a line.", "sections": [
        {"title": "Books to engine", "columns": [C("ref", "Ref", "ref"), C("label", "Step"), C("amount", "Amount", "money"), C("check", "Engine says", "money")],
         "rows": rows, "note": f"Reconciles to the engine's {engine:,} exactly." if not gap else f"Unexplained difference of {gap:,}: investigate."},
        {"title": "Engine to workpaper", "columns": [C("ref", "Line", "ref"), C("label", "Adjustment"), C("amount", "Effect on profit", "money")], "rows": wp_rows},
        {"title": "Schedule C lines", "columns": LINE_COLS, "rows": _line_rows(w, [k for k in w.p.current.order if k.startswith("SchC.")])}]}


def r_rentals(w):
    sections = []
    for letter in "ABC":
        keys = [k for k in w.p.current.order if re.match(rf"SchE\.\d+{letter}$", k)]
        if not keys:
            continue
        name = w.p.current.lines.get(f"SchE.1{letter}", {}).get("value", f"Property {letter}")
        sold = any(a.get("disposed") and str(name).split(",")[0] in a["activity"] for a in w.p.current.raw["assets"])
        sections.append({"title": f"{name}{' (sold)' if sold else ''}", "columns": LINE_COLS,
                         "rows": _line_rows(w, [*keys, f"F4562-E.total-{letter}"])})
    pal = [k for k in w.p.current.order if k.startswith("F8582") or re.match(r"SchE\.(22[A-C]|26|41)$", k)]
    co = w.p.prior["carryovers_into_2025"]
    prior = {k: v for k, v in co.items() if k.startswith("passive_") and isinstance(v, (int, float))}
    net = w.p.current.lines.get("F8582.4", {}).get("value", 0)
    sections.append({"title": "Passive activity loss (Form 8582)", "columns": LINE_COLS, "rows": _line_rows(w, pal),
                     "note": f"Suspended losses carried in: {', '.join(f'{k[8:]} {v:,}' for k, v in prior.items())}. "
                             + ("Net passive income is positive, so all are allowed this year." if net > 0 else "Net passive loss: some remain suspended.")})
    return {"subtitle": "Each rental, the passive loss limitation, and losses freed by a sale.", "sections": sections}


def r_k1(w):
    rows = []
    for t in ("K-1-1120S", "K-1-1065", "K-1-state-supplement"):
        for d in w.p.docs_of(t, w.visible_docs()):
            for e in w.p.values_by_doc.get(d["id"], []):
                v = w.p.values[e]
                land = w.p.landing_for_value(e)
                rows.append({"ref": e, "doc": f"{d['id']} ({d['tax_year']})", "label": v["label"],
                             "value": v["value"] if isinstance(v["value"], (int, float)) else None,
                             "text": "" if isinstance(v["value"], (int, float)) else str(v["value"]),
                             "lands": ", ".join(land.get("lines", [])) or land.get("reason", "")})
    return {"subtitle": "Each K-1 box and where it landed.", "sections": [
        {"title": "K-1 items", "columns": [C("ref", "Value", "ref"), C("doc", "Doc"), C("label", "Box"), C("value", "Amount", "money"), C("text", "Text"),
                                           C("lands", "Lands on")], "rows": rows},
        {"title": "Related returns", "columns": [C("label", "Entity"), C("ret", "Return"), C("by", "Prepared by"), C("here", "In this packet")],
         "rows": [{"label": r["who"], "ret": r["return"], "by": r["prepared_by"], "here": str(r["in_this_packet"])} for r in w.p.household["related_returns"]]}]}


def r_retirement_foreign(w):
    note = lambda *codes: " ".join(f["title"] + "." for f in w.findings() if f["code"] in codes) or None  # noqa: E731
    return {"sections": [
        {"title": "Nondeductible IRA and Roth conversion (Form 8606)", "columns": LINE_COLS,
         "rows": _line_rows(w, [k for k in w.p.current.order if k.startswith("F8606")] + ["F1040.4a", "F1040.4b"])},
        {"title": "SEP and HSA", "columns": LINE_COLS, "rows": _line_rows(w, ["Sch1.16", "Sch1.13"] + [k for k in w.p.current.order if k.startswith("F8889")]),
         "note": note("EXCESS_SEP_CONTRIBUTION")},
        {"title": "Foreign accounts and income", "columns": LINE_COLS,
         "rows": _line_rows(w, [k for k in w.p.current.order if k.startswith(("SchB.7", "F8938"))] + ["Sch3.1"]),
         "note": note("WRONG_YEAR_EXCHANGE_RATE", "FBAR_OUTSIDE_RETURN", "PRIOR_PREPARER_OPEN_ITEM")}]}


def r_deductions(w):
    p = w.p.params
    return {"sections": [
        {"title": "Itemized deductions", "columns": LINE_COLS, "rows": _line_rows(w, [k for k in w.p.current.order if k.startswith(("SchA", "F8283"))] + ["F1040.12"]),
         "note": f"SALT cap {p['salt_cap']:,} (phase-down above {p['salt_cap_phase_start']:,} MAGI). Standard deduction would be {p['std_deduction_mfj']:,}."},
        {"title": "QBI", "columns": LINE_COLS, "rows": _line_rows(w, [k for k in w.p.current.order if k.startswith("F8995")])},
        {"title": "Credits", "columns": LINE_COLS, "rows": _line_rows(w, [k for k in w.p.current.order if k.startswith(("F8812", "F8863", "F2441", "F8867"))]),
         "note": f"CTC phase-out from {p['ctc_phaseout_start']:,}: 50 per 1,000 over. AOTC phases out 160,000-180,000."}]}


def r_payments(w):
    tr = w.p.agency["irs_account_transcript_2025"]
    rows = [{"label": t["description"], "date": t["date"], "amount": t["amount"] if isinstance(t["amount"], (int, float)) else None,
             "text": "" if isinstance(t["amount"], (int, float)) else t["amount"], "src": f"IRS transcript as of {tr[-1]['as_of']}"}
            for t in tr[-1]["transactions"] if t["date"] <= w.state().clock[:10]]
    ftb = w.p.agency["ftb_account"]
    crow = [{"label": "Estimated payment (TY2025)", "date": t["date"], "amount": t["amount"], "src": f"FTB account as of {ftb['as_of']}"} for t in ftb["tax_year_2025_payments"]]
    crow += [{"label": "Payment held as TY2024 credit", "date": t["date"], "amount": t["amount"], "src": t["note"]} for t in ftb["tax_year_2024_payments_after_filing"]]
    pr = w.p.raw["post_filing_rates"]
    return {"sections": [
        {"title": "Federal payments on the return", "columns": LINE_COLS, "rows": _line_rows(w, ["F1040.25a", "F1040.26", "Sch3.10", "Sch3.11", "F1040.33", "F1040.37", "F2210.19"])},
        {"title": "IRS account transcript", "columns": [C("date", "Date"), C("label", "Transaction"), C("amount", "Amount", "money"), C("text", ""), C("src", "Source")], "rows": rows},
        {"title": "California payments", "columns": LINE_COLS, "rows": _line_rows(w, ["F540NR.71", "F540NR.72", "F540NR.73", "F540NR.78", "F540NR.97"])},
        {"title": "FTB account", "columns": [C("date", "Date"), C("label", "Payment"), C("amount", "Amount", "money"), C("src", "Source")], "rows": crow},
        {"title": "After the due date", "columns": [C("label", "Rate"), C("value", "Value")],
         "rows": [{"label": k, "value": str(v)} for k, v in pr.items()],
         "note": "Any federal balance paid after 2026-04-15 accrues interest and the failure-to-pay penalty (the engine does not compute these)."}]}


def r_state(w):
    rows = []
    for k in w.p.current.order:
        m = re.match(r"SchCA540NR\.(\d+)\.A$", k)
        if not m:
            continue
        n = m.group(1)
        def g(c, n=n):
            return w.value_of(f"SchCA540NR.{n}.{c}") if f"SchCA540NR.{n}.{c}" in w.p.current.lines else None
        label = w.p.current.lines[k]["label"].replace(" - federal", "")
        rows.append({"ref": f"SchCA540NR.{n}.E", "label": label, "A": g("A"), "B": g("B"), "C": g("C"), "D": g("D"), "E": g("E"),
                     "rule": w.p.rules.get(w.p.current.lines.get(f"SchCA540NR.{n}.E", {}).get("rule", ""), "")})
    res = w.p.household["residency"]
    return {"subtitle": f"California resident {res[0]['from']} to {res[0]['to']} ({w.p.params['ca_resident_days']} of {w.p.params['year_days']} days); Texas from {res[1]['from']}.",
            "sections": [
                {"title": "Schedule CA (540NR): federal, adjustments, California law, California source", "columns": [
                    C("ref", "Line", "ref"), C("label", "Income"), C("A", "A Federal", "money"), C("B", "B Subtract", "money"), C("C", "C Add", "money"),
                    C("D", "D CA law", "money"), C("E", "E CA source", "money"), C("rule", "How sourced")], "rows": rows},
                {"title": "540NR computation", "columns": LINE_COLS, "rows": _line_rows(w, [k for k in w.p.current.order if k.startswith(("F540NR", "ScheduleS"))])}]}


def r_carryovers(w):
    cin = w.p.prior["carryovers_into_2025"]
    cout = w.p.current.raw["carryovers_out"]
    rows = []
    for k in sorted(set(cin) | set(cout["federal"])):
        if k in ("california", "sources"):
            continue
        rows.append({"label": k.replace("_", " "), "in": cin.get(k) if isinstance(cin.get(k), (int, float)) else None,
                     "out": cout["federal"].get(k) if isinstance(cout["federal"].get(k), (int, float)) else None})
    adds = [f"{a['label']} {a['cost']:,.0f}" for a in _improvement_assets(w)]
    sep = next((f for f in w.findings() if f["code"] == "EXCESS_SEP_CONTRIBUTION"), None)
    if sep:
        adds.append(sep["title"].lower())
    return {"subtitle": cin["sources"], "sections": [
        {"title": "Federal", "columns": [C("label", "Item"), C("in", "Into this year", "money"), C("out", "Out to next year (engine)", "money")], "rows": rows,
         "note": ("Workpaper adds: " + "; ".join(adds) + ".") if adds else None},
        {"title": "California", "columns": [C("label", "Item"), C("in", "Into this year", "money")],
         "rows": [{"label": k.replace("_", " "), "in": v} for k, v in cin["california"].items() if isinstance(v, (int, float))]}]}


def r_basis(w):
    """Stock basis by year, rolled from the last known year with each year's source."""
    year = w.p.household["tax_year"]
    rows = []
    for name, recs in w.p.prior["basis_records"].items():
        if not name.startswith("scorp"):
            continue
        start = next((r for r in recs if r.get("ending_stock_basis") is not None), None)
        if not start:
            continue
        basis = start["ending_stock_basis"]
        rows.append({"entity": name, "year": start["year"], "begin": None, "income": None, "dist": None, "end": basis, "src": start["source"]})
        for y in range(start["year"] + 1, year):
            k1 = w.p.doc_of("K-1-1120S", w.visible_docs(), tax_year=y)
            if k1:
                inc = w.p.val(k1["id"], "box1", 0) + w.p.val(k1["id"], "box4", 0)
                dist, src = w.p.val(k1["id"], "box16d", 0), f"{y} K-1 ({k1['id']}, received {k1['received_at'][:10]})"
            else:
                rec = next((r for r in recs if r["year"] == y), {})
                inc, dist, src = rec.get("k1_income"), rec.get("distributions"), rec.get("source", "missing")
            if inc is None:
                rows.append({"entity": name, "year": y, "begin": basis, "income": None, "dist": None, "end": None, "src": f"GAP: {src}"})
                break
            end = max(0, basis + inc - dist)
            rows.append({"entity": name, "year": y, "begin": basis, "income": inc, "dist": dist, "end": end, "src": src})
            basis = end
        L = lambda k: w.p.current.lines.get(k, {}).get("value")  # noqa: E731
        rows.append({"entity": name, "year": year, "begin": L("F7203.1"), "income": L("F7203.4"), "dist": L("F7203.6"), "end": L("F7203.15"),
                     "src": f"Form 7203; distributions in excess of basis {L('F7203.excess') or 0:,} taxed as capital gain"})
    other = []
    for d in w.p.docs_of("K-1-1065", w.visible_docs()):
        other.append({"label": f"{d['issuer']} capital account at year end", "value": w.p.val(d["id"], "cap_end"), "src": f"{d['id']} (outside basis not provided)"})
    for k in ("F8606.2", "F8606.14"):
        if k in w.p.current.lines:
            other.append({"label": w.p.current.lines[k]["label"], "value": w.p.current.lines[k]["value"], "src": k})
    buy = w.p.doc_of("closing_statement_buyer")
    if buy:
        other.append({"label": "Home purchase price", "value": w.p.val(buy["id"], "price"), "src": f"{buy['id']} (plus capitalized closing costs)"})
    return {"subtitle": "Basis gaps filled from late documents; each year tied to its source.", "sections": [
        {"title": "S corporation stock basis", "columns": [C("year", "Year"), C("begin", "Beginning", "money"), C("income", "Income items", "money"),
                                                          C("dist", "Distributions", "money"), C("end", "Ending", "money"), C("src", "Source")], "rows": rows},
        {"title": "Form 7203", "columns": LINE_COLS, "rows": _line_rows(w, [k for k in w.p.current.order if k.startswith("F7203")])},
        {"title": "Other basis", "columns": [C("label", "Item"), C("value", "Value", "money"), C("src", "Source")], "rows": other}]}


def r_prior_vs_us(w):
    pw = w.p.prior["prior_preparer_workpaper"]
    fs = w.findings()
    rows = [{"label": n, "us": _prior_resolution(w, fs, n)} for n in pw["notes"]]
    rows += [{"label": "Open item: " + n, "us": _prior_resolution(w, fs, n)} for n in pw["open_items_left_by_prior_preparer"]]
    rows += [{"label": f"{k}: {v}", "us": _prior_resolution(w, fs, v)} for k, v in w.p.prior["return_2024"]["notes"].items()]
    adj = [{"ref": a["line"], "label": a["reason"][:100], "by": w.name(a["by"]), "fed": a["effect"]["fed_tax"], "ca": a["effect"]["ca_tax"]} for a in w.active_adjustments()]
    return {"subtitle": pw["summary_memo"], "sections": [
        {"title": "Prior preparer positions and what we did", "columns": [C("label", "Prior preparer"), C("us", "This year")], "rows": rows},
        {"title": "Our adjustments to the engine", "columns": [C("ref", "Line", "ref"), C("label", "Reason"), C("by", "By"), C("fed", "Federal tax", "money"),
                                                               C("ca", "CA tax", "money")], "rows": adj}]}


def _prior_resolution(w, fs: list[dict], note: str) -> str:
    """What this year's file says about a prior-preparer position: the matching finding, or the line it concerns."""
    low = note.lower()
    open_item = next((f for f in fs if f["code"] == "PRIOR_PREPARER_OPEN_ITEM" and f["title"].split(": ", 1)[-1].lower()[:30] in low), None)
    if open_item:
        return open_item["summary"]
    topics = [("8606", None, "F8606.18"), ("s corp", None, "F7203.1"), ("8938", "FBAR_OUTSIDE_RETURN", "F8938.1.max"),
              ("home office", "HOME_OFFICE_AREA_CHANGE", "SchC.30"), ("health insurance", "SEHI_NOT_ALLOWED", "Sch1.17"),
              ("unallowed", None, "F8582.4"), ("appliances", None, "SchCA540NR.17.B")]
    for word, code, line in topics:
        if word in low:
            f = next((x for x in fs if x["code"] == code), None) if code else None
            ln = w.p.current.lines.get(line)
            txt = f"{f['title']} ({f['status']})." if f else ""
            if ln:
                txt += f" This year {line} {ln['label']}: {w.value_of(line):,}." if isinstance(ln["value"], (int, float)) else f" {line}: {ln['value']}."
            return txt.strip()
    return ""


def r_variances(w):
    s = w.state()
    rows = []
    for v in variances(w.p, s.standards.get("variance_review", {})):
        ex = s.explanations.get(v["key"])
        rows.append({"ref": v["key"], "label": v["label"], "prior": v["prior"], "current": v["current"], "change": v["change"],
                     "pct": f"{v['pct']:+.0%}" if v["pct"] is not None else "new", "explained": ex["text"] if ex else ""})
    st = s.standards.get("variance_review", {})
    return {"subtitle": f"Flagged when the change is over {st.get('flag_if_change_over_percent')}% and over {st.get('and_over_amount'):,} (firm standard).",
            "sections": [{"title": f"{len(rows)} swings vs 2024", "columns": [C("ref", "Line", "ref"), C("label", "Line"), C("prior", "2024", "money"),
                                                                                C("current", "2025", "money"), C("change", "Change", "money"), C("pct", "%"),
                                                                                C("explained", "Explanation")], "rows": rows}]}


def r_outside(w):
    f = next((x for x in w.findings() if x["id"] == "F-OUTSIDE"), None)
    rows = [{"label": part.split(":", 1)[0], "detail": part.split(":", 1)[1].strip() if ":" in part else ""} for part in (f["summary"].split(" | ") if f else [])]
    rows += [{"label": x["title"], "detail": x["summary"][:200]} for x in w.findings() if x["kind"] == "outside_filing" and x["id"] != "F-OUTSIDE"]
    steps = w.required_steps()
    return {"subtitle": "Completeness: every document used, every area considered, every outside filing identified.", "sections": [
        {"title": "Outside filings", "columns": [C("label", "Filing"), C("detail", "Detail")], "rows": rows},
        {"title": "Required steps (firm standard)", "columns": [C("n", "#"), C("step", "Step"), C("done", "Done", "status"), C("why", "Evidence")],
         "rows": [{"n": x["n"], "step": x["step"], "done": "done" if x["done"] else "open", "why": x["why"]} for x in steps]},
        {"title": "Areas considered", "columns": [C("label", "Area"), C("lines", "Lines"), C("docs", "Documents"), C("findings", "Findings")],
         "rows": [{"label": a["title"], "lines": a["lines"], "docs": a["docs"], "findings": a["findings"]} for a in w.area_status()]}]}


_ = AREA_TITLES
