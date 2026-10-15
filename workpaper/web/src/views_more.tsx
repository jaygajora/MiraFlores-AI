// Review, changes, records, filing, firm, and the client portal.
import { useState, type FormEvent, type ReactNode } from "react";
import { api, can, cmd, go, isUndoable, loadBoot, me, openRef, run, toast, useApi, useBoot, userLink, userName } from "./api";
import { Attach, Thread } from "./actions";
import { BulkBar, NavButton, SplitView, Totals, View } from "./views_work";
import type { Data, LogEvent, Note, Overview, Person } from "./types";
import {
  Button, Check, ConfirmDialog, Count, DataTable, Empty, ErrorNote, Field, Loading, Money, NUM, Pill, ROW_CLICK, Ref, ReasonForm, Row,
  TABLE, TABLE_WRAP, TD, TH, Tabs, Tag, VerifyMark, Who, buttonClass, cx, fmt, when,
} from "./ui";

const LEVELS = ["preparer", "reviewer", "partner"] as const;
const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

// ================================================================ review: areas, sign-offs, approvals, due diligence
export function Review() {
  const { data: ov } = useApi<Overview>("/api/overview");
  const { data: notes } = useApi<{ notes: Note[]; questions: Note[] }>("/api/notes");
  if (!ov || !notes) return <Loading />;
  return (
    <View>
      <h1>Review and sign-off</h1>
      <p className="text-muted">A sign-off records a fingerprint of what was signed: the area's line values, adjustments, finding and document dispositions. If any of it changes, the sign-off reopens on its own.</p>
      <div className={TABLE_WRAP}>
        <table className={TABLE}>
          <thead>
            <tr>
              <th scope="col" className={TH}>Area</th><th scope="col" className={cx(TH, "text-right")}>Open findings</th><th scope="col" className={cx(TH, "text-right")}>Adjustments</th>
              <th scope="col" className={cx(TH, "text-right")}>Open notes</th><th scope="col" className={cx(TH, "text-right")}>Hours / budget</th>
              {LEVELS.map((l) => <th key={l} scope="col" className={TH}>{cap(l)}</th>)}
            </tr>
          </thead>
          <tbody>
            {ov.areas.map((a) => (
              <tr key={a.area} className="[&:last-child>td]:border-b-0">
                <th scope="row" className={cx(TD, "text-left font-normal")}>{a.title}</th>
                <td className={cx(TD, NUM)}>{a.open_findings}</td><td className={cx(TD, NUM)}>{a.adjustments}</td><td className={cx(TD, NUM)}>{a.open_notes}</td>
                <td className={cx(TD, NUM, a.budget && a.hours > a.budget ? "text-error" : "")}>{a.hours} / {a.budget ?? "–"}</td>
                {LEVELS.map((l) => {
                  const so = a.signoffs[l];
                  const partnerOnly = a.area === "partner_review" && l !== "partner";
                  return (
                    <td key={l} className={cx(TD, "min-w-[120px] text-xs", so && (so.valid ? "text-verified" : "font-semibold text-warning"))}>
                      {so ? <span title={so.note || ""}>{so.valid ? "Signed" : "Reopened"} <Who id={so.by} /><br /><span className="font-normal text-muted">{when(so.at)}</span></span>
                        : l === "reviewer" && a.area !== "partner_review" && !a.signoffs.preparer?.valid ? <span className="text-muted">After the preparer</span>
                        : can(`signoff:${l}`) && !partnerOnly ? <Button onClick={() => run({ type: "signoff", area: a.area, level: l })}>Sign off</Button>
                        : <span className="text-muted">–</span>}
                      {so && !so.valid && can(`signoff:${l}`) && <div className="mt-1"><Button onClick={() => run({ type: "signoff", area: a.area, level: l })}>Sign again</Button></div>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Approvals approvals={ov.approvals} />
      <DueDiligence />
      <section>
        <h2>Review notes and questions</h2>
        {notes.notes.length === 0 && <Empty>No notes yet. Add one from any line, document or finding.</Empty>}
        {notes.notes.map((n) => <div key={n.id} className="my-2.5"><div className="text-muted">On <Ref r={n.target} /> by <Who id={n.by} /> {when(n.at)}</div><Thread n={n} /></div>)}
      </section>
      <section>
        <h2>Questions to the client</h2>
        {notes.questions.length === 0 && <Empty>None sent. Ask from a finding, or below.</Empty>}
        {notes.questions.map((q) => (
          <div key={q.id} className="my-2.5">
            <div className="text-muted">{q.target ? <>About <Ref r={q.target} /> </> : null}asked by <Who id={q.by} /> {when(q.at)}</div>
            <Thread n={{ ...q, blocking: false }} />
          </div>
        ))}
        {can("ask_client") && <AskClient />}
      </section>
    </View>
  );
}

function AskClient() {
  const [t, setT] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!t.trim()) return;
    try { await cmd({ type: "ask_client", text: t }); setT(""); } catch { /* reported */ }
  };
  return (
    <form className="my-2 flex flex-wrap gap-2" onSubmit={submit}>
      <input aria-label="New question for the client" className="min-w-[16rem] flex-1" placeholder="New question for the client" value={t} onChange={(e) => setT(e.target.value)} />
      <Button type="submit" disabled={!t.trim()}>Send</Button>
    </form>
  );
}

function Approvals({ approvals }: { approvals: Overview["approvals"] }) {
  const boot = useBoot();
  if (!approvals.length) return null;
  return (
    <section>
      <h2>Adjustments waiting for approval<Count n={approvals.length} /></h2>
      <p className="text-muted">Firm rule: any adjustment with a tax effect over {fmt(boot.standards.partner_signoff_over)} needs the partner; the rest need a reviewer. Nobody approves their own work.</p>
      <ul className="my-2 rounded border border-rule bg-surface">
        {approvals.map((a) => (
          <li key={a.adjustment} className={cx("flex flex-wrap items-start justify-between gap-3 border-l-[3px] border-t border-t-rule-soft px-3.5 py-2.5 first:border-t-0", a.level === "partner" ? "border-l-error" : "border-l-warning")}>
            <button type="button" className="group min-w-0 text-left" onClick={() => openRef(a.line, true)}>
              <span className="block font-semibold group-hover:text-evidence">{a.line}</span>
              <span className="block text-sm text-muted">Effect {fmt(a.size)}; recorded by {userName(a.by)}; needs {a.level}</span>
            </button>
            {can(`approve:${a.level}`) && a.by !== me().id && <Button variant="primary" onClick={() => run({ type: "approve_adjustment", adjustment: a.adjustment })}>Approve</Button>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ageOn(dob: string | undefined, year: number) {
  if (!dob) return null;
  const [y, m, d] = dob.split("-").map(Number);
  return year - y - (m > 12 || (m === 12 && d > 31) ? 1 : 0);
}

/** Form 8867 knowledge questions, written from the household record. */
function ddQuestions(people: Person[], year: number): string[] {
  const deps = people.filter((p) => p.role === "dependent");
  const who = deps.map((p) => {
    const age = ageOn(p.dob, year);
    return `${p.name.split(" ")[0]}${age !== null ? ` ${age}` : ""}${p.full_time_student ? ", full-time student" : ""}`;
  }).join("; ");
  return [
    `Interviewed the taxpayer about each dependent's relationship, age and residency (${who}).`,
    "Have documents showing relationship and residency (prior-year return, school and care statements).",
    "Verified each dependent's SSN against a card or prior return.",
    "No information is inconsistent or incomplete (or the inconsistency was resolved and documented).",
    "Retain this checklist and the records relied on for the retention period.",
  ];
}

function DueDiligence() {
  const boot = useBoot();
  const { data: wi } = useApi("/api/whatif");
  const questions = ddQuestions(boot.household.people, boot.household.tax_year);
  const [ans, setAns] = useState<boolean[]>(() => questions.map(() => false));
  if (!wi) return null;
  const rec = wi.decisions?.due_diligence;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run({ type: "decide", topic: "due_diligence", choice: "completed", answers: questions.map((q, i) => ({ q, a: ans[i] })),
      rationale: "Form 8867 knowledge and documentation requirements met.", authority: "IRC 6695(g); Treas. Reg. 1.6695-2" });
  };
  return (
    <section>
      <h2>Due diligence (Form 8867) for the child tax credit and credit for other dependents</h2>
      {rec ? <p><VerifyMark s="verified" /> Completed by <Who id={rec.by} /> {when(rec.at)}. {rec.rationale}</p> : can("decide") ? (
        <form onSubmit={submit} className="space-y-2">
          {questions.map((q, i) => <Check key={i} checked={ans[i]} onChange={(v) => setAns((a) => a.map((x, j) => (j === i ? v : x)))}>{q}</Check>)}
          <div className="flex justify-end"><Button variant="primary" type="submit" disabled={ans.some((a) => !a)}>Complete checklist</Button></div>
        </form>
      ) : <p className="text-muted">Not completed. The preparer completes it.</p>}
    </section>
  );
}

// ================================================================ changes: since last look, history, compare, what-if, variances
type ChangeTab = "since" | "history" | "compare" | "whatif" | "variances";
const CHANGE_TABS: [ChangeTab, string][] = [["since", "Since I last looked"], ["history", "Full history"], ["compare", "Compare versions"], ["whatif", "What-ifs"], ["variances", "Swings vs 2024"]];

export function Changes({ tab }: { tab?: string }) {
  const t = (CHANGE_TABS.find(([k]) => k === tab)?.[0] ?? "since") as ChangeTab;
  return (
    <View>
      <h1>Changes</h1>
      <Tabs value={t} tabs={CHANGE_TABS} onChange={(k) => go(`changes/${k}`)} />
      <div role="tabpanel">
        {t === "since" && <Since />}
        {t === "history" && <History />}
        {t === "compare" && <Compare />}
        {t === "whatif" && <WhatIf />}
        {t === "variances" && <Variances />}
      </div>
    </View>
  );
}

function Since() {
  const { data } = useApi("/api/changes");
  if (!data) return <Loading />;
  return (
    <section>
      <Row><span>{data.count} change{data.count === 1 ? "" : "s"} by others since you last marked as seen.</span><Button onClick={() => run({ type: "seen", seq: data.head }, true)}>Mark all as seen</Button></Row>
      <EventList events={[...data.events].reverse()} />
    </section>
  );
}

function History() {
  const { data } = useApi<LogEvent[]>("/api/history?limit=400");
  if (!data) return <Loading />;
  return <section><p className="text-muted">The log is append-only. Undo adds an event that cancels earlier ones; nothing is erased.</p><EventList events={data} undo /></section>;
}

export function Events({ children }: { children: ReactNode }) {
  return <ul className="my-2 rounded border border-rule bg-surface text-sm">{children}</ul>;
}

export function EventRow({ when: w, who, children, undone, action }: { when: string; who?: string; children: ReactNode; undone?: boolean; action?: ReactNode }) {
  return (
    <li className={cx("grid grid-cols-1 items-baseline gap-x-2.5 border-t border-rule-soft px-3 py-1.5 first:border-t-0 md:grid-cols-[96px_130px_1fr_auto]", undone && "line-through opacity-60")}>
      <span className="text-muted tabular">{w}</span>
      <span className={cx("truncate font-semibold", !who && "hidden md:block")}>{who}</span>
      <span>{children}</span>
      {action ?? <span />}
    </li>
  );
}

export function EventList({ events, undo }: { events: LogEvent[]; undo?: boolean }) {
  if (!events.length) return <Empty>Nothing new.</Empty>;
  return (
    <Events>
      {events.map((e) => (
        <EventRow key={e.id} when={when(e.sim_at)} who={e.actor_name} undone={e.undone}
          action={undo && !e.undone && e.actor === me().id && isUndoable(e.kind) && e.kind !== "adjustment.approved"
            ? <Button onClick={() => run(e.batch ? { type: "undo", batch: e.batch } : { type: "undo", event: e.id })}>Undo</Button> : undefined}>
          {e.target && !e.target.startsWith("tl-") && !e.target.startsWith("e-") ? <Ref r={e.target} /> : null} {e.text}
        </EventRow>
      ))}
    </Events>
  );
}

const VERSIONS: [string, string][] = [["2024", "2024 as filed"], ["v1", "v1 (Mar 4)"], ["v2", "v2 (Mar 19)"], ["v3", "v3 (Jun 23)"], ["workpaper", "Workpaper now"]];

function Compare() {
  const [a, setA] = useState("v2");
  const [b, setB] = useState("v3");
  const { data } = useApi(`/api/compare?a=${a}&b=${b}`);
  const pick = (v: string, set: (x: string) => void, label: string) => (
    <select aria-label={label} value={v} onChange={(e) => set(e.target.value)}>{VERSIONS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select>
  );
  return (
    <section>
      <Row>Compare {pick(a, setA, "Base version")} with {pick(b, setB, "Compared version")}</Row>
      {!data ? <Loading /> : (
        <>
          {data.summary_a && data.summary_b && (
            <div className="my-2 flex flex-wrap gap-6 rounded border border-rule bg-surface px-3.5 py-2.5">
              {["agi", "total_tax", "balance_due"].map((k) => <div key={k}><span className="text-xs text-muted">{k.replace("_", " ")}</span> <Money v={data.summary_a.federal[k]} /> → <Money v={data.summary_b.federal[k]} /></div>)}
              <div><span className="text-xs text-muted">CA tax</span> <Money v={data.summary_a.california.total_tax} /> → <Money v={data.summary_b.california.total_tax} /></div>
            </div>
          )}
          {data.docs_added.length > 0 && <p>Documents new in {b}: {data.docs_added.map((d: string) => <Ref key={d} r={d} />)}</p>}
          <p className="text-muted">{data.count} lines differ{data.rows.length > 300 ? "; showing the first 300" : ""}.</p>
          <div className={TABLE_WRAP}>
            <table className={TABLE}>
              <thead>
                <tr>
                  <th scope="col" className={TH}>Line</th><th scope="col" className={TH}>Description</th><th scope="col" className={cx(TH, "text-right")}>{a}</th>
                  <th scope="col" className={cx(TH, "text-right")}>{b}</th><th scope="col" className={cx(TH, "text-right")}>Change</th><th scope="col" className={TH}>Why</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.slice(0, 300).map((r: Data) => (
                  <tr key={r.key} className={ROW_CLICK} onClick={() => openRef(r.key)}>
                    <td className={TD}><button type="button" className="font-cond font-semibold hover:text-evidence" onClick={(e) => { e.stopPropagation(); openRef(r.key); }}>{r.key}</button></td>
                    <td className={TD}>{r.label}</td>
                    <td className={cx(TD, NUM)}><Money v={typeof r.a === "number" ? r.a : null} /></td><td className={cx(TD, NUM)}><Money v={typeof r.b === "number" ? r.b : null} /></td>
                    <td className={cx(TD, NUM)}><Money v={r.change} sign /></td><td className={cx(TD, "text-xs text-muted")}>{r.cause}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function WhatIf() {
  const { data } = useApi("/api/whatif");
  const [open, setOpen] = useState<string | null>(null);
  const [deciding, setDeciding] = useState<string | null>(null);
  if (!data) return <Loading />;
  return (
    <section>
      <p className="text-muted">The engine computed these alternatives exactly. Adopting one records a judgment call with its authority; it does not silently change the return.</p>
      {data.alternatives.map((a: Data) => {
        const dec = data.decisions[`whatif:${a.id}`];
        return (
          <article key={a.id} className="my-2.5 rounded border border-rule bg-surface px-3.5 py-2.5">
            <h3 className="mt-0">{a.description}</h3>
            <Row>
              <span>Federal tax <Money v={a.federal.total_tax_change} sign /></span><span>California tax <Money v={a.california.total_tax_change} sign /></span>
              <span className="text-muted">{a.changed_lines.length} lines change</span>
              <Button aria-expanded={open === a.id} onClick={() => setOpen(open === a.id ? null : a.id)}>{open === a.id ? "Hide lines" : "Show lines"}</Button>
              {!dec && can("decide") && deciding !== a.id && <Button onClick={() => setDeciding(a.id)}>Record a decision</Button>}
            </Row>
            {dec && <p><VerifyMark s="verified" /> Decision: {dec.choice} by <Who id={dec.by} />. {dec.rationale} ({dec.authority})</p>}
            {!dec && deciding === a.id && (
              <ReasonForm submit="Record decision" placeholder="Adopt or reject, and why" onCancel={() => setDeciding(null)}
                extra={<p className="text-xs text-muted">Start with “Reject” to record a rejection; anything else records adoption.</p>}
                onSubmit={(reason, authority) => cmd({ type: "decide", topic: `whatif:${a.id}`, choice: /^reject/i.test(reason) ? "rejected" : "adopted", rationale: reason, authority, what_if: a.id }).then(() => setDeciding(null))} />
            )}
            {open === a.id && <DataTable columns={[{ key: "key", label: "Line", type: "ref" }, { key: "old", label: "Base", type: "money" }, { key: "new", label: "Alternative", type: "money" }]} rows={a.changed_lines} />}
          </article>
        );
      })}
      <article className="my-2.5 rounded border border-rule bg-surface px-3.5 py-2.5">
        <h3 className="mt-0">Extension estimate (April 14)</h3>
        <p>Based on {data.extension.based_on_version}: federal balance {fmt(data.extension.federal.estimated_balance)}, paid {fmt(data.extension.federal.paid_with_form_4868)} with Form 4868; California {fmt(data.extension.california.estimated_balance)} (refund), paid 0.</p>
      </article>
    </section>
  );
}

function Variances() {
  const boot = useBoot();
  const { data } = useApi<Data[]>("/api/variances");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [text, setText] = useState("");
  if (!data) return <Loading />;
  const open = data.filter((v) => !v.explanation);
  const toggle = (k: string) => setSel((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    try { await cmd({ type: "bulk", items: [...sel].map((k) => ({ type: "explain_variance", key: k, text })) }); setSel(new Set()); setText(""); } catch { /* reported */ }
  };
  const vr = boot.standards.variance_review;
  return (
    <section>
      <p className="text-muted">Firm standard: explain any line that moved more than {vr.flag_if_change_over_percent}% and more than {fmt(vr.and_over_amount)}. {open.length} of {data.length} unexplained. Select several to explain at once.</p>
      {sel.size > 0 && can("verify") && (
        <form onSubmit={submit}>
          <BulkBar>
            <span>{sel.size} selected</span>
            <input aria-label="Explanation for all selected" className="min-w-[240px] flex-1" placeholder="Explanation for all selected (e.g. moved to Texas mid-year; new 540NR)" value={text} onChange={(e) => setText(e.target.value)} />
            <Button variant="primary" type="submit" disabled={!text.trim()}>Explain selected</Button>
          </BulkBar>
        </form>
      )}
      <div className={TABLE_WRAP}>
        <table className={TABLE}>
          <thead>
            <tr>
              <th scope="col" className={TH}><span className="sr-only">Select</span></th><th scope="col" className={TH}>Line</th><th scope="col" className={TH}>Description</th>
              <th scope="col" className={cx(TH, "text-right")}>2024</th><th scope="col" className={cx(TH, "text-right")}>2025</th><th scope="col" className={cx(TH, "text-right")}>Change</th><th scope="col" className={TH}>Explanation</th>
            </tr>
          </thead>
          <tbody>
            {data.map((v) => (
              <tr key={v.key} className={cx("[&:last-child>td]:border-b-0", !v.explanation && "[&>td:first-child]:shadow-[inset_3px_0_rgb(var(--error))]")}>
                <td className={TD}>{!v.explanation && can("verify") && <input type="checkbox" aria-label={`Select ${v.key}`} checked={sel.has(v.key)} onChange={() => toggle(v.key)} />}</td>
                <td className={TD}><button type="button" className="font-cond font-semibold text-evidence" onClick={() => openRef(v.key)}>{v.key}</button></td>
                <td className={TD}>{v.label}</td><td className={cx(TD, NUM)}><Money v={v.prior} /></td><td className={cx(TD, NUM)}><Money v={v.current} /></td>
                <td className={cx(TD, NUM)}><Money v={v.change} sign /> <span className="text-muted">{v.pct !== null ? `${(v.pct * 100).toFixed(0)}%` : "new"}</span></td>
                <td className={cx(TD, "text-xs")}>{v.explanation ? <>{v.explanation.text} <span className="text-muted">(<Who id={v.explanation.by} />)</span></> : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ================================================================ records
export function Records({ id }: { id?: string }) {
  const boot = useBoot();
  const rid = id || "summary";
  const { data, error } = useApi(`/api/reports/${encodeURIComponent(rid)}`);
  return (
    <SplitView nav={
      <nav aria-label="Records" className="contents">
        {boot.reports.map((r) => <NavButton key={r.id} on={r.id === rid} onClick={() => go(`records/${r.id}`)}>{r.title}</NavButton>)}
      </nav>
    }>
      {error ? <ErrorNote>{error}</ErrorNote> : !data ? <Loading /> : (
        <>
          <h1>{data.title}</h1>
          {data.subtitle && <p className="text-muted">{data.subtitle}</p>}
          {data.sections.map((s: Data, i: number) => (
            <section key={i} className="mb-[18px]">
              <h2>{s.title}</h2>
              <DataTable columns={s.columns} rows={s.rows} onRow={(r) => typeof r.ref === "string" && openRef(r.ref)} />
              {s.note && <p className="text-sm text-muted">{s.note}</p>}
            </section>
          ))}
          <p className="print-hide"><Button onClick={() => window.print()}>Print this record</Button></p>
        </>
      )}
    </SplitView>
  );
}

// ================================================================ filing and after
const STAGES = ["Extension filed", "Ready to send", "Client approval", "Transmitted", "Accepted", "Sealed", "Client copy delivered"];
type Confirm = null | "send" | "transmit";

export function Filing() {
  const { data: f } = useApi("/api/filing");
  const { data: ov } = useApi<Overview>("/api/overview");
  const { data: rf } = useApi("/api/rollforward");
  const [showRf, setShowRf] = useState(false);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [amending, setAmending] = useState(false);
  if (!f || !ov) return <Loading />;
  const ready = f.gates.every((g: Data) => g.ok);
  const reached = [true, ready || !!f.sent, !!f.approval_current || !!f.submission, !!f.submission, f.submission?.result === "accepted", !!f.sealed, !!f.delivered];
  const open = f.gates.filter((g: Data) => !g.ok);
  return (
    <View>
      <h1>Filing and after</h1>
      <Totals ov={ov} />
      <ol aria-label="Filing stages" className="my-3.5 flex flex-wrap">
        {STAGES.map((s, i) => (
          <li key={s} className={cx("min-w-[110px] flex-1 border-t-[3px] py-2 pl-2 pr-2.5 text-sm", reached[i] ? "border-verified text-ink" : "border-rule text-muted")}>
            <span className="font-semibold">{i + 1}</span> {s}<span className="sr-only">{reached[i] ? " (reached)" : " (not yet)"}</span>
          </li>
        ))}
      </ol>
      <p>Stage: <b>{f.stage}</b>. Return fingerprint <code>{f.fingerprint}</code>{f.sealed ? <> (sealed <code>{f.sealed.fingerprint}</code>)</> : null}.</p>
      {f.extension && <p className="text-muted">Extension filed {when(f.extension.at)}: Form 4868 with {fmt(f.extension.federal_paid)} (estimated from {f.extension.based_on}); FTB 3519 with {fmt(f.extension.california_paid)}.</p>}

      {f.rejection && f.submission?.result === "rejected" && (
        <section role="alert" className="my-3.5 rounded border border-error bg-error-tint px-4 pb-3 pt-1">
          <h2>E-file rejected</h2>
          {f.rejection.errors.map((e: Data, i: number) => <p key={i}><b>{e.code}</b> {e.message}</p>)}
          <HouseholdFixes fixes={f.household_fixes} />
        </section>
      )}

      <section>
        {f.sealed ? (
          <p className="text-muted">Filed. {f.submission?.forced ? `Transmitted with these gates open, recorded: ${f.submission.open_gates.join("; ")}.` : "All gates were met at transmission."}</p>
        ) : (
          <>
            <h2>Before it can go</h2>
            <ul className="rounded border border-rule bg-surface text-sm">
              {f.gates.map((g: Data, i: number) => (
                <li key={i} className="grid grid-cols-[16px_1fr] gap-2 border-t border-rule-soft px-3 py-1.5 first:border-t-0 md:grid-cols-[16px_300px_1fr]">
                  <span role="img" aria-label={g.ok ? "met" : "open"} className={cx("mt-1 h-2.5 w-2.5 rounded-full", g.ok ? "bg-verified" : "bg-error")} />
                  <span>{g.gate}</span>
                  <span className="col-start-2 text-muted md:col-start-auto">{g.why}</span>
                </li>
              ))}
            </ul>
          </>
        )}
        <Row>
          {can("send_to_client") && !f.sealed && (ready
            ? <Button variant="primary" onClick={() => run({ type: "send_to_client" })}>Send to client for approval</Button>
            : <Button onClick={() => setConfirm("send")}>Send to client anyway (recorded)</Button>)}
          {can("transmit") && !f.sealed && f.client_approval && (ready && f.approval_current
            ? <Button variant="primary" onClick={() => run({ type: "transmit" })}>Transmit e-file</Button>
            : <Button onClick={() => setConfirm("transmit")}>Transmit anyway (recorded)</Button>)}
          {can("deliver") && f.sealed && !f.delivered && <Button variant="primary" onClick={() => run({ type: "deliver" })}>Deliver client copy</Button>}
          <a className={buttonClass()} href={userLink("/api/export/client-copy")} target="_blank" rel="noopener noreferrer">Open client copy</a>
        </Row>
        {f.sent && <p className="text-muted">Sent to the client {when(f.sent.at)} by {userName(f.sent.by)} (fingerprint {f.sent.fingerprint}).</p>}
        {f.client_approval && (
          <p className={f.approval_current ? "" : "font-semibold text-warning"}>
            Client approved {when(f.client_approval.at)} ({f.client_approval.via}). {f.approval_current ? "Matches the return as it stands." : "Numbers changed after approval: send again."}
            {f.client_approval.presented === false ? " The approval arrived before the firm presented a return." : ""}
          </p>
        )}
      </section>

      {confirm && (
        <ConfirmDialog title={confirm === "send" ? "Send with open gates?" : "Transmit with open gates?"} variant="danger"
          confirm={confirm === "send" ? "Send anyway" : "Transmit anyway"} onClose={() => setConfirm(null)}
          onConfirm={() => cmd({ type: confirm === "send" ? "send_to_client" : "transmit", force: true })}>
          <p>These are still open and will be recorded with the {confirm === "send" ? "request" : "submission"}, under your name:</p>
          <ul className="list-disc pl-5">
            {open.map((g: Data, i: number) => <li key={i}>{g.gate}</li>)}
            {confirm === "transmit" && !f.approval_current && <li>Client approval of this exact return</li>}
          </ul>
        </ConfirmDialog>
      )}

      {f.history.length > 0 && (
        <section>
          <h2>E-file history</h2>
          <Events>
            {f.history.map((h: Data, i: number) => (
              <EventRow key={i} when={when(h.at)}>{h.kind}{h.errors ? ": " + h.errors.map((e: Data) => e.message).join("; ") : ""}{h.agency_submission ? ` (${h.agency_submission})` : ""}</EventRow>
            ))}
          </Events>
        </section>
      )}

      {f.sealed && (
        <section>
          <h2>Frozen at filing</h2>
          <p>Sealed {when(f.sealed.at)} at log event {f.sealed.seq}; log head hash <code>{(f.sealed.log_head || "").slice(0, 24)}</code>. Changes now require an amendment, which builds on the filed return and shows the difference from it.</p>
          {f.amendments.length > 0 ? <p>Amendment open: {f.amendments[f.amendments.length - 1].reason}</p> : can("amend") && (
            amending
              ? <ReasonForm authority={false} submit="Start amendment" placeholder="What changed and why an amendment is needed" onCancel={() => setAmending(false)}
                  onSubmit={(r) => cmd({ type: "start_amendment", reason: r }).then(() => setAmending(false))} />
              : <Button onClick={() => setAmending(true)}>Start an amendment (Form 1040-X)</Button>
          )}
          {f.post_filing.length > 0 && <ul className="list-disc pl-5">{f.post_filing.map((p: Data, i: number) => <li key={i}>{when(p.at)} {p.kind}: {p.detail}</li>)}</ul>}
          <InterestEstimate ov={ov} f={f} />
        </section>
      )}

      {Object.values(f.notices).length > 0 && (
        <section className="my-3.5 rounded border border-error bg-error-tint px-4 pb-3 pt-1">
          <h2>Notices</h2>
          {Object.values(f.notices as Record<string, Data>).map((n) => (
            <div key={n.id}>
              <p><b>{n.type}</b> for {n.tax_year}, dated {n.dated}, response due {n.response_due}.</p>
              <ul className="list-disc pl-5">{n.items_under_examination.map((i: string) => <li key={i}>{i}</li>)}</ul>
              <Row>
                <a className={buttonClass("primary")} href={userLink(`/api/export/notice/${encodeURIComponent(n.id)}`)} target="_blank" rel="noopener noreferrer">Open self-contained response record</a>
                {can("respond_notice") && <Button onClick={() => run({ type: "respond_notice", notice: n.id, text: "Response record sent to the IRS examiner." })}>Record response sent</Button>}
              </Row>
              {n.responses.map((r: Data, i: number) => <p key={i} className="text-muted">Responded {when(r.at)} by {userName(r.by)}</p>)}
            </div>
          ))}
        </section>
      )}

      {rf && (
        <section>
          <h2 className="flex items-center gap-2">Carry forward to 2026 <Button aria-expanded={showRf} onClick={() => setShowRf(!showRf)}>{showRf ? "Hide" : "Show"}</Button></h2>
          {showRf && <Rollforward rf={rf} />}
        </section>
      )}
    </View>
  );
}

function Rollforward({ rf }: { rf: Data }) {
  const fed = rf.plan_2026.federal, ca = rf.plan_2026.california;
  return (
    <div className="rounded border border-rule bg-surface px-4 pb-3 pt-1 [&_ul]:list-disc [&_ul]:pl-5">
      <h3>Carryovers (each keeps its source)</h3>
      <DataTable columns={[{ key: "item", label: "Item" }, { key: "amount", label: "Amount", type: "money" }, { key: "from", label: "From" }]} rows={rf.carryovers} />
      {rf.added_by_workpaper.length > 0 && <><h3>Added by this workpaper</h3><ul>{rf.added_by_workpaper.map((a: Data, i: number) => <li key={i}>{a.item}</li>)}</ul></>}
      <h3>2026 estimates</h3>
      <p>Federal: {fmt(fed.installment)} per quarter ({fed.basis}) due {fed.due.join(", ")}.</p>
      <p>California safe harbor: {ca.installments.map((x: number) => fmt(x)).join(" / ")} due {ca.due.join(", ")}. {ca.note}</p>
      <ul>{rf.plan_2026.changes.map((c: string, i: number) => <li key={i}>{c}</li>)}</ul>
      <h3>Client facts for next year</h3><ul>{rf.client_facts.map((c: string, i: number) => <li key={i}>{c}</li>)}</ul>
      <h3>Open items carried</h3><ul>{rf.open_items.map((o: Data, i: number) => <li key={i}><Ref r={o.ref} label={o.item} /> <span className="text-muted">{o.status}</span></li>)}</ul>
      <p className="text-muted">
        Retention: destroy {rf.retention.destroy_after_years} years after filing
        {rf.retention.filed ? ` (${parseInt(rf.retention.filed.slice(0, 4), 10) + rf.retention.destroy_after_years}${rf.retention.filed.slice(4)})` : ""}.
      </p>
    </div>
  );
}

/** Corrections the documents agree on (computed by the server from the identity documents). */
function HouseholdFixes({ fixes }: { fixes: Data[] }) {
  if (!fixes?.length) return <p>Correct the household record to match the identity documents, then transmit again.</p>;
  return (
    <>
      {fixes.map((x) => (
        <div key={x.person + x.field}>
          <p>{x.name}: the organizer's {x.field.toUpperCase()} differs from {x.evidence.map((r: string) => <Ref key={r} r={r} />)}, which show {x.shown}. Fix the household record, then transmit again.</p>
          {!can("fix_household") ? <p className="text-muted">A preparer, reviewer or partner corrects the record.</p>
            : !x.value ? <p className="text-muted">Correcting it needs sensitive-data clearance.</p>
            : <Button variant="primary" onClick={() => run({ type: "fix_household", person: x.person, field: x.field, value: x.value, reason: x.reason, evidence: x.evidence })}>
                Correct {x.name.split(" ")[0]}'s {x.field.toUpperCase()} to the documents
              </Button>}
        </div>
      ))}
    </>
  );
}

// IRS underpayment interest rate for the period (7% a year) and the failure-to-pay penalty (0.5% a month).
const INTEREST_RATE = 0.07;
const FTP_PER_MONTH = 0.005;

function InterestEstimate({ ov, f }: { ov: Overview; f: Data }) {
  const boot = useBoot();
  const bal = ov.summary.workpaper.federal.balance_due;
  if (bal <= 0) return null;
  const due = boot.deadlines.find((d) => /original due date/i.test(d.what))?.date ?? `${boot.household.tax_year + 1}-04-15`;
  const paid = f.post_filing.find((p: Data) => p.kind === "payment");
  const days = paid ? (Date.parse(paid.at) - Date.parse(due)) / 864e5 : null;
  if (!days || days <= 0) {
    return <p className="text-muted">Federal balance {fmt(bal)} unpaid after {when(due)}: interest at {INTEREST_RATE * 100}% a year and the {FTP_PER_MONTH * 100}% a month failure-to-pay penalty run until paid.</p>;
  }
  const interest = Math.round((bal * INTEREST_RATE * days) / 365);
  const ftp = Math.round(bal * FTP_PER_MONTH * Math.ceil(days / 30));
  return <p>Federal balance {fmt(bal)} paid {when(paid.at)}, {Math.round(days)} days late: estimated interest {fmt(interest)} and failure-to-pay penalty {fmt(ftp)} (the IRS computes the final amounts; the engine does not).</p>;
}

// ================================================================ firm
export function Firm() {
  const boot = useBoot();
  const { data: au, error } = useApi(can("audit") ? "/api/audit" : null);
  const { data: ov } = useApi<Overview>("/api/overview");
  const [resetting, setResetting] = useState(false);
  const st = boot.standards;
  return (
    <View>
      <h1>Firm</h1>
      <section>
        <h2>Standards</h2>
        <p className="text-muted">Firm-wide settings this workpaper enforces. The administrator can change them; each change is logged.</p>
        <StandardsEditor />
        <ul className="list-disc pl-5 text-sm text-muted">{st.rules.map((r, i) => <li key={i}>{r}</li>)}</ul>
      </section>
      {ov && (
        <section>
          <h2>Team, time and budget</h2>
          <p>{Object.entries(ov.assignments).map(([r, s]) => <Tag key={r}>{r}: {userName(s)}</Tag>)} {ov.team.map((t) => <Tag key={t.id}>{t.name}</Tag>)}</p>
          {can("assign") && <AssignForm assignments={ov.assignments} />}
          <div className={TABLE_WRAP}>
            <table className={TABLE}>
              <thead><tr><th scope="col" className={TH}>Area</th><th scope="col" className={cx(TH, "text-right")}>Hours</th><th scope="col" className={cx(TH, "text-right")}>Budget</th><th scope="col" className={TH}>Use</th></tr></thead>
              <tbody>
                {ov.areas.filter((a) => a.budget !== undefined && a.budget !== null).map((a) => {
                  const pct = Math.min(100, (a.hours / a.budget!) * 100);
                  return (
                    <tr key={a.area} className="[&:last-child>td]:border-b-0">
                      <td className={TD}>{a.title}</td><td className={cx(TD, NUM)}>{a.hours}</td><td className={cx(TD, NUM)}>{a.budget}</td>
                      <td className={TD}>
                        <span role="meter" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label={`${a.title} hours used`}
                          className="inline-block h-2 w-[140px] overflow-hidden rounded bg-rule-soft align-middle">
                          <span className={cx("block h-full", a.hours > a.budget! ? "bg-error" : "bg-recalc")} style={{ width: `${pct}%` }} />
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {can("log_time") && <LogTime />}
        </section>
      )}
      <section>
        <h2>Sensitive data and the audit log</h2>
        {error || !can("audit") ? <p className="text-muted">The audit log is for the administrator, the quality reviewer and the partner.</p> : !au ? <Loading /> : (
          <>
            <Row>
              Log integrity:{" "}
              {au.chain.ok ? <Pill tone="ok">verified, {au.chain.checked} events in an unbroken hash chain</Pill> : <Pill tone="error">broken at {au.chain.broken_at}</Pill>}
              <a className={buttonClass()} href={userLink("/api/export/log")}>Export the log</a>
            </Row>
            <h3>Unmasked views ({au.sensitive_views.length})</h3>
            {au.sensitive_views.length === 0 ? <p className="text-muted">No one has revealed sensitive data.</p> : (
              <Events>{au.sensitive_views.map((v: Data, i: number) => <EventRow key={i} when={new Date(v.at).toLocaleString()} who={v.name}>{v.target} {v.field}</EventRow>)}</Events>
            )}
            <h3>Recent events</h3>
            <Events>{au.events.slice(0, 60).map((e: LogEvent) => <EventRow key={e.id} when={when(e.sim_at)} who={e.actor_name} undone={e.undone}>{e.text}</EventRow>)}</Events>
          </>
        )}
      </section>
      {can("reset") && (
        <section>
          <h2>Demo</h2>
          <p className="text-muted">Start the season over from the packet. Everyone's work in this demo is cleared.</p>
          <Button variant="danger" onClick={() => setResetting(true)}>Reset demo</Button>
          {resetting && (
            <ConfirmDialog title="Reset the demo workpaper?" confirm="Reset everything" variant="danger" onClose={() => setResetting(false)}
              onConfirm={async () => { await api("/api/reset", { method: "POST" }); toast("Reset to the packet as delivered"); location.hash = ""; await loadBoot(); }}>
              <p>Every adjustment, note, sign-off and filing event in this demo is deleted, and the season clock goes back to the start. This cannot be undone.</p>
            </ConfirmDialog>
          )}
        </section>
      )}
    </View>
  );
}

function LogTime() {
  const boot = useBoot();
  const [area, setArea] = useState(boot.areas[0]?.id ?? "");
  const [hours, setHours] = useState("1");
  const [note, setNote] = useState("");
  const h = parseFloat(hours);
  const valid = h > 0 && h <= 24;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    try { await cmd({ type: "log_time", area, hours: h, note }); setNote(""); } catch { /* reported */ }
  };
  return (
    <form className="my-2 flex flex-wrap items-center gap-2" onSubmit={submit}>
      <select aria-label="Area" value={area} onChange={(e) => setArea(e.target.value)}>{boot.areas.map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}</select>
      <input aria-label="Hours" type="number" min="0.1" max="24" step="0.1" className="w-[90px] text-right" value={hours} onChange={(e) => setHours(e.target.value)} />
      <input aria-label="What you did" placeholder="What you did" value={note} onChange={(e) => setNote(e.target.value)} />
      <Button type="submit" disabled={!valid}>Log time</Button>
    </form>
  );
}

function StandardsEditor() {
  const boot = useBoot();
  const st = boot.standards;
  const initial = { pct: String(st.variance_review.flag_if_change_over_percent), amt: String(st.variance_review.and_over_amount), partner: String(st.partner_signoff_over) };
  const [v, setV] = useState(initial);
  const edit = can("standards");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const changes: [string, string, number][] = [
      ["variance_review.flag_if_change_over_percent", v.pct, st.variance_review.flag_if_change_over_percent],
      ["variance_review.and_over_amount", v.amt, st.variance_review.and_over_amount],
      ["partner_signoff_over", v.partner, st.partner_signoff_over],
    ];
    try {
      for (const [path, val, cur] of changes) if (Number(val) !== cur) await cmd({ type: "standard", path, value: Number(val) });
      await loadBoot();
    } catch { /* reported */ }
  };
  const num = (key: keyof typeof initial, label: string) => (
    <Field label={label} className="text-xs"><input type="number" min="0" className="w-[110px] text-right" disabled={!edit} value={v[key]} onChange={(e) => setV({ ...v, [key]: e.target.value })} /></Field>
  );
  return (
    <form className="flex flex-wrap items-end gap-3" onSubmit={submit}>
      {num("pct", "Flag swings over (%)")}
      {num("amt", "and over ($)")}
      {num("partner", "Partner approves adjustments over ($)")}
      <Field label="Verification types" className="min-w-[16rem] flex-1 text-xs"><input disabled value={st.verification_types.map((t) => t.replace(/_/g, " ")).join(", ")} /></Field>
      {edit && <Button type="submit" className="mb-2">Save standards</Button>}
    </form>
  );
}

function AssignForm({ assignments }: { assignments: Record<string, string> }) {
  const boot = useBoot();
  const [role, setRole] = useState<string>("reviewer");
  const [staff, setStaff] = useState(assignments.reviewer ?? "");
  return (
    <form className="my-2 flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (staff) run({ type: "assign", role, staff }); }}>
      <select aria-label="Role" value={role} onChange={(e) => { setRole(e.target.value); setStaff(assignments[e.target.value] ?? ""); }}>{LEVELS.map((r) => <option key={r} value={r}>{r}</option>)}</select>
      <select aria-label="Staff member" value={staff} onChange={(e) => setStaff(e.target.value)}>{boot.users.filter((u) => u.role !== "client").map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select>
      <Button type="submit">Assign</Button>
    </form>
  );
}

// ================================================================ client portal
export function ClientPortal() {
  const boot = useBoot();
  const { data } = useApi("/api/client");
  const [ans, setAns] = useState<Record<string, string>>({});
  if (!data) return <Loading />;
  const u = boot.me;
  const balance = (side: Data) => (side.balance_due >= 0 ? `balance due ${fmt(side.balance_due)}` : `refund ${fmt(-side.balance_due)}`);
  const answer = async (e: FormEvent, id: string) => {
    e.preventDefault();
    if (!(ans[id] || "").trim()) return;
    try { await cmd({ type: "answer", question: id, text: ans[id] }); setAns((a) => ({ ...a, [id]: "" })); } catch { /* reported */ }
  };
  return (
    <View className="mx-auto max-w-[760px]">
      <h1>Hello {u.name.split(" ")[0]}</h1>
      <p className="text-[15px]">Your {boot.household.tax_year} federal and California returns with {boot.firm}.</p>
      <section>
        <h2>Questions from your accountant</h2>
        {data.questions.length === 0 && <Empty>No questions right now.</Empty>}
        {data.questions.map((q: Data) => (
          <div key={q.id} className={cx("my-2 rounded border border-rule bg-surface px-3.5 py-2.5", q.status !== "open" && "opacity-80")}>
            <p><b>{q.text}</b></p>
            {q.thread.slice(1).map((m: Data, i: number) => <p key={i} className="text-muted">{userName(m.by)}: {m.text}</p>)}
            {q.status === "open" && (
              <form onSubmit={(e) => answer(e, q.id)}>
                <textarea className="w-full" rows={3} aria-label="Your answer" placeholder="Your answer" value={ans[q.id] || ""} onChange={(e) => setAns({ ...ans, [q.id]: e.target.value })} />
                <div className="mt-2 flex justify-end gap-2"><Attach target={q.id} /><Button variant="primary" type="submit" disabled={!(ans[q.id] || "").trim()}>Send answer</Button></div>
              </form>
            )}
          </div>
        ))}
      </section>
      <section>
        <h2>Review and sign</h2>
        {!data.sent ? <p className="text-muted">Your accountant will send the return here for your review.</p> : (
          <div>
            <p>Federal: total tax {fmt(data.summary.federal.total_tax)}, {balance(data.summary.federal)}.</p>
            <p>California: tax {fmt(data.summary.california.total_tax)}, {balance(data.summary.california)}.</p>
            {data.approval_current
              ? <p><VerifyMark s="verified" /> You approved and signed Forms 8879 on {when(data.approval.at)}.</p>
              : <Button variant="primary" onClick={() => run({ type: "client_approve" })}>Approve and sign Forms 8879</Button>}
          </div>
        )}
      </section>
      <section>
        <h2>Your documents</h2>
        <p className="text-muted">{data.documents.length} documents uploaded. Add more:</p>
        <Attach target="client-upload" />
        {data.uploads.length > 0 && <ul className="list-disc pl-5">{data.uploads.map((a: Data, i: number) => <li key={i}>{a.name} ({when(a.at)})</li>)}</ul>}
      </section>
      {data.filing.sealed && (
        <section><h2>Your filed returns</h2><a className={buttonClass("primary")} href={userLink("/api/export/client-copy")} target="_blank" rel="noopener noreferrer">Open your copy</a></section>
      )}
      <section>
        <h2>Messages</h2>
        <Events>{[...data.messages].reverse().map((m: Data, i: number) => <EventRow key={i} when={when(m.sent_at)} who={m.from}>{m.text}</EventRow>)}</Events>
      </section>
    </View>
  );
}

