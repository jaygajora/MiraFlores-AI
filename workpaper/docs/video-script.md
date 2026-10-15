# Video walkthrough: script and talking points (about 8 minutes)

Record at 1440×900. Start from a fresh demo: as Jo Kimura (administrator), go to Firm and click Reset demo. Speak in your own words; the bullets are prompts, not lines to read.

## 1. The idea (45 s): Open items, as Priya (preparer)
- "A return is a few hundred numbers, each resting on other numbers down to words on a page. I built the workpaper as that graph, plus an append-only log of everything people do to it."
- Point at the totals strip: the engine's v3 numbers, and below them what the workpaper says once our adjustments count.
- "The home screen is a queue, not a form: what's open, sorted by severity and tax effect. A new hire starts here."

## 2. Trace a number to its source (90 s)
- Open the RSU finding. Read the summary: the 1099-B left basis blank, and the engine used zero.
- Click lot F8949.B.N1, then a source, so the chain at the top grows: finding › line › extracted value. The page renders with the words highlighted.
- "There are no real PDFs, so each page is laid out from its printed text as a form: labelled boxes, ledger tables. Every extracted value is anchored to its box, so the trace ends on the exact cell. The Text toggle shows the verbatim print as ground truth. The packet's position boxes are random, so I didn't lay pages out with them. But the renderer contract is (doc, page, anchors), and a real PDF renderer would drop in and place the same anchors by position."
- Open D31 and scroll to page 32: the unread page shows lot M18 as a row with no anchors. That's the missing sale.
- Go back up the chain to the line and show *Where it goes*: solid arrows are sums, dashed ones are engine computations.
- Open Documents, then D23 (mileage log): values colored by where they landed. Point out page 3, the second scan that was counted twice.

## 3. Checks that don't trust the engine (60 s)
- Open Checks. "Each rule compares two independent sources: printed page against extraction, books against 1099-K, paystub against W-2 box 16, IRS transcript against the return."
- "None of these errors are in the engine's own diagnostics, and most rest on values read with 0.99 confidence."
- Scroll to *Proved by recalculation*: these become machine verification on the lines they cover.

## 4. Change without losing anything (75 s)
- Select several findings, click Accept and adjust all, then Undo in the toast. Then accept again.
- Open a changed line: the engine value is struck through, the workpaper value is shown, and the adjustment records who, why, the authority and the effect.
- Lines downstream are exact where the arithmetic is plain sums; where the engine's logic applies they show "needs engine recompute". "I chose not to fake engine math: the README says to estimate effects with marginal rates, so totals are honest estimates."
- Changes, then Compare versions: v2 against v3 with the cause of each change, then v3 against the workpaper. Show *Swings vs 2024* with bulk explain.

## 5. People and roles (75 s)
- Switch to Daniel (reviewer). Approvals appear for his role. Try approving something he made himself: it's refused.
- Add a blocking review note on SchC.1, then show the filing gate turning red.
- Sign off an area as Priya, then make an adjustment in that area. The sign-off reopens on its own, because it stored a fingerprint of what was signed.
- Switch to Marcus (no clearance): SSNs are masked and Reveal isn't offered. Switch to Helen and reveal a W-2, then show Firm, where the reveal is in the audit log.
- Switch to Ngozi (client): the portal shows only her questions, her approval and her documents.

## 6. Filing and after (90 s)
- Filing page: the stages and gates. Theo's SSN finding had already come up from the 2024 return. Fix it.
- As Helen, send to the client. As Ngozi, approve. As Helen, transmit. Advance the clock: the scripted rejection doesn't happen because the SSN was fixed; the return is accepted and sealed. (Alternatively, show it unfixed: the rejection arrives and links to the fix.)
- Try an adjustment: refused, because the return is sealed. Start an amendment.
- Advance to 2028: the Letter 566 arrives. Open the self-contained response record (gross-receipts reconciliation and the noncash gifts, with evidence and audit trail). "It needs no app to read."
- *Carry forward to 2026*: carryovers keep their sources, plus open items, client facts and the estimate plan.

## 7. Technical decisions and tradeoffs (90 s)
- **Event sourcing in SQLite, hash-chained.** It gives undo, history, "since I last looked", sign-off reopening, sealing and notice exports from one mechanism. Tradeoff: state is a fold of the log. At thousands of events per return that is milliseconds (cached per log head); at firm scale I'd keep snapshots.
- **Packet loaded as delivered, never mutated.** The graph index (reverse edges, value landings, inferred signs) is built at load. I inferred each sum's signs from the engine's own numbers and pinned the two the data couldn't decide. A test re-adds all 85 sums.
- **Rate-based effects, not a re-implemented engine.** I could have rebuilt tax computation; I chose to propagate exactly where the arithmetic is plain sums and flag the rest. The engine is the source of truth, and pretending otherwise would make the workpaper less trustworthy.
- **Checks are small rules with evidence**, each tested. Several parse printed text as a stand-in for structured extraction of those fields; the evidence chain is the same either way.
- **Stack:** FastAPI with SQLite and pydantic-validated commands; React 19 with TypeScript (strict), bundled by esbuild and styled with Tailwind, where the theme's colors are evidence states. It runs as one process with one SQLite file. Tradeoffs: one process means no horizontal scaling (fine for one engagement; a real product would put the log in Postgres), there is no code-splitting, and live updates are SSE on the log head with refetch (simple and reliable, not fine-grained).
- **Roles are enforced on the server** for every command; the UI only mirrors them. Identity is a role switcher (an X-User header) as the brief asked; real auth would replace that header.
- **What I'd do next:** rerun the engine on adjustments instead of estimating, a real PDF renderer with the same anchors, structured extraction for the fields the rules parse, finer-grained live updates, and firm-wide multi-client views.

## How I used AI
I worked with Claude as a pair: it read the packet with me, proposed the error hunt (I verified each finding against the documents), and wrote much of the code, which I reviewed, ran and tested (29 unit and API tests, lint, strict type-checking, and a browser smoke test that drives every role at desktop and phone width, all in CI). The design decisions and tradeoffs above are ones I made and can defend.
