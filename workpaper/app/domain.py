"""Domain configuration: review areas, tax-effect categories, line classification."""
from __future__ import annotations

import re

# Review areas follow the firm's budget buckets so time, sign-off and status line up.
AREAS = [
    ("intake_and_engagement", "Intake and engagement"),
    ("wages_and_stock_compensation", "Wages and stock compensation"),
    ("investments_and_digital_assets", "Investments, IRA and foreign"),
    ("business", "Business (Schedule C)"),
    ("rentals_and_sale", "Rentals and property sales"),
    ("pass_throughs_and_basis", "K-1s and basis"),
    ("deductions_and_credits", "Deductions and credits"),
    ("tax_and_payments", "Tax, payments and penalty"),
    ("california", "California (540NR)"),
    ("partner_review", "Partner review"),
]
AREA_TITLES = dict(AREAS)


def area_for_line(key: str, form: str) -> str:
    if form in ("SchCA540NR", "F540NR", "ScheduleS", "FTB3885A", "FTB5805"):
        return "california"
    if form in ("SchC", "SchSE", "F4562-C"):
        return "business"
    if form == "Sch1":
        return "business" if key in ("Sch1.15", "Sch1.16", "Sch1.17", "Sch1.3") else (
            "investments_and_digital_assets" if key == "Sch1.13" else "rentals_and_sale" if key == "Sch1.5" else "tax_and_payments")
    if form in ("F4797", "F4562-E", "F8582"):
        return "rentals_and_sale"
    if form == "SchE":
        return "pass_throughs_and_basis" if re.match(r"SchE\.(28|32)", key) else "rentals_and_sale"
    if form == "F7203" or key == "F8949.F.SCORP" or key == "F8949.F.total" or key == "SchD.12":
        return "pass_throughs_and_basis"
    if form in ("SchB", "SchD", "F8949", "F8938", "F8960", "F8606", "F8889"):
        return "investments_and_digital_assets"
    if form == "F8995":
        return "business" if key.endswith(".1") else "pass_throughs_and_basis" if key.endswith(".2") else "deductions_and_credits"
    if form in ("SchA", "F8283", "F8812", "F8863", "F2441", "F8867"):
        return "deductions_and_credits"
    if form == "F1040":
        n = key.split(".", 1)[1]
        if n in ("1a", "1z"):
            return "wages_and_stock_compensation"
        if n in ("2b", "3a", "3b", "4a", "4b", "7"):
            return "investments_and_digital_assets"
        if n in ("12", "13", "14", "19"):
            return "deductions_and_credits"
        return "tax_and_payments"
    if form in ("F8959",) or key == "Sch3.11":
        return "wages_and_stock_compensation"
    if form == "F6251":
        return "wages_and_stock_compensation" if key == "F6251.2i" else "tax_and_payments"
    if form == "Sch3" and key == "Sch3.1":
        return "investments_and_digital_assets"
    return "tax_and_payments"


DOC_AREA = {
    "engagement_letter": "intake_and_engagement", "consent_7216": "intake_and_engagement",
    "irs_ip_pin_notice": "intake_and_engagement", "identity_document": "intake_and_engagement",
    "prior_year_return": "intake_and_engagement", "prior_workpaper": "intake_and_engagement",
    "W-2": "wages_and_stock_compensation", "stock_plan_supplement": "wages_and_stock_compensation",
    "3921": "wages_and_stock_compensation", "3922": "wages_and_stock_compensation",
    "paystub": "wages_and_stock_compensation",
    "books_profit_loss": "business", "books_transaction_detail": "business", "1099-NEC": "business",
    "1099-K": "business", "invoice": "business", "mileage_log": "business", "client_note": "business",
    "insurance_statement": "business", "retirement_contribution": "business", "books_report": "business",
    "1099-composite": "investments_and_digital_assets", "1099-INT": "investments_and_digital_assets",
    "1099-DA": "investments_and_digital_assets", "transaction_export": "investments_and_digital_assets",
    "foreign_bank_statement": "investments_and_digital_assets", "1099-R": "investments_and_digital_assets",
    "5498": "investments_and_digital_assets", "1099-SA": "investments_and_digital_assets",
    "5498-SA": "investments_and_digital_assets",
    "K-1-1065": "pass_throughs_and_basis", "K-1-state-supplement": "pass_throughs_and_basis",
    "K-1-1120S": "pass_throughs_and_basis",
    "rental_owner_statement": "rentals_and_sale", "1098": "deductions_and_credits",
    "property_tax_bill": "rentals_and_sale", "rental_ledger": "rentals_and_sale",
    "closing_statement_seller": "rentals_and_sale", "1099-S": "rentals_and_sale",
    "closing_statement_buyer": "deductions_and_credits", "payoff_statement": "deductions_and_credits",
    "property_tax_receipt": "deductions_and_credits", "1098-T": "deductions_and_credits",
    "letter": "deductions_and_credits", "dependent_care_statement": "deductions_and_credits",
    "donation_receipt": "deductions_and_credits", "1098-C": "deductions_and_credits",
    "payment_confirmation": "tax_and_payments", "irs_transcript": "tax_and_payments",
    "irs_notice": "tax_and_payments",
}


