"""Load the pipeline packet exactly as delivered and index it as a lineage graph.

The packet is read-only. Everything the workpaper adds (adjustments, notes,
sign-offs, decisions...) lives in the event log (store.py), never here.

Graph vocabulary
----------------
node      anything addressable by a ref string: a return line ("F1040.11"),
          an extracted value ("ev-0016"), a document ("D08") or page ("D08#p1"),
          a client answer ("qa-14"), a prior-year pointer ("py:/..."), ...
inputs    line -> lines it is computed from (engine provided)
sources   line -> evidence refs (extracted values, answers, records)
consumers reverse of inputs ("used by")
landings  extracted value -> lines that cite it (reverse of sources)
"""
from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

FORM_ORDER = [
    "F1040", "Sch1", "Sch2", "Sch3", "SchA", "SchB", "SchC", "SchSE", "F4562-C", "SchD", "F8949",
    "F4797", "SchE", "F4562-E", "F8582", "F7203", "F8995", "F6251", "F8959", "F8960", "F8812",
    "F8863", "F2441", "F8889", "F8606", "F8283", "F8938", "F2210", "F8867", "SchCA540NR",
    "F540NR", "ScheduleS", "FTB3885A", "FTB5805",
]

FORM_TITLES = {
    "F1040": "Form 1040", "Sch1": "Schedule 1 - Additional income and adjustments",
    "Sch2": "Schedule 2 - Additional taxes", "Sch3": "Schedule 3 - Credits and payments",
    "SchA": "Schedule A - Itemized deductions", "SchB": "Schedule B - Interest and dividends",
    "SchC": "Schedule C - Business income", "SchSE": "Schedule SE - Self-employment tax",
    "F4562-C": "Form 4562 - Studio equipment", "SchD": "Schedule D - Capital gains",
    "F8949": "Form 8949 - Sales detail", "F4797": "Form 4797 - Sale of business property",
    "SchE": "Schedule E - Rentals and K-1s", "F4562-E": "Form 4562 - Rental depreciation",
    "F8582": "Form 8582 - Passive losses", "F7203": "Form 7203 - S corporation basis",
    "F8995": "Form 8995-A - QBI deduction", "F6251": "Form 6251 - AMT",
    "F8959": "Form 8959 - Additional Medicare tax", "F8960": "Form 8960 - Net investment income tax",
    "F8812": "Schedule 8812 - Child tax credit", "F8863": "Form 8863 - Education credits",
    "F2441": "Form 2441 - Dependent care", "F8889": "Form 8889 - HSA",
    "F8606": "Form 8606 - Nondeductible IRA", "F8283": "Form 8283 - Noncash gifts",
    "F8938": "Form 8938 - Foreign assets", "F2210": "Form 2210 - Underpayment penalty",
    "F8867": "Form 8867 - Due diligence", "SchCA540NR": "Schedule CA (540NR)",
    "F540NR": "California Form 540NR", "ScheduleS": "California Schedule S",
    "FTB3885A": "FTB 3885A - California depreciation", "FTB5805": "FTB 5805 - CA underpayment",
}

# Signs for R-SUM lines whose listed inputs do not fully describe the arithmetic.
# Inferred once from the engine values (see infer_signs) and pinned here where the
# data is ambiguous (an input that is zero in every version).
SIGN_OVERRIDES = {
    "F540NR.64": {"F540NR.40": 1, "ScheduleS.credit": -1, "F540NR.61": 1},
}

MONEY_RE = re.compile(r"-?\$?\(?\d[\d,]*\.?\d*\)?")


@dataclass
class Version:
    version: str
    computed_at: str
    trigger: str
    raw: dict
    lines: dict[str, dict] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    consumers: dict[str, list[str]] = field(default_factory=dict)
    landings: dict[str, list[str]] = field(default_factory=dict)
    signs: dict[str, dict[str, int]] = field(default_factory=dict)


