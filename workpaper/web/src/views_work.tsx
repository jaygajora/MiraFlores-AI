// The working views: open items, the return, documents, a document, checks.
import { useState, type ReactNode } from "react";
import { can, cmd, go, me, openRef, run, useApi, useApp, useBoot } from "./api";
import { Notes, VerifyBox, dispText } from "./actions";
import { MarkLegend, Paper } from "./paper";
import type { Data, Finding, OpenItem, Overview, Page, Step } from "./types";
import {
  Badge, Button, Card, Check, Count, Effect, Empty, ErrorNote, Key, Loading, Money, NUM, Pill, ROW_CLICK, Ref, ReasonForm, Row, RowLink,
  SEV_RAIL, Section, Sev, TABLE, TABLE_WRAP, TD, TH, Tag, VerifyMark, Who, cx, when,
} from "./ui";

/** Toggle membership in a Set held in state. */
function useSelection() {
  const [sel, setSel] = useState<Set<string>>(new Set());
  const toggle = (id: string) => setSel((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  return { sel, toggle, clear: () => setSel(new Set()) };
}

export function View({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("max-w-[1240px] px-4 pb-14 pt-3.5 md:px-7 md:pb-16 md:pt-5", className)}>{children}</div>;
}

export function QueueHead({ title, count, children }: { title: string; count?: number; children?: ReactNode }) {
  return (
    <div className="mt-1 flex flex-wrap items-center justify-between gap-3">
      <h1>{title}{count !== undefined && <Count n={count} />}</h1>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function BulkBar({ children }: { children: ReactNode }) {
  return <div className="sticky top-0 z-[5] my-2 flex flex-wrap items-center gap-2.5 rounded border border-adjusted/40 bg-adjusted-tint px-3 py-2">{children}</div>;
}

// ================================================================ totals strip
export function Totals({ ov }: { ov: Overview }) {
  const s = ov.summary;
  const cell = (label: string, eng: number, wpv: number, refund = false) => {
    const isTotal = label.startsWith("Total");
    return (
      <div className="flex flex-col">
        <span className="text-xs text-muted">{label}</span>
        <span className="text-lg font-semibold tracking-tight tabular md:text-[22px]"><Money v={refund ? -wpv : wpv} /></span>
        {eng !== wpv
          ? <span className="text-xs text-adjusted">engine {isTotal ? "" : eng >= 0 ? "owes " : "refund "}<Money v={isTotal ? eng : Math.abs(eng)} /></span>
          : <span className="text-xs text-muted">as engine</span>}
      </div>
    );
  };
  const side = (name: string, wp: Overview["summary"]["workpaper"]["federal"], en: Overview["summary"]["engine"]["federal"]) => (
    <div className="flex flex-wrap items-end gap-3.5 md:gap-[22px]">
      <span className="w-[76px] self-center font-semibold">{name}</span>
      {cell("Total tax", en.total_tax, wp.total_tax)}
      {cell(wp.balance_due >= 0 ? "Balance due" : "Refund", en.balance_due, wp.balance_due, wp.balance_due < 0)}
    </div>
  );
  return (
    <section aria-label="Return totals" className="mb-3.5 flex flex-wrap items-end gap-3.5 rounded border border-rule bg-surface px-[18px] py-3.5 md:gap-7">
      {side("Federal", s.workpaper.federal, s.engine.federal)}
      {side("California", s.workpaper.california, s.engine.california)}
      <p className="m-0 max-w-[220px] text-xs text-muted md:ml-auto" title={s.basis}>Workpaper = engine v3 + rate-based effect of adjustments</p>
    </section>
  );
}

// ================================================================ home: the open-items queue
const TYPE_LABEL: Record<OpenItem["type"], string> = {
  finding: "Findings", approval: "Approvals", note: "Notes", client_answer: "Client answers", client_question: "Waiting on client", document: "Documents", reopened: "Reopened sign-offs",
};
const NOTIF: Record<string, string> = { reopened: "border-l-warning", deadline: "border-l-warning", approval: "border-l-adjusted" };

export function Home() {
  const boot = useBoot();
  const { data: ov } = useApi<Overview>("/api/overview");
  const { data: items } = useApi<OpenItem[]>("/api/open-items");
  const [mine, setMine] = useState(false);
  const [type, setType] = useState("");
  const [area, setArea] = useState("");
  const { sel, toggle, clear } = useSelection();
  if (!ov || !items) return <Loading />;
  const list = items.filter((i) => (!mine || i.mine) && (!type || i.type === type) && (!area || i.area === area));
  const counts: Partial<Record<OpenItem["type"], number>> = {};
  items.forEach((i) => { counts[i.type] = (counts[i.type] || 0) + 1; });
  const selFindings = list.filter((i) => sel.has(i.id) && i.type === "finding");
  const areaTitle = (id: string) => boot.areas.find((a) => a.id === id)?.title;
  return (
    <View>
      <Totals ov={ov} />
      {ov.changes.count > 0 && (
        <div className="mb-2.5 flex flex-wrap items-center gap-2.5 rounded bg-evidence-tint px-3 py-2">
          <span>{ov.changes.count} change{ov.changes.count === 1 ? "" : "s"} by others since you last looked.</span>
          <Button onClick={() => go("changes")}>See what changed</Button>
          <Button onClick={() => run({ type: "seen", seq: ov.head }, true)}>Mark as seen</Button>
        </div>
      )}
      {ov.notifications.length > 0 && (
        <ul className="mb-2.5">
          {ov.notifications.map((n, i) => <li key={i} className={cx("mb-1 border-l-[3px] bg-surface px-2.5 py-1.5 text-sm", NOTIF[n.kind] ?? "border-l-evidence")}>{n.text}</li>)}
        </ul>
      )}
      <Steps steps={ov.steps} />
      <QueueHead title="Open items" count={list.length}>
        <Check checked={mine} onChange={setMine}>For me ({me().role_title.toLowerCase()})</Check>
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Type">
          <option value="">All types</option>
          {(Object.keys(counts) as OpenItem["type"][]).map((t) => <option key={t} value={t}>{TYPE_LABEL[t] || t} ({counts[t]})</option>)}
        </select>
        <select value={area} onChange={(e) => setArea(e.target.value)} aria-label="Area">
          <option value="">All areas</option>
          {boot.areas.map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}
        </select>
      </QueueHead>
      <p className="text-muted">Sorted by what matters most: errors before warnings, then by tax effect. Open any item to see its evidence.</p>
      {selFindings.length > 0 && can("dispose_finding") && (
        <BulkBar>
          <span>{selFindings.length} selected</span>
          <Button variant="primary" onClick={async () => {
            try { await cmd({ type: "bulk", items: selFindings.map((i) => ({ type: "accept_finding", finding: i.id })) }); clear(); } catch { /* reported */ }
          }}>Accept and adjust all</Button>
          <Button onClick={clear}>Clear</Button>
          <span className="text-muted">One action: undo reverses all of it.</span>
        </BulkBar>
      )}
      {list.length === 0 ? <Empty>Nothing open here. Change the filters, or move the season clock forward to see what arrives next.</Empty> : (
        <ul className="my-2 rounded border border-rule bg-surface">
          {list.map((i) => (
            <li key={i.type + i.id} className={cx("grid grid-cols-[22px_1fr] items-start gap-x-3 gap-y-1 border-l-[3px] border-t border-t-rule-soft py-2.5 pl-2.5 pr-3.5 first:border-t-0 md:grid-cols-[26px_1fr_auto_auto]", SEV_RAIL[i.severity])}>
              {i.type === "finding" && can("dispose_finding")
                ? <input type="checkbox" className="mt-[3px]" aria-label={`Select ${i.title}`} checked={sel.has(i.id)} onChange={() => toggle(i.id)} />
                : <span />}
              <button type="button" className="group min-w-0 text-left" onClick={() => openItem(i)}>
                <span className="block font-semibold group-hover:text-evidence">{i.title}</span>
                <span className="clamp-2 block max-w-[90ch] text-sm text-muted">{i.summary}</span>
                <span className="mt-1 block">
                  <Tag>{TYPE_LABEL[i.type]}</Tag><Tag>{areaTitle(i.area)}</Tag>
                  {i.source === "engine" && <Tag>engine diagnostic</Tag>}{i.needs && <Tag>needs {i.needs}</Tag>}
                </span>
              </button>
              <div className="col-start-2 max-w-[260px] text-sm md:col-start-auto md:text-right">{i.effect ? <Effect e={i.effect} compact /> : i.impact ? <Money v={i.impact} /> : null}</div>
              <div className="col-start-2 md:col-start-auto">
                {i.type === "approval" && (can("approve:reviewer") || can("approve:partner")) && i.by !== me().id &&
                  <Button variant="primary" onClick={() => run({ type: "approve_adjustment", adjustment: i.id })}>Approve</Button>}
                {i.type === "client_answer" && can("verify") && <Button onClick={() => run({ type: "review_answer", question: i.id })}>Mark reviewed</Button>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </View>
  );
}

function openItem(i: OpenItem) {
  if (i.type === "finding") openRef(i.id, true);
  else if (i.type === "approval" || i.type === "note") openRef(i.lines?.[0] || i.target || i.id, true);
  else if (i.type === "document") go(`doc/${i.id}`);
  else if (i.type === "reopened") go("review");
  else if (i.target) openRef(i.target, true);
  else go("review");
}

/** Which command completes a manual step; due diligence is completed on the Review page. */
function stepAction(s: Step): { label: string; act: () => void } | null {
  const name = s.step.toLowerCase();
  if (name.startsWith("identity")) return { label: "Mark done", act: () => run({ type: "complete_step", step: "identity", note: s.why, evidence: s.evidence }) };
  if (name.startsWith("prior-year return")) return { label: "Mark done", act: () => run({ type: "complete_step", step: "prior_year", note: s.why, evidence: s.evidence }) };
  if (name.startsWith("due diligence")) return { label: "Open checklist", act: () => go("review") };
  return null;
}

export function Steps({ steps }: { steps: Step[] }) {
  const done = steps.filter((s) => s.done).length;
  const [open, setOpen] = useState(false);
  return (
    <section className="mb-[18px] rounded border border-rule bg-surface">
      <button type="button" aria-expanded={open} aria-controls="required-steps" onClick={() => setOpen(!open)}
        className="flex w-full flex-wrap items-center gap-3.5 px-3.5 py-2.5 text-left font-semibold">
        <span>Required steps</span>
        <span aria-hidden className="flex gap-[3px]">{steps.map((s, i) => <span key={i} className={cx("h-1.5 w-2.5 rounded-[1px] md:w-[18px]", s.done ? "bg-verified" : "bg-rule")} />)}</span>
        <span className="font-normal text-muted">{done} of {steps.length} done</span>
        <span aria-hidden className="ml-auto text-muted">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <ol id="required-steps" className="list-decimal pb-3 pl-[38px] pr-3.5">
          {steps.map((s, i) => {
            const a = !s.done && !s.auto && can("verify") ? stepAction(s) : null;
            return (
              <li key={i} className="border-t border-rule-soft py-1.5">
                <div className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5">
                  <span className={s.done ? "text-verified" : ""}>{s.step}{s.done && <span className="sr-only"> (done)</span>}</span>
                  {a && <Button className="row-span-2 self-center" onClick={a.act}>{a.label}</Button>}
                  <span className="text-sm text-muted">{s.why}</span>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

// ================================================================ the return
export function ReturnView({ form }: { form?: string }) {
  const { data, error } = useApi("/api/return");
  const [box, setBox] = useState<string | null>(null);
  const cur = form || "F1040";
  const { data: lots } = useApi(cur === "F8949" && box ? `/api/return?form=F8949&box=${encodeURIComponent(box)}` : null);
  if (error) return <View><ErrorNote>{error}</ErrorNote></View>;
  if (!data) return <Loading />;
  const f = data.forms.find((x: Data) => x.form === cur) || data.forms[0];
  const rows = cur === "F8949" && box && lots ? lots.forms[0].lines : f.lines;
  return (
    <SplitView nav={
      <nav aria-label="Forms" className="contents md:block">
        {["federal", "california"].map((j) => (
          <div key={j} className="contents md:block">
            <div className="mb-1 ml-2 mt-2.5 hidden text-xs text-muted md:block">{j === "federal" ? "Federal" : "California"}</div>
            {data.forms.filter((x: Data) => x.jurisdiction === j).map((x: Data) => (
              <NavButton key={x.form} on={x.form === f.form} onClick={() => { setBox(null); go(`return/${x.form}`); }} title={x.title}>
                <span>{x.title.split(" - ")[0]}</span>{x.open_findings > 0 && <Badge n={x.open_findings} title={`${x.open_findings} open findings`} />}
              </NavButton>
            ))}
          </div>
        ))}
      </nav>
    }>
      <h1>{f.title}</h1>
      {cur === "F8949" && (
        <>
          <p className="text-muted">{f.lots} sales. Totals by box below; pick a box to list its lots. Exceptions (zero basis, wash sales, unread pages) are in Records, Sales detail.</p>
          <Row>
            {f.lines.map((l: Data) => {
              const b = l.key.split(".")[1];
              return <Button key={l.key} aria-pressed={box === b} variant={box === b ? "primary" : "default"} onClick={() => setBox(b)}>Box {b}: <Money v={l.workpaper} /></Button>;
            })}
            {box && <Button onClick={() => setBox(null)}>Totals</Button>}
          </Row>
        </>
      )}
      <LineTable rows={rows} />
    </SplitView>
  );
}

export function SplitView({ nav, children }: { nav: ReactNode; children: ReactNode }) {
  return (
    <View className="grid max-w-none grid-cols-1 gap-5 md:grid-cols-[150px_1fr] lg:grid-cols-[200px_1fr]">
      <div className="flex gap-px overflow-x-auto md:sticky md:top-0 md:max-h-[calc(100vh-100px)] md:flex-col md:self-start md:overflow-auto">{nav}</div>
      <div className="min-w-0">{children}</div>
    </View>
  );
}

export function NavButton({ on, onClick, title, children }: { on: boolean; onClick: () => void; title?: string; children: ReactNode }) {
  return (
    <button type="button" aria-current={on ? "page" : undefined} onClick={onClick} title={title}
      className={cx("flex shrink-0 items-center justify-between gap-1 whitespace-nowrap rounded md:w-full px-2 py-[5px] text-left text-sm hover:bg-surface md:whitespace-normal",
        on && "bg-surface font-semibold shadow-[inset_2px_0_rgb(var(--evidence))]")}>
      {children}
    </button>
  );
}

export function LineTable({ rows }: { rows: Data[] }) {
  return (
    <div className={TABLE_WRAP}>
      <table className={TABLE}>
        <thead>
          <tr>
            <th scope="col" className={cx(TH, "w-[22px] pr-0")}><span className="sr-only">Verified</span></th>
            <th scope="col" className={TH}>Line</th><th scope="col" className={TH}>Description</th>
            <th scope="col" className={cx(TH, "text-right")}>Engine v3</th><th scope="col" className={cx(TH, "text-right")}>Workpaper</th>
            <th scope="col" className={TH}><span className="sr-only">Flags</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((l) => (
            <tr key={l.key} className={cx(ROW_CLICK, "[&:last-child>td]:border-b-0", l.delta ? "[&>td:first-child]:shadow-[inset_3px_0_rgb(var(--adjusted))]" : l.findings.length ? "[&>td:first-child]:shadow-[inset_3px_0_rgb(var(--error))]" : "")}
              onClick={() => openRef(l.key, true)}>
              <td className={cx(TD, "w-[22px] pr-0")}><VerifyMark s={l.verify} /></td>
              <td className={TD}><button type="button" className="font-cond font-semibold hover:text-evidence" onClick={(e) => { e.stopPropagation(); openRef(l.key, true); }}>{l.key}</button></td>
              <td className={TD}>{l.label}</td>
              <td className={cx(TD, NUM)}>{typeof l.engine === "number" ? <Money v={l.engine} /> : <span>{String(l.engine)}</span>}</td>
              <td className={cx(TD, NUM)}>{l.delta ? <Money v={l.workpaper} className="font-semibold text-adjusted" /> : l.stale ? <span className="font-semibold text-warning" title="Needs engine recompute">↻</span> : null}</td>
              <td className={cx(TD, "w-12 whitespace-nowrap")}>
                {l.findings.length > 0 && <Badge n={l.findings.length} title={`${l.findings.length} open finding(s)`} />}
                {l.notes.length > 0 && <span role="img" aria-label="Open note" title="Open note" className="ml-1.5 inline-block h-2 w-2 rounded-full bg-warning" />}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ================================================================ documents
type DocFilter = "" | "open" | "unused" | "findings";

export function Documents() {
  const { data } = useApi<Data[]>("/api/documents");
  const [filter, setFilter] = useState<DocFilter>("");
  const { sel, toggle, clear } = useSelection();
  const [bulk, setBulk] = useState(false);
  if (!data) return <Loading />;
  const list = data.filter((d) => !filter || (filter === "open" ? !d.accounted : filter === "findings" ? d.findings.length : d.engine_status !== "used"));
  const open = data.filter((d) => !d.accounted).length;
  return (
    <View>
      <QueueHead title="Documents" count={data.length}>
        <select value={filter} onChange={(e) => setFilter(e.target.value as DocFilter)} aria-label="Filter">
          <option value="">All</option><option value="open">Not accounted for ({open})</option>
          <option value="unused">Not used by the engine</option><option value="findings">Cited by findings</option>
        </select>
      </QueueHead>
      <p className="text-muted">Completeness: every document must be used, superseded, a duplicate, or explained. Documents the engine ignored are where errors hide: several findings cite them.</p>
      {sel.size > 0 && can("dispose_document") && (
        <BulkBar><span>{sel.size} selected</span><Button variant="primary" onClick={() => setBulk(true)}>Mark as reviewed, not a return input</Button><Button onClick={clear}>Clear</Button></BulkBar>
      )}
      {bulk && (
        <Card>
          <ReasonForm authority={false} submit="Mark selected" placeholder="e.g. Identity and engagement documents; no return amounts" onCancel={() => setBulk(false)}
            onSubmit={async (reason) => {
              await cmd({ type: "bulk", items: [...sel].map((d) => ({ type: "dispose_document", document: d, status: "reviewed_not_input", reason })) });
              clear(); setBulk(false);
            }} />
        </Card>
      )}
      <div className={TABLE_WRAP}>
        <table className={TABLE}>
          <thead>
            <tr>
              <th scope="col" className={TH}><span className="sr-only">Select</span></th><th scope="col" className={TH}>Doc</th><th scope="col" className={TH}>Title</th>
              <th scope="col" className={TH}>Received</th><th scope="col" className={cx(TH, "text-right")}>Values used</th><th scope="col" className={TH}>Status</th><th scope="col" className={TH}>Lands on</th>
            </tr>
          </thead>
          <tbody>
            {list.map((d) => (
              <tr key={d.id} className={cx(ROW_CLICK, "[&:last-child>td]:border-b-0", !d.accounted && "[&>td:first-child]:shadow-[inset_3px_0_rgb(var(--error))]")} onClick={() => go(`doc/${d.id}`)}>
                <td className={TD} onClick={(e) => e.stopPropagation()}>
                  {!d.accounted && can("dispose_document") && <input type="checkbox" aria-label={`Select ${d.id}`} checked={sel.has(d.id)} onChange={() => toggle(d.id)} />}
                </td>
                <td className={TD}><a href={`#doc/${d.id}`} className="font-cond font-semibold text-ink no-underline hover:text-evidence" onClick={(e) => e.stopPropagation()}>{d.id}</a></td>
                <td className={TD}>{d.title}{d.findings.length > 0 && <Badge n={d.findings.length} title="Cited by findings" />}</td>
                <td className={cx(TD, "whitespace-nowrap")}>{when(d.received_at)}</td>
                <td className={cx(TD, NUM)}>{d.values_used}/{d.values}</td>
                <td className={TD}><DocStatus d={d} /></td>
                <td className={cx(TD, "font-cond text-xs text-muted")}>{d.lines.slice(0, 4).join(", ")}{d.line_count > 4 ? ` +${d.line_count - 4}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </View>
  );
}

const ENGINE_STATUS: Record<string, string> = { used: "used", superseded: "superseded", duplicate: "duplicate image", reference: "not extracted", not_used: "not used", context: "not used" };

function DocStatus({ d }: { d: Data }) {
  if (d.disposition) return <span className="text-xs text-verified">{d.disposition.status.replace(/_/g, " ")}</span>;
  if (d.auto_accounted) return <span className="text-xs text-verified" title={d.auto_accounted}>reference</span>;
  return <span className={cx("text-xs", d.accounted ? "text-verified" : "font-semibold text-error")}>{ENGINE_STATUS[d.engine_status] || d.engine_status}</span>;
}

const DOC_DISPOSITIONS: [string, string][] = [
  ["reviewed_not_input", "Reviewed: not a return input"], ["used_by_workpaper", "Used through a workpaper adjustment"],
  ["superseded", "Superseded"], ["duplicate", "Duplicate"], ["out_of_scope", "Out of engagement scope"],
];

export function DocView({ id }: { id: string }) {
  const boot = useBoot();
  const [reveal, setReveal] = useState(0);
  const { data: d, error } = useApi(`/api/document/${encodeURIComponent(id)}?reveal=${reveal}`);
  const [status, setStatus] = useState("reviewed_not_input");
  const drawerOpen = useApp((s) => s.drawer.length > 0); // the side column only fits when the trace drawer is closed
  if (error) return <View><ErrorNote>{error}</ErrorNote></View>;
  if (!d) return <Loading />;
  const allVals: Data[] = d.pages.flatMap((p: Page) => p.values.map((v) => ({ ...v, page: p.page })));
  const sorted = [...allVals].sort((a, b) => (b.landing.status === "used" ? 1 : 0) - (a.landing.status === "used" ? 1 : 0)).slice(0, 80);
  return (
    <View className={cx("grid max-w-none grid-cols-1 gap-[22px]", !drawerOpen && "xl:grid-cols-[minmax(0,1fr)_380px]")}>
      <div className="min-w-0">
        <button type="button" className="text-evidence" onClick={() => go("documents")}>‹ Documents</button>
        <h1 className="mt-1.5 break-words"><Key>{d.id}</Key> {d.title}</h1>
        <p className="text-muted">
          {d.type}, {d.issuer}, belongs to {d.belongs_to}. Received {when(d.received_at)} from {d.uploaded_by} as {d.file_name}. Extraction: {d.extraction.status}{d.extraction.reason ? ` (${d.extraction.reason})` : ""}.
        </p>
        <Row>
          <VerifyBox target={d.id} label="Verify document" />
          {boot.me.clearance && !reveal && <Button onClick={() => setReveal(1)} title="Shows full SSNs and account numbers; the view is logged">Reveal sensitive data</Button>}
          {reveal ? <Pill tone="warning">Sensitive data shown; this view was logged</Pill> : null}
        </Row>
        {d.related.length > 0 && <p>{d.related.map((x: Data) => <span key={x.ref} className="mr-3.5">{x.relation}: <Ref r={x.ref} /></span>)}</p>}
        {d.pages.map((p: Page) => (
          <div key={p.page} id={`p${p.page}`}>
            <Paper doc={d.id} title={d.title} page={p.page} pageCount={d.page_count} text={p.text} values={p.values} layout={p.layout} unread={p.unread} />
          </div>
        ))}
      </div>
      <aside className={cx("self-start rounded border border-rule bg-surface px-3.5 pb-3.5", !drawerOpen && "xl:sticky xl:top-0 xl:max-h-[calc(100vh-80px)] xl:overflow-auto")}>
        <Section title="Where it landed">
          <p className="text-muted">{d.index?.values_used} of {d.index?.values} values feed the return.</p>
          <MarkLegend />
          {allVals.length > 60 && <p className="text-muted">{allVals.length} values; showing those that land on the return first.</p>}
          <ul className="mt-2 text-xs">
            {sorted.map((v) => (
              <li key={v.id} className="border-t border-rule-soft">
                <button type="button" onClick={() => openRef(v.id)} className="grid w-full grid-cols-[1fr_auto_34px] gap-x-2 gap-y-0.5 px-1 py-[5px] text-left hover:bg-evidence-tint">
                  <span className="font-semibold">{v.label}</span>
                  <span className="font-cond">{String(v.text_as_read)}</span>
                  <span className={cx("text-2xs tabular", v.confidence < 0.9 ? "font-semibold text-warning" : "text-muted")}>{v.confidence.toFixed(2)}</span>
                  <span className={cx("col-span-3 font-cond", v.landing.status === "used" ? "text-evidence" : "text-muted")}>
                    {v.landing.lines?.length ? v.landing.lines.slice(0, 3).join(", ") : v.landing.reason}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Section>
        {d.findings.length > 0 && (
          <Section title="Findings citing this document">
            {d.findings.map((f: Finding) => <RowLink key={f.id} onClick={() => openRef(f.id)}><Sev s={f.severity} /> {f.title}</RowLink>)}
          </Section>
        )}
        <Section title="Accounted for">
          {d.index?.disposition
            ? <p><b>{d.index.disposition.status.replace(/_/g, " ")}</b>: {d.index.disposition.reason} <span className="text-muted">(<Who id={d.index.disposition.by} />)</span></p>
            : d.index?.accounted ? <p>{d.index.auto_accounted || `Engine: ${d.index.engine_status}`}</p> : <p className="font-semibold text-warning">Not yet accounted for.</p>}
          {can("dispose_document") && (
            <div>
              <select className="w-full" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Disposition">
                {DOC_DISPOSITIONS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
              </select>
              <ReasonForm authority={false} submit="Record" placeholder="How this document was used or why it is not needed"
                onSubmit={(reason) => cmd({ type: "dispose_document", document: d.id, status, reason })} />
            </div>
          )}
        </Section>
        <Section title="Notes"><Notes target={d.id} notes={d.notes} /></Section>
      </aside>
    </View>
  );
}

// ================================================================ checks
const KINDS: [string, string][] = [["error", "Errors in the return"], ["judgment", "Judgment calls"], ["data", "Data quality"], ["outside_filing", "Outside filings"], ["process", "Process"], ["planning", "Planning"]];
const isOpen = (f: Finding) => f.status === "open" || f.status === "client_answered";
type Show = "open" | "closed" | "all";

export function Checks() {
  const { data } = useApi<{ findings: Finding[]; passes: Data[] }>("/api/findings");
  const [show, setShow] = useState<Show>("open");
  const { sel, toggle, clear } = useSelection();
  if (!data) return <Loading />;
  const fs = data.findings.filter((f) => show === "all" || (show === "open" ? isOpen(f) : !isOpen(f)));
  const tot = data.findings.filter((f) => f.kind === "error").reduce((a, f) => ({ fed: a.fed + (f.effect.fed_tax || 0), ca: a.ca + (f.effect.ca_tax || 0) }), { fed: 0, ca: 0 });
  return (
    <View>
      <QueueHead title="Checks">
        <select value={show} onChange={(e) => setShow(e.target.value as Show)} aria-label="Status">
          <option value="open">Open</option><option value="closed">Resolved</option><option value="all">All</option>
        </select>
      </QueueHead>
      <p className="text-muted">
        Rules that do not trust the engine or the extraction: each reads the printed pages, client answers, agency records and prior years.
        If every error finding were accepted: federal tax <Money v={tot.fed} sign />, California tax <Money v={tot.ca} sign />.
      </p>
      {sel.size > 0 && can("dispose_finding") && (
        <BulkBar>
          <span>{sel.size} selected</span>
          <Button variant="primary" onClick={async () => {
            try { await cmd({ type: "bulk", items: [...sel].map((id) => ({ type: "accept_finding", finding: id })) }); clear(); } catch { /* reported */ }
          }}>Accept and adjust all</Button>
          <Button onClick={clear}>Clear</Button>
        </BulkBar>
      )}
      {KINDS.map(([k, title]) => {
        const g = fs.filter((f) => f.kind === k);
        if (!g.length) return null;
        return (
          <section key={k}>
            <h2 className="border-b border-rule pb-1">{title}<Count n={g.length} /></h2>
            {g.map((f) => (
              <article key={f.id} className={cx("my-2 grid grid-cols-[24px_1fr] gap-2 rounded border border-l-[3px] border-rule bg-surface py-2.5 pl-2.5 pr-3.5", SEV_RAIL[f.severity])}>
                {f.suggestions.length > 0 && isOpen(f) && can("dispose_finding")
                  ? <input type="checkbox" className="mt-1" aria-label={`Select ${f.title}`} checked={sel.has(f.id)} onChange={() => toggle(f.id)} />
                  : <span />}
                <div className="min-w-0">
                  <h3 className="m-0 mb-1 text-base">
                    <button type="button" className="text-left hover:text-evidence" onClick={() => openRef(f.id, true)}>{f.title}</button>
                  </h3>
                  <p className="text-sm text-muted">{f.summary}</p>
                  <Row><Effect e={f.effect} compact />{f.source === "engine" && <Tag>engine diagnostic</Tag>}{f.status !== "open" && <Tag ok>{dispText(f)}</Tag>}</Row>
                </div>
              </article>
            ))}
          </section>
        );
      })}
      <section>
        <h2 className="border-b border-rule pb-1">Proved by recalculation<Count n={data.passes.length} /></h2>
        <p className="text-muted">These pass, and count as machine verification on the lines they cover.</p>
        <ul className="text-sm">
          {data.passes.map((p, i) => (
            <li key={i} className="border-t border-rule-soft py-1">
              <VerifyMark s="recalculated" /> <b>{p.title}</b> <span className="text-muted">{p.detail}</span> {p.lines.slice(0, 3).map((l: string) => <Ref key={l} r={l} />)}
            </li>
          ))}
        </ul>
      </section>
    </View>
  );
}

