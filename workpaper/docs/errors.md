# Errors found in the packet, and how the design surfaced them

Every item below is raised by a rule in `app/checks.py` as a **finding**: evidence refs, the lines affected, a suggested adjustment and its tax effect. Findings sit at the top of **Open items**, sorted by severity and dollar effect. *Accept and adjust* records the adjustment (with undo); *Dismiss* needs a reason and an authority; *Ask the client* sends a question to the client portal. No rule hardcodes a document id, an amount or the expected answer: each finds its evidence by document type, field name and question text, and compares two independent sources in the packet. The rules do encode what a reviewer knows to look for (RSU basis, a state move, a 1099-K inside gross receipts), so they are a review checklist made executable, not a general error detector; another household would run the same rules and need more. Effects are federal and California tax at the packet's v3 marginal rates. The HVAC finding is the exception: it uses the engine's exact what-if result.

The engine's own v3 diagnostics are shown too, but **none of the errors below appear in them**. Most come from values read with confidence 0.99.

## Errors that change the return

| # | Error | Evidence that exposes it | Rule (how it was found) | Fed tax | CA tax |
|---|---|---|---|---:|---:|
| 1 | **RSU sales taxed at zero basis.** Lots N1, N3, N4 on the Northlake 1099-B are noncovered with basis blank, and the engine used 0. The vest value was already taxed as wages. | D11 p2 (plan supplement: basis 19,100 / 19,100 / 9,420); D08 box 14 RSU 38,200; D28 p3 | Match each zero-basis noncovered lot to the stock-plan supplement by acquisition and sale dates. The engine rule says it uses the supplement "if matched", and it failed because the lot names differ (RSU-2502 vs N1). | −15,536 | −1,618 |
| 2 | **California taxes Texas wages.** All 111,300 of Halvorsen box 16 is sourced to CA. The family moved 07/14; the employer "kept California as the work state through 09/30". | D09 text; D73 paystub (CA wages 22,469 through 07/15); qa-45; residency | For W-2s whose employment spans the residency change, compare box 16 with the paystub YTD at the move. 88,831 overstated. | 0 | −5,685 |
| 3 | **SE health insurance deducted while Erik was eligible for Ngozi's employer plan.** 14,400 on Schedule 1 line 17. | qa-25 ("Yes - both of Ngozi's employers offer family coverage"); D45 family HDHP; 2024 return note | Questionnaire eligibility answer vs a non-zero SEHI line; the prior year shows the same fact. | +4,464 | +605 |
| 4 | **1099-K card receipts counted twice.** Gross receipts = books 151,300 + 1099-K 12,400. | D15 p3: Atlas paid 41,200, of which 12,400 came through Paywell, "deposited gross" into books revenue | For each 1099-K, look for its filer in the books' deposit detail. If found, and line 1 = books + 1099-K, the card amount is already in books. Also answers the 2028 exam letter. | −4,402 | −384 |
| 5 | **11,000 HVAC system replacement expensed as a repair** on the Sacramento rental. | D46 owner statement; D47 invoice (whole heat-pump system, new air handler, line set); qa-37; call notes | Single item in a repairs line above the 2,500 de minimis safe harbor that describes a building system. Effect taken from the engine's `hvac_improvement` what-if. | +3,633 | +896 |
| 6 | **California estimates overstated by 3,500.** The 09/15/2025 Web Pay payment was designated tax year 2024, and FTB holds it as a 2024 credit. | D68 (pay5_year 2024); FTB account record | Return line vs the FTB account's tax-year-2025 payments. | CA payments −3,500 | |
| 7 | **Home property tax not prorated.** 13,420 deducted, but the seller credited 6,912 for 01/01–07/07 at closing. SALT falls below the 40,000 cap. | D54 buyer closing statement; D57 / D58 | Buyer closing statement tax credit vs the deducted bill; cap recomputed. | +1,462 | +332 |
| 8 | **Federal estimates overstated by 1,000.** No confirmation for January, so the engine used the client's "4,000 I think". | IRS transcript (D69): 3,000 on 2026-01-15; qa-41 | Return line vs IRS transcript code 670 payments. | Fed payments −1,000 | |
| 9 | **Mileage log page counted twice.** Page 3 is "a second scan of the May–Aug sheet", and both page totals (3,700 each) were added: 11,800 miles instead of 8,100. | D23 p2 and p3 (identical text) | Pages in one document that are ≥85% identical, where a line sums values from both. Car expense −2,590. | +919 | +80 |
| 10 | **Donated car claimed at the client's 6,000 estimate.** The charity sold it for 2,900 (1098-C box 4a checked). | D66; qa-39; call notes | Vehicle gift on Form 8283 vs 1098-C box 4c when the car was sold. | +806 | +149 |
| 11 | **Same 1,840 of interest reported twice.** Northlake composite (D28) and Northlake Bank 1099-INT (D29) are one bank-sweep account. | Both pages say "account ending 7731" | Equal-amount payer lines from different documents that name the same account. | −640 | −127 |
| 12 | **Payoff interest added on top of the 1098 that includes it** (2,150). | D56: "Interest is reported on the 2025 Form 1098"; D55 box 1 "includes … interest paid at payoff" | Mortgage-interest line cites both a payoff statement and the lender's 1098 that says it is included. | +559 | +103 |
| 13 | **Personal share of phone, internet and Spotify deducted in full.** | Call notes: phone 70% business, internet 50%, Spotify personal; D15 detail | Business-use percentages from the call notes vs books lines deducted at 100%. | +541 | +47 |
| 14 | **Swedish interest converted at the 2024 exchange rate** (10.56, not 9.86). | Line cites `ref:fx.SEK.2024_average` | A 2025 line referencing a prior-year average rate. | +43 | +9 |
| 15 | **Unread page 32 of the corrected Meridian 1099** (in the document view the page is dashed and its lot row has no anchors): lot M18 (proceeds 250, basis 310) is missing. This is the engine's "summary vs detail" difference of exactly 250. | D31 p32 | Document extraction "partial" plus amounts on the unread page. | −21 | −2 |
| 16 | **Crypto lot C6 at zero basis.** The client later supplied a 3,050 cost from March 2021 (long-term), arriving 06/30 after v3. | msg-07; D35 | Zero-basis digital asset lot plus a later client message with a date and cost. Shown as a judgment call (support is a bank statement line). | −1,312 | −104 |