def area_for_doc(doc: dict, landed_lines: list[tuple[str, str]] | None = None) -> str:
    """Review area for a document: where its values land on the return, else its type's usual area."""
    if landed_lines:
        counts: dict[str, int] = {}
        for key, form in landed_lines:
            a = area_for_line(key, form)
            counts[a] = counts.get(a, 0) + 1
        return max(counts, key=lambda a: counts[a])
    return DOC_AREA.get(doc["document_type"], "intake_and_engagement")


# ---------------------------------------------------------------------- tax effects
# The engine cannot be rerun. The packet gives per-dollar marginal rates for the
# current version; an adjustment's effect is its change in the right category x
# rate. Payments do not change tax, they change the balance.
EFFECT_CATEGORIES = {
    "wages": "Wages", "interest": "Interest", "schc_profit": "Schedule C profit",
    "stcg": "Short-term capital gain", "ltcg": "Long-term capital gain",
    "ordinary_income": "Other ordinary income", "adjustment": "Adjustment to income (deduction)",
    "salt": "State and local taxes", "itemized": "Itemized deduction",
    "ca_source_income": "California-source income", "payments_fed": "Federal payment",
    "payments_ca": "California payment", "none": "No tax effect", "exact": "Engine what-if (exact)",
}


def effect_of(category: str, basis_fed: float, basis_ca: float | None, rates: dict) -> dict:
    """Tax effect of a change. basis_* is the change measured in the category's units
    (e.g. +2,590 of Schedule C profit). Returns tax and payment deltas per jurisdiction."""
    basis_ca = basis_fed if basis_ca is None else basis_ca
    out = {"fed_tax": 0.0, "ca_tax": 0.0, "fed_payments": 0.0, "ca_payments": 0.0}
    if category == "payments_fed":
        out["fed_payments"] = basis_fed
    elif category == "payments_ca":
        out["ca_payments"] = basis_ca
    elif category in rates:
        out["fed_tax"] = round(basis_fed * rates[category]["federal_per_dollar"])
        out["ca_tax"] = round(basis_ca * rates[category]["california_per_dollar"])
    return out


def category_for_line(key: str, form: str) -> str:
    """Default effect category when someone adjusts a line by hand."""
    if key in ("F1040.25a", "F1040.26", "Sch3.10", "Sch3.11"):
        return "payments_fed"
    if key in ("F540NR.71", "F540NR.72", "F540NR.73"):
        return "payments_ca"
    if form == "SchCA540NR" and key.endswith(".E"):
        return "ca_source_income"
    if form in ("SchC", "F4562-C"):
        return "schc_profit"
    if form == "SchB" or key == "F1040.2b":
        return "interest"
    if form == "SchA" or form == "F8283":
        return "itemized"
    if form == "Sch1":
        return "adjustment"
    if key.startswith("F8949.A") or key.startswith("F8949.B") or key.startswith("F8949.H") or key.startswith("SchD.1") or key.startswith("SchD.2") or key.startswith("SchD.3"):
        return "stcg"
    if form in ("F8949", "SchD", "F4797"):
        return "ltcg"
    if key.startswith("F1040.1"):
        return "wages"
    return "ordinary_income"


# Expense-type lines reduce the parent total; used to translate a line delta into
# a category delta (e.g. +100 of expense = -100 of Schedule C profit).
def profit_sign(key: str, form: str) -> int:
    if form == "SchC" and key not in ("SchC.1", "SchC.5", "SchC.7", "SchC.29", "SchC.31") and not key.startswith("SchC.4"):
        return -1
    if form == "F4562-C":
        return -1
    if form == "SchE" and re.match(r"SchE\.(9|10|11|12|13|14|15|16|17|18|19|20)", key):
        return -1
    return 1


SENSITIVE_FIELDS = ("ssn", "ip_pin", "account", "routing", "ein_full")
