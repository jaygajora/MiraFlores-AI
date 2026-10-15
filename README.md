# Tax workpaper: Okafor-Lindqvist 2025

A web-native workpaper for one household's return. It proves where every number came from, what was done to it, who checked it, and what is still open. It loads the Miraflores packet exactly as delivered and saves everything people do as an append-only, hash-chained event log.

- **Core idea and data model:** [docs/core-idea.md](docs/core-idea.md)
- **Errors found and how the design surfaced them:** [docs/errors.md](docs/errors.md)

## Run it

```sh
pip install -r requirements.txt
npm install && npm run build      # React + Tailwind front end -> static/app/ (skip if static/app/ is already built)
uvicorn app.main:app --port 8000
# open http://localhost:8000
```

Run one server process. The log is a single SQLite file and live updates fan out in-process, so `--workers 1` (the default) is required.

The event log is written to `var/workpaper.db` (override with `DB_PATH`). The packet path is set with `PACKET_PATH` (default `data/okafor_lindqvist_2025_packet.json`).

### Using it
- **Role switcher** (top right): preparer (Priya), second preparer without sensitive-data clearance (Marcus), reviewer (Daniel), partner (Helen), administrator (Jo), quality reviewer (Sam, active from 2027), and the two clients.
- **Season clock** (top bar): the workpaper opens the morning after v3 (2026-06-24). *Next* (partner or administrator) replays the next scripted event: client messages, approval, e-file acknowledgments, payments, quality review, next year, and the 2028 examination letter.
- **Reset demo**: Firm page, as the administrator.
- Press `/` to search, and click any number or ref to trace it.

## Test

```sh
pip install -r requirements-dev.txt
ruff check .                                   # lint (config in pyproject.toml)
python -m unittest discover -s tests -v        # 29 unit and API tests
npm run typecheck                              # TypeScript, strict
python tests/e2e_smoke.py http://127.0.0.1:8765   # browser flows against a running server (Playwright)
```

The unit and API tests cover packet integrity (all 85 engine sums re-add), page layout for all 199 pages, every planted error being found, effects, role rules, command validation (422s), stable finding ids, sign-off reopening, blocking notes, bulk actions with undo, security headers, masking, and a whole season from findings through filing, sealing, amendment and the 2028 notice.

The browser smoke test drives the UI by role and accessible name as each role (preparer, partner, administrator, client) and at phone width. It fails on any page error, console error, native `alert/confirm/prompt`, or horizontal page scroll.

CI (`.github/workflows/ci.yml`) runs the lint, the tests, the front-end build, and the browser test.

## Deploy

One Docker image (`Dockerfile`): a Node stage builds the front end, then a slim Python stage serves the API and the built UI. The container runs as an unprivileged user and has a health check.

- **Render:** `render.yaml` (Docker web service with a 1 GB disk at `/data` for the log).
- **Fly.io:** `fly launch --copy-config --no-deploy && fly volumes create workpaper_data --size 1 && fly deploy`.

Without a persistent disk the app still works, but the log resets on restart.

## Layout

```
app/
  packet.py    load the packet; lineage graph (inputs, consumers, landings, inferred sum signs, ref resolver)
  store.py     append-only SQLite event log with a hash chain; attached files
  state.py     commands -> events; projection -> state; effective values, findings status, sign-offs, steps, filing
  checks.py    independent checks (findings with evidence and suggested adjustments) and recalculations that pass
  reports.py   the records a CPA expects, generated from the graph and the log
  layout.py    lays out each simulated page as a form (boxes, ledger tables) with character-span anchors
  views.py     read models: line trace, value, document, return tree, compare, search, notice record, client copy, roll-forward
  auth.py      roles and permissions, masking
  domain.py    review areas, effect categories
  main.py      FastAPI routes, SSE live updates, static UI
  commands.py  typed commands (pydantic): every write is validated before it can become an event
web/
  src/         React 19 + TypeScript UI, bundled by esbuild
    api.ts       API client, app store (useSyncExternalStore), hash routing, live updates
    ui.tsx       primitives: Button, Pill, Ref, Modal, ConfirmDialog, ReasonForm, DataTable...
    paper.tsx    the simulated source page (form view and text view) with clickable value anchors
    drawer.tsx   the trace drawer: line, value, document, finding and other refs
    views_*.tsx  the sections
  styles.css   Tailwind entry: theme tokens (light and dark), self-hosted fonts, element defaults
tailwind.config.cjs   colors are evidence states (see the comment there)
static/        index.html, fonts (IBM Plex, OFL), and the built app in static/app/
tests/
docs/
```

`npm run build` type-checks, bundles `web/src/main.tsx` to `static/app/main.js`, and builds `static/app/app.css` with Tailwind. `npm run watch:js` and `npm run watch:css` rebuild on save.

## Notes and limits

- **Tax effects** of adjustments use the packet's per-dollar rates for v3 (or the engine's exact what-if result where one exists). The engine can't be rerun here, so lines computed by engine logic downstream of an adjustment are flagged "needs engine recompute" rather than recalculated by hand.
- **Source documents** are simulated from `printed_content` and laid out as paper (`app/layout.py`): a heading, a grid of labelled boxes for form fields, and ledger tables for lots, trips and dated payments. Every extracted value is anchored to its box or cell. A *Text* toggle shows the printed content verbatim. The packet's `position` boxes are synthetic and random, so they cannot drive layout; the renderer contract `(doc, page, text, value anchors)` lets a real PDF renderer replace this and place the same anchors by `position`.
- **Identity** is a role switcher (an `X-User` header), as the brief asked for. Every permission is enforced on the server. Links the browser opens directly (exports, attachments) carry the user as a query parameter because a link cannot send a header; real authentication (sessions or OIDC) would replace both.
- **Security**: strict Content Security Policy (scripts, styles and fonts from this origin only; nothing inline), `nosniff`, no framing; uploaded files are served as downloads in a sandbox; sensitive values are masked unless the user has clearance, and every reveal is logged.
- **Accessibility**: every interactive thing is a real button or link with an accessible name; dialogs trap focus and close on Escape; search is a keyboard combobox; status changes are announced; color is never the only signal.
- **California AMT** isn't computed (an engine limitation); it is flagged.

## How AI was used

Built with Claude (Anthropic) as a pair programmer: reading the packet, proposing and cross-checking the error hunt, and writing much of the code and docs. Every finding was verified against the packet's printed pages, and the behavior is covered by tests and headless-browser click-throughs.