**If all are accepted:** federal goes from **4,220 owed to a 4,264 refund**. California refund goes from **8,256 to 10,455** (tax 18,874 → 13,175; payments −3,500). These are estimates at marginal rates: lines computed by engine logic are flagged for recompute rather than recalculated by hand.

## Errors with no dollar effect that would still break filing

| Error | How it surfaced |
|---|---|
| **Theo's SSN typed wrong in the organizer** (666-74-3309; the card and the 2024 return say 666-74-3390). This is the cause of the scripted e-file rejection R0000-504-02. | The SSN rule compares every household SSN with every document that names the person. It fires **before filing** from the 2024 return (D06), weeks before the card (D71) arrives. If you fix it, the replay's rejection doesn't happen and the return is accepted. If you don't, the rejection arrives and the Filing page links it to the fix. |
| **Little Sprouts EIN misread** as 74-3829516 (printed 74-3829156), confidence 0.97, on Form 2441. | The "second read" rule: every extracted value must appear on its page. Of the 3,012 values (checkboxes aside), only 2 fail: this one and the next. For this one it shows the transposed number it finds on the page. |
| **St. Brigid gift amount ambiguous** ("$?,500.00", confidence 0.41). The acknowledgment also lacks the goods-or-services statement required at 250 or more. | Second read plus the acknowledgment rule. The client confirmed 1,500 on 07/01 (msg-08). The substantiation gap stays a judgment call: ask the parish for a corrected letter. |
| **Care provider name** "Bright Oak Preschool" on Form 2441 vs "Bright Oak Kids Club" on the statement. | Provider name check. |

## Judgment calls, outside filings and process gaps the design forces into the open

- **Excess SEP contribution of 2,786** (18,000 contributed vs a 15,214 limit). 6% excise each year unless withdrawn (Form 5329). The limit moves with every Schedule C fix.
- **2023 Form 3520 for the Swedish inheritance**: the prior preparer's open item, never resolved. Outside the engagement, but carried forward and listed.
- **Questionnaire answers contradicting documents:** qa-14 "no sales" (282 sales), qa-15 "didn't really sell" (12 crypto dispositions), qa-31 "no prior IRA basis" (the 2024 Form 8606 and 5498 show 7,000; the engine was right), qa-39, qa-41.
- **2024 home office overstated** (300 sq ft claimed; the room is 220).
- **Outside filings identified:** FBAR, late 1099-NECs for two contractors, Ada's own return, Oregon/Arizona composites (none required), Form 8801 next year.
- **Planning:** electing §179 instead of bonus depreciation saves California 1,050 with no federal cost (the engine's what-if).
- **Process:** Form 8867 due diligence not done; California AMT on the ISO exercise not computed by the engine.

## What passed (recorded as machine verification)

W-2 box 1, box 2 and box 17 totals; excess social security; Form 8938 values at the year-end rate; all 85 engine sums re-added from their inputs; straight-line depreciation for the Sacramento building and roof; S corporation basis rolled from 2022 using the late 2023 K-1 (2,300 at 1/1/2025); backdoor Roth pro-rata (taxable 26); capital-loss and passive-loss carryovers vs the 2024 return; extension payment vs the IRS transcript; Brightpath's 260 lots tie to its summary exactly.