class Packet:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.raw: dict = json.loads(self.path.read_text())
        r = self.raw
        self.readme = r["readme"]
        self.household = r["household"]
        self.people = {p["id"]: p for p in r["household"]["people"]}
        self.docs: dict[str, dict] = {d["id"]: d for d in r["documents"]}
        self.doc_order = [d["id"] for d in r["documents"]]
        self.pages: dict[tuple[str, int], str] = {}
        for d in r["documents"]:
            for p in d["pages"]:
                self.pages[(d["id"], p["page"])] = p["printed_content"]
        self.values: dict[str, dict] = {e["id"]: e for e in r["extracted_values"]}
        self.values_by_doc: dict[str, list[str]] = {}
        for e in r["extracted_values"]:
            self.values_by_doc.setdefault(e["document_id"], []).append(e["id"])
        c = r["client"]
        self.questionnaire = {q["id"]: q for q in c["questionnaire"]}
        self.messages = {m["id"]: m for m in c["messages"]}
        self.calls = {k["id"]: k for k in c["call_notes"]}
        self.firm = r["firm"]
        self.staff = {s["id"]: s for s in r["firm"]["staff"]}
        self.client_users = {u["id"]: u for u in r["firm"]["client_users"]}
        self.timeline = r["timeline"]
        self.timeline_by_id = {t["id"]: t for t in r["timeline"]}
        self.engine = r["engine_reference"]
        self.rules = r["engine_reference"]["rules"]
        self.params = r["engine_reference"]["parameters"]
        self.prior = r["prior_years"]
        self.agency = r["tax_agency_records"]
        self.what_if = r["what_if"]
        self.versions: dict[str, Version] = {}
        for v in r["return_versions"]:
            ver = Version(v["version"], v["computed_at"], v["trigger"], v)
            for line in v["lines"]:
                ver.lines[line["key"]] = line
                ver.order.append(line["key"])
            for line in v["lines"]:
                for i in line["inputs"]:
                    ver.consumers.setdefault(i, []).append(line["key"])
                for s in line["sources"]:
                    ver.landings.setdefault(s, []).append(line["key"])
            for a in v.get("assets", []):
                for s in a.get("sources", []):
                    ver.landings.setdefault(s, []).append(f"asset:{a['asset_id']}")
            ver.signs = self._infer_signs(ver)
            self.versions[ver.version] = ver
        self.current = self.versions["v3"]

    # ------------------------------------------------------------------ arithmetic
    @staticmethod
    def _sum_inputs(ver: Version, line: dict) -> list[str]:
        """Inputs actually combined by an R-SUM line.

        Schedule CA column D lines list only column A as an input, but the form's
        arithmetic is A - B + C; we make that explicit.
        """
        key = line["key"]
        if line["form"] == "SchCA540NR" and key.endswith(".D") and len(line["inputs"]) == 1:
            stem = key[:-2]
            return [k for k in (f"{stem}.A", f"{stem}.B", f"{stem}.C") if k in ver.lines]
        return list(line["inputs"])

    def _infer_signs(self, ver: Version) -> dict[str, dict[str, int]]:
        signs: dict[str, dict[str, int]] = {}
        for key, line in ver.lines.items():
            if line["rule"] == "R-SUM":
                ins = self._sum_inputs(ver, line)
                if key in SIGN_OVERRIDES:
                    signs[key] = SIGN_OVERRIDES[key]
                    continue
                if key.endswith(".D") and line["form"] == "SchCA540NR":
                    stem = key[:-2]
                    signs[key] = {i: (-1 if i == f"{stem}.B" else 1) for i in ins}
                    continue
                vals = [ver.lines[i]["value"] if i in ver.lines else 0 for i in ins]
                if not all(isinstance(x, (int, float)) for x in vals):
                    continue
                target = line["value"]
                found = None
                if abs(sum(vals) - target) <= 1.01:
                    found = (1,) * len(vals)
                elif len(vals) <= 14:
                    for s in itertools.product([1, -1], repeat=len(vals)):
                        if abs(sum(a * b for a, b in zip(s, vals, strict=False)) - target) <= 1.01:
                            found = s
                            break
                if found:
                    signs[key] = dict(zip(ins, found, strict=False))
            elif line["rule"] == "R-CARRY" and len(line["inputs"]) == 1:
                signs[key] = {line["inputs"][0]: 1}
        return signs

    # ------------------------------------------------------------------ helpers
    def page_text(self, doc_id: str, page: int) -> str:
        return self.pages.get((doc_id, page), "")

    def line(self, key: str, version: str = "v3") -> dict | None:
        return self.versions[version].lines.get(key)

    def is_line_key(self, ref: str) -> bool:
        return any(ref in v.lines for v in self.versions.values())

    def prior_line(self, key: str) -> Any:
        return self.prior["return_2024"]["lines"].get(key)

    def doc_for_ref(self, ref: str) -> str | None:
        if ref in self.values:
            return self.values[ref]["document_id"]
        m = re.match(r"(?:doc:)?(D\d\d)(?:#page?(\d+))?$", ref)
        if m:
            return m.group(1)
        return None

    def json_pointer(self, root: Any, ptr: str) -> Any:
        cur = root
        for part in [p for p in ptr.split("/") if p != ""]:
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(cur, list):
                cur = cur[int(part)]
            elif isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return cur

    # ------------------------------------------------------------------ ref resolution
    def resolve(self, ref: str, version: str = "v3") -> dict:
        """Describe any ref in a uniform shape the UI can render as a chip/link."""
        out: dict[str, Any] = {"ref": ref, "kind": "unknown", "title": ref}
        if ref in self.values:
            e = self.values[ref]
            d = self.docs[e["document_id"]]
            out.update(kind="value", title=f"{e['label']}", value=e["value"], doc=d["id"],
                       doc_title=d["title"], page=e["page"], field=e["field"],
                       text_as_read=e["text_as_read"], confidence=e["confidence"],
                       value_type=e["value_type"])
            return out
        m = re.match(r"(?:doc:)?(D\d\d)(?:#page?(\d+))?$", ref)
        if m and m.group(1) in self.docs:
            d = self.docs[m.group(1)]
            out.update(kind="document", doc=d["id"], title=d["title"],
                       page=int(m.group(2)) if m.group(2) else None)
            if out["page"]:
                out["excerpt"] = self.page_text(d["id"], out["page"])[:240]
            return out
        if ref in self.questionnaire:
            q = self.questionnaire[ref]
            out.update(kind="answer", title=q["question"], text=q["answer"], by=q["answered_by"],
                       at=q["answered_at"])
            return out
        if ref in self.messages:
            msg = self.messages[ref]
            out.update(kind="message", title=f"Message from {msg['from']}", text=msg["text"],
                       at=msg["sent_at"])
            return out
        if ref in self.calls:
            c = self.calls[ref]
            out.update(kind="call", title=f"Call notes {c['date'][:10]}", text=" | ".join(c["notes"]),
                       at=c["date"])
            return out
        if ref.startswith("py:"):
            val = self.json_pointer(self.prior, ref[3:])
            label = None
            mm = re.match(r"py:/return_2024/lines/(.+)$", ref)
            if mm:
                label = self.prior["return_2024"]["line_labels"].get(mm.group(1))
            out.update(kind="prior_year", title=label or f"Prior-year record {ref[3:]}", value=val)
            return out
        if ref.startswith("agency:"):
            val = self.json_pointer(self.agency, ref[7:])
            out.update(kind="agency", title=f"Agency record {ref[7:]}", value=val)
            return out
        if ref.startswith("asset:"):
            aid = ref[6:]
            a = next((x for x in self.versions[version].raw.get("assets", []) if x["asset_id"] == aid), None)
            if a is None:
                a = next((x for x in self.prior["asset_records"] if x["asset_id"] == aid), None)
            out.update(kind="asset", title=a["description"] if a else aid, asset=a)
            return out
        if ref.startswith("household:"):
            pid = ref[10:]
            p = self.people.get(pid, {})
            out.update(kind="household", title=f"Household: {p.get('name', pid)}",
                       text=p.get("relationship") or p.get("role"))
            return out
        if ref.startswith("ref:param."):
            name = ref[10:]
            out.update(kind="parameter", title=f"Engine parameter {name}", value=self.params.get(name))
            return out
        if ref.startswith("ref:fx."):
            parts = ref.split(".")
            rate = parts[-1]
            out.update(kind="parameter", title=f"Exchange rate SEK per USD ({rate})",
                       value=self.raw["fx_rates"]["SEK_per_USD"].get(rate))
            return out
        if ref.startswith("timeline:"):
            t = self.timeline_by_id.get(ref[9:])
            out.update(kind="timeline", title=t["event"].replace("_", " ") if t else ref,
                       text=(t or {}).get("detail"), at=(t or {}).get("at"))
            return out
        if ref in self.versions:
            v = self.versions[ref]
            out.update(kind="version", title=f"Return {ref} ({v.computed_at[:10]})", text=v.trigger)
            return out
        line = self.versions[version].lines.get(ref) or next(
            (v.lines[ref] for v in self.versions.values() if ref in v.lines), None)
        if line:
            out.update(kind="line", title=f"{ref} {line['label']}", value=line["value"],
                       form=line["form"], jurisdiction=line["jurisdiction"])
            return out
        return out

    # ------------------------------------------------------------------ lineage
    def trace_down(self, key: str, version: str = "v3", depth: int = 0, seen=None, max_depth: int = 12) -> dict:
        """How a line was built: inputs recursively, down to evidence."""
        ver = self.versions[version]
        seen = seen if seen is not None else set()
        line = ver.lines.get(key)
        if line is None:
            return {"ref": key, "missing": True}
        node = {
            "key": key, "label": line["label"], "value": line["value"], "rule": line["rule"],
            "rule_text": self.rules.get(line["rule"]), "note": line.get("note"),
            "sign": None, "sources": [self.resolve(s, version) for s in line["sources"]],
            "inputs": [],
        }
        if key in seen or depth >= max_depth:
            node["truncated"] = True
            return node
        seen.add(key)
        signs = ver.signs.get(key, {})
        ins = self._sum_inputs(ver, line) if line["rule"] == "R-SUM" else line["inputs"]
        for i in ins:
            child = self.trace_down(i, version, depth + 1, seen, max_depth)
            child["sign"] = signs.get(i)
            node["inputs"].append(child)
        return node

    def used_by(self, key: str, version: str = "v3") -> list[str]:
        """Every line downstream of key (transitive consumers), nearest first."""
        ver = self.versions[version]
        out, frontier, seen = [], [key], {key}
        while frontier:
            nxt = []
            for k in frontier:
                for c in ver.consumers.get(k, []):
                    if c not in seen:
                        seen.add(c)
                        out.append(c)
                        nxt.append(c)
            frontier = nxt
        return out

    def lines_citing(self, ref: str, version: str = "v3") -> list[str]:
        return list(dict.fromkeys(self.versions[version].landings.get(ref, [])))

    @cached_property
    def duplicate_notes(self) -> dict[str, str]:
        """Documents that the engine itself says it counted once (second image...)."""
        out = {}
        for line in self.current.lines.values():
            note = line.get("note") or ""
            m = re.match(r"(D\d\d) is a second image of .*\((D\d\d)\)", note)
            if m:
                out[m.group(1)] = f"Second image of {m.group(2)}; the engine counted it once ({line['key']})."
        return out

    def landing_for_value(self, ev_id: str, version: str = "v3") -> dict:
        """Where an extracted value landed, or why it did not."""
        e = self.values[ev_id]
        lines = self.lines_citing(ev_id, version)
        if lines:
            return {"status": "used", "lines": lines}
        ver = self.versions[version]
        doc = e["document_id"]
        if doc in ver.raw.get("documents_superseded", []):
            by = self.superseded_by(doc)
            return {"status": "superseded", "reason": f"Document superseded{' by ' + by if by else ''}."}
        if doc in self.duplicate_notes:
            return {"status": "duplicate", "reason": self.duplicate_notes[doc]}
        if doc not in ver.raw.get("documents_used", []):
            return {"status": "not_used", "reason": "Document not used by the engine in this version."}
        return {"status": "informational", "reason": "Read from the document but not a return input (context or identity field)."}

    def superseded_by(self, doc_id: str) -> str | None:
        d = self.docs[doc_id]
        for other in self.raw["documents"]:
            if other["id"] != doc_id and other["document_type"] == d["document_type"] and \
               other["issuer"] == d["issuer"] and "CORRECTED" in other["title"].upper():
                return other["id"]
        return None

    # ------------------------------------------------------------------ lookups (rules find evidence by meaning, not by id)
    def docs_of(self, doc_type: str, visible: set[str] | None = None) -> list[dict]:
        """Documents of a type, in packet order, optionally limited to those received."""
        return [d for d in self.raw["documents"] if d["document_type"] == doc_type and (visible is None or d["id"] in visible)]

    def doc_of(self, doc_type: str, visible: set[str] | None = None, text: str | None = None, tax_year: int | None = None) -> dict | None:
        for d in self.docs_of(doc_type, visible):
            if tax_year is not None and d.get("tax_year") != tax_year:
                continue
            if text is not None and not any(text.lower() in p["printed_content"].lower() or text.lower() in d["title"].lower() for p in d["pages"]):
                continue
            return d
        return None

    def ev(self, doc_id: str | None, field: str) -> str | None:
        """Id of the value read from `field` on a document."""
        if not doc_id:
            return None
        return next((e for e in self.values_by_doc.get(doc_id, []) if self.values[e]["field"] == field), None)

    def val(self, doc_id: str | None, field: str, default=None):
        e = self.ev(doc_id, field)
        return self.values[e]["value"] if e else default

    def fields(self, doc_id: str | None) -> dict[str, str]:
        """field -> value id for one document."""
        return {self.values[e]["field"]: e for e in self.values_by_doc.get(doc_id or "", [])}

    def answer(self, *keywords: str) -> dict | None:
        """The questionnaire item whose question mentions all the keywords."""
        kws = [k.lower() for k in keywords]
        return next((q for q in self.questionnaire.values() if all(k in q["question"].lower() for k in kws)), None)

    def call_notes_with(self, keyword: str) -> list[tuple[str, str]]:
        """(call id, note) pairs whose note mentions the keyword."""
        return [(cid, n) for cid, c in self.calls.items() for n in c["notes"] if keyword.lower() in n.lower()]

    def page_ref(self, doc: dict | None, page: int = 1) -> list[str]:
        return [f"{doc['id']}#page{page}"] if doc else []

    @cached_property
    def doc_areas(self) -> dict[str, str]:
        from .domain import area_for_doc
        out = {}
        for d in self.raw["documents"]:
            landed = [(k, self.current.lines[k]["form"]) for e in self.values_by_doc.get(d["id"], [])
                      for k in self.current.landings.get(e, []) if k in self.current.lines]
            out[d["id"]] = area_for_doc(d, landed)
        return out
