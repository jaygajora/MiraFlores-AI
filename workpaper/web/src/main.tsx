import { Component, StrictMode, useEffect, useId, useState, type ErrorInfo, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { can, closeDrawer, cmd, dismissToast, getState, go, loadBoot, openRef, setUser, startStream, useApi, useApp, useBoot } from "./api";
import { Drawer } from "./drawer";
import type { Overview } from "./types";
import { Button, ErrorNote, Loading, cx, when } from "./ui";
import { Changes, ClientPortal, Filing, Firm, Records, Review } from "./views_more";
import { Checks, DocView, Documents, Home, ReturnView } from "./views_work";

const NAV: [string, string][] = [["", "Open items"], ["return", "Return"], ["documents", "Documents"], ["checks", "Checks"], ["review", "Review"],
  ["changes", "Changes"], ["records", "Records"], ["filing", "Filing"], ["firm", "Firm"]];

function App() {
  const boot = useApp((s) => s.boot);
  const route = useApp((s) => s.route);
  const drawerOpen = useApp((s) => s.drawer.length > 0);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    loadBoot().catch((e: Error) => setFailed(e.message));
    return startStream();
  }, []);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement).closest("input,textarea,select,[contenteditable]");
      if (e.key === "/" && !typing) { e.preventDefault(); document.getElementById("search")?.focus(); }
      if (e.key === "Escape" && getState().drawer.length && !document.querySelector("[role=dialog]")) closeDrawer();
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);

  useEffect(() => {
    if (boot) document.title = `${boot.packet.name.split(" household")[0]} ${boot.household.tax_year} workpaper`;
  }, [boot]);

  if (failed && !boot) return <div className="p-7"><ErrorNote>Could not load the workpaper: {failed}</ErrorNote><Button onClick={() => location.reload()}>Try again</Button></div>;
  if (!boot) return <Loading label="Loading the workpaper…" />;
  const isClient = boot.me.role === "client";
  const [section, ...rest] = route.split("/");
  return (
    <div className={cx("grid h-screen grid-cols-1 grid-rows-[auto_auto_1fr] md:grid-rows-[52px_1fr]",
      isClient ? "grid-rows-[auto_1fr] md:grid-cols-1" : "md:grid-cols-[172px_1fr]", drawerOpen && !isClient && "xl:grid-cols-[172px_1fr_min(620px,46vw)]")}>
      <a href="#main" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}
        className="sr-only z-50 rounded bg-surface px-3 py-2 focus:not-sr-only focus:fixed focus:left-2 focus:top-2">Skip to content</a>
      <TopBar />
      {!isClient && (
        <nav aria-label="Sections" className="print-hide flex overflow-x-auto border-b border-rule bg-surface md:flex-col md:border-b-0 md:border-r md:py-3">
          {NAV.map(([r, t]) => {
            const on = section === r || (r === "documents" && section === "doc");
            return (
              <a key={r} href={`#${r}`} aria-current={on ? "page" : undefined}
                className={cx("whitespace-nowrap border-b-[3px] px-3 py-2 text-ink no-underline hover:bg-sunk md:border-b-0 md:border-l-[3px] md:px-[18px] md:py-[7px]",
                  on ? "border-evidence bg-sunk font-semibold" : "border-transparent")}>
                {t}
              </a>
            );
          })}
        </nav>
      )}
      <main id="main" tabIndex={-1} className="min-w-0 overflow-auto outline-none">
        <ErrorBoundary key={route}>
          {isClient ? <ClientPortal /> : <Route section={section} rest={rest} />}
        </ErrorBoundary>
      </main>
      {!isClient && <ErrorBoundary><Drawer /></ErrorBoundary>}
      <Toast />
    </div>
  );
}

function Route({ section, rest }: { section: string; rest: string[] }) {
  switch (section) {
    case "return": return <ReturnView form={rest[0]} />;
    case "documents": return <Documents />;
    case "doc": return <DocView id={rest[0]} />;
    case "checks": return <Checks />;
    case "review": return <Review />;
    case "changes": return <Changes tab={rest[0]} />;
    case "records": return <Records id={rest[0]} />;
    case "filing": return <Filing />;
    case "firm": return <Firm />;
    default: return <Home />;
  }
}

