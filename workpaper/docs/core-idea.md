# Core idea and data model

## The idea: the return is a graph of claims, and the workpaper is the log of what people did to it

A tax return is a few hundred numbers. Each one is a claim ("wages are 212,400") that rests on other claims, down to words printed on a page. A spreadsheet hides that structure; this workpaper makes it the interface.

- **Every number is a node with lineage.** Return lines point to the lines they are computed from and to the evidence they cite: extracted values (document, page, field, confidence), client answers, prior-year records, agency records, engine parameters. Following a number down and following a document up are the same graph walked in two directions. In the UI this is the **trace chain**: click any number, follow its evidence hop by hop, and the path stays visible at the top of the drawer (`F1040.11 › F1040.7 › SchD.16 › F8949.B.N1 › ev-0493 › D28 p3`), ending at the highlighted words on the simulated page.
- **Nothing is overwritten. Every action is an event.** Adjustments, verifications, notes, client questions and answers, sign-offs, decisions, document dispositions, filing steps and the scripted season are rows in one append-only, hash-chained log. Current state is a projection of that log. From that one choice:
  - The engine's value is never lost: an adjustment is a new event with who, why, the authority, and its tax effect.
  - Undo appends an event that cancels earlier ones, so a bulk action undoes as one unit.
  - "What changed since I last looked" is a log query from your last-seen marker. Version compare diffs any two of 2024, v1, v2, v3 and the live workpaper.
  - A sign-off stores a fingerprint of what was signed (the area's values, adjustments and dispositions). When any of it changes, the sign-off reopens by itself.
  - Filing seals the record (fingerprint plus log head hash), and later changes must go through an amendment. A notice response is a self-contained export of the relevant slice.
- **Checks that do not trust the engine.** A rule library reads printed pages, client answers, call notes, agency transcripts and prior years, then raises findings with evidence, affected lines and a suggested adjustment with its effect. Recalculations that agree become machine verification on the lines they cover.
- **The home screen is a queue, not a form.** Open findings, approvals, blocking notes, client answers, unaccounted documents and reopened sign-offs, sorted by severity and tax effect. A new hire can start there on day one, while a 20-year CPA can go straight to any number and its proof.

## Data model

| Store | What it holds | Mutable? |
|---|---|---|
| **Packet** (JSON, loaded as delivered) | Documents and pages, 3,012 extracted values, three engine versions with lines (`inputs`, `sources`, `rule`), what-ifs, prior years, agency records, firm, timeline | Never |
| **Graph index** (built at load) | `consumers` (reverse of inputs), `landings` (value to lines), inferred signs for every sum so deltas propagate exactly, ref resolver for every ref format in the README | Derived |
| **Event log** (SQLite, `events`) | `seq, id, at, sim_at, actor, kind, target, batch, data, prev_hash, hash` | Append-only |
| **Files** (SQLite, `files`) | Attached evidence, with sha256 | Append-only |
| **Projection** (in memory, per log head) | Adjustments, verifications, notes, questions, dispositions, decisions, sign-offs, filing state, clock | Derived |

**Values.** Workpaper value = engine value + adjustments, propagated exactly through sums and carries (signs inferred from the engine's own numbers, and all 85 sums re-add). Propagation stops where engine logic begins (tax tables, limits, phase-outs). Those lines are flagged "needs engine recompute" instead of being faked. The tax effect of each adjustment uses the packet's per-dollar rates (or the engine's exact what-if result when one exists), so totals are honest estimates until the engine reruns.

**Refs** are plain strings (`F1040.11`, `ev-0016`, `D28#page3`, `qa-14`, `py:/...`, `agency:/...`, `asset:SAC-BLDG`), so any event can point at anything, and evidence can come from any year or a related return.

**Documents** are laid out from `printed_content` as paper: a heading, a grid of labelled boxes, and ledger tables for lots, trips and payments. A Text toggle shows the verbatim print. Each extracted value is anchored by its character span to a box or cell, so a trace ends on the exact box. The packet's `position` boxes are random, so they can't drive layout. The renderer contract `(doc, page, text, value anchors)` lets a real PDF renderer replace this one and place the same anchors by `position`.

**Roles** are enforced on the server for every command: preparer, reviewer, partner, firm administrator, quality reviewer, client. The rules include no self-review, the partner threshold, blocking notes, masked sensitive data with every reveal logged, and staff start dates against the season clock.