function TopBar() {
  const boot = useBoot();
  const u = boot.me;
  const isClient = u.role === "client";
  const { data: ov } = useApi<Overview>(isClient ? null : "/api/overview");
  const household = boot.packet.name.split(" household")[0];
  return (
    <header className="print-hide col-span-full flex min-w-0 flex-wrap items-center gap-2 border-b border-rule bg-surface px-4 py-2 md:flex-nowrap md:gap-4 md:py-0">
      <div className="whitespace-nowrap text-[15px]"><b>{household}</b> <span className="text-muted">{boot.household.tax_year} {boot.household.filing_status === "married_filing_jointly" ? "joint return" : "return"}</span></div>
      {!isClient && <Search />}
      <Clock ov={ov} />
      {ov && ov.presence.length > 0 && (
        <ul aria-label="Also here now" className="flex gap-1">
          {ov.presence.map((p) => (
            <li key={p.name} title={`${p.name}: ${p.where}`} className="grid h-[26px] w-[26px] place-items-center rounded-full bg-evidence-tint text-2xs font-semibold text-evidence">
              <span aria-hidden>{p.name.split(" ").map((x) => x[0]).join("")}</span><span className="sr-only">{p.name}, viewing {p.where}</span>
            </li>
          ))}
        </ul>
      )}
      <label className="ml-auto flex items-center gap-1.5">
        <span className="text-muted">Acting as</span>
        <select className="max-w-[200px] md:max-w-[280px]" value={u.id} onChange={(e) => setUser(e.target.value)} aria-label="Role switcher">
          {boot.users.map((x) => (
            <option key={x.id} value={x.id}>{x.name}, {x.role_title}{x.credential ? ` (${x.credential})` : ""}{!x.clearance && x.role !== "client" ? ", no clearance" : ""}</option>
          ))}
        </select>
      </label>
    </header>
  );
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

type Hit = { kind: string; ref: string; title: string; sub?: string };

/** Search as an ARIA combobox: arrow keys move through results, Enter opens one, Escape closes. */
function Search() {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(-1); // no option highlighted until the arrow keys move
  const [open, setOpen] = useState(false);
  const dq = useDebounced(q.trim(), 200);
  const { data: res } = useApi<Hit[]>(dq.length >= 2 ? `/api/search?q=${encodeURIComponent(dq)}` : null);
  const listId = useId();
  const shown = open && q.trim().length >= 2 && res;
  const choose = (r: Hit) => {
    setQ(""); setOpen(false);
    if (r.kind === "document") go(`doc/${r.ref}`); else openRef(r.ref, true);
  };
  const onKey = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (!res?.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(res.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(-1, a - 1)); }
    else if (e.key === "Enter" && shown) { e.preventDefault(); choose(res[Math.max(0, active)]); }
    else if (e.key === "Escape") { e.stopPropagation(); setOpen(false); }
  };
  return (
    <div className="relative order-last max-w-none flex-1 basis-full md:order-none md:max-w-[520px] md:basis-auto">
      <input id="search" type="search" role="combobox" aria-expanded={!!shown} aria-controls={listId} aria-autocomplete="list"
        aria-activedescendant={shown && active >= 0 ? `${listId}-${active}` : undefined} aria-label="Search"
        className="w-full bg-sunk px-2.5 py-1.5" placeholder="Search lines, documents, findings, answers  ( / )"
        value={q} onChange={(e) => { setQ(e.target.value); setActive(-1); setOpen(true); }} onKeyDown={onKey}
        onBlur={() => setTimeout(() => setOpen(false), 150)} onFocus={() => setOpen(true)} />
      {shown && (
        <ul id={listId} role="listbox" aria-label="Search results" className="absolute inset-x-0 top-9 z-30 max-h-[60vh] overflow-auto rounded border border-rule bg-surface py-1 shadow-pop">
          {res.length === 0 && <li className="px-2.5 py-1.5 text-muted">No matches</li>}
          {res.map((r, i) => (
            <li key={r.kind + r.ref} id={`${listId}-${i}`} role="option" aria-selected={i === active}
              onMouseDown={(e) => { e.preventDefault(); choose(r); }} onMouseEnter={() => setActive(i)}
              className={cx("cursor-pointer truncate px-2.5 py-1.5", i === active && "bg-evidence-tint")}>
              <span className="inline-block w-[62px] font-cond text-2xs text-muted">{r.kind}</span> <b>{r.title}</b> <span className="text-muted">{r.sub}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Season replay: the workpaper's clock. Partners and the administrator can move it to the next event in the packet's timeline. */
function Clock({ ov }: { ov: Overview | null }) {
  const boot = useBoot();
  const [busy, setBusy] = useState(false);
  const next = ov?.timeline_next?.[0] || boot.timeline_next?.[0];
  const clock = ov?.clock || boot.clock;
  const label = next ? next.event.replace(/_/g, " ").replace("client ", "") : "";
  const advance = async () => {
    if (!next) return;
    setBusy(true);
    try { await cmd({ type: "advance_clock", to: next.at }); await loadBoot(); } catch { /* reported */ } finally { setBusy(false); }
  };
  return (
    <div className="flex items-center gap-2 whitespace-nowrap">
      <span className="text-muted">Today</span> <b>{when(clock)}</b>
      {next && (can("advance_clock")
        ? <Button className="max-w-[180px] overflow-hidden text-ellipsis md:max-w-[300px]" disabled={busy} onClick={advance}
            title={`Next: ${next.event.replace(/_/g, " ")} on ${when(next.at)}`}>Next: {label} ({when(next.at)})</Button>
        : boot.me.role !== "client" && <span className="hidden text-xs text-muted lg:inline" title="Switch to the partner or the firm administrator to move the season clock">Next: {label} ({when(next.at)})</span>)}
    </div>
  );
}

function Toast() {
  const t = useApp((s) => s.toast);
  return (
    <div aria-live="polite" role="status" className="pointer-events-none fixed bottom-[18px] left-1/2 z-[60] -translate-x-1/2">
      {t && (
        <div className={cx("pointer-events-auto flex max-w-[min(720px,92vw)] items-center gap-3.5 rounded px-3.5 py-[9px] text-sm", t.error ? "bg-error text-white" : "bg-ink text-surface")}>
          <span>{t.text}</span>
          {t.undo && <button type="button" className="rounded-sm border border-current px-2.5 py-0.5 font-semibold" onClick={() => { t.undo!(); dismissToast(); }}>Undo</button>}
          <button type="button" aria-label="Dismiss" className="px-1 text-base leading-none opacity-80" onClick={dismissToast}>×</button>
        </div>
      )}
    </div>
  );
}

/** A rendering error in one view should not blank the whole workpaper. */
class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error(error, info.componentStack); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="p-7">
        <ErrorNote>Something went wrong showing this view: {this.state.error.message}</ErrorNote>
        <Button onClick={() => this.setState({ error: null })}>Try again</Button>
      </div>
    );
  }
}

createRoot(document.getElementById("app")!).render(<StrictMode><App /></StrictMode>);
