// The trace drawer. Every ref opens here; following evidence pushes onto the chain,
// so a reviewer can walk from total tax down to the words on a page and back.
import { useState, type FormEvent, type ReactNode } from "react";
import { backDrawer, can, closeDrawer, cmd, go, openRef, useApi, useApp, useBoot } from "./api";
import { AdjustModal, AdjustmentRow, Attach, Attachments, FindingActions, Notes, VerifyBox, dispText } from "./actions";
import { Paper } from "./paper";
import type { Adjustment, Data, Finding, Page } from "./types";
import {
  Button, CloseButton, Effect, ErrorNote, Key, Loading, Money, NUM, Pill, Ref, RowLink, Row, Section, Sev, TABLE, TD,
  VerifyMark, Who, cx, guessKind, prettyRef, verifyLabel, when, type RefKind,
} from "./ui";

const HOP: Partial<Record<RefKind, [string, string]>> = {
  // [resting, current]
  finding: ["text-error border-error/50", "bg-error text-on-accent border-error"],
  document: ["text-evidence border-evidence/45", "bg-ink text-surface border-ink"],
  value: ["text-evidence border-evidence/45 border-dashed", "bg-ink text-surface border-ink"],
};
const HOP_DEFAULT: [string, string] = ["text-evidence border-evidence/45", "bg-evidence text-on-accent border-evidence"];

export function Drawer() {
  const chain = useApp((s) => s.drawer);
  if (!chain.length) return null;
  const cur = chain[chain.length - 1];
  return (
    <aside aria-label="Trace" className="fixed inset-y-0 right-0 z-40 flex w-screen min-w-0 flex-col overflow-hidden border-l border-rule bg-surface shadow-[-10px_0_30px_rgb(0_0_0/0.18)] md:top-[52px] md:w-[min(620px,100vw)] xl:static xl:col-start-3 xl:row-start-2 xl:w-auto xl:shadow-none">
      <nav aria-label="Trace path" className="relative flex min-h-[46px] flex-wrap items-center border-b border-rule bg-sunk py-2.5 pl-3.5 pr-11">
        <ol className="flex flex-wrap items-center">
          {chain.map((r, i) => {
            const [rest, now] = HOP[guessKind(r)] ?? HOP_DEFAULT;
            const isCur = i === chain.length - 1;
            return (
              <li key={r + i} className="inline-flex items-center">
                {i > 0 && <span aria-hidden className="relative h-0.5 w-4 bg-evidence/45 after:absolute after:-right-0.5 after:-top-0.5 after:h-1.5 after:w-1.5 after:rounded-full after:bg-evidence" />}
                <button type="button" aria-current={isCur ? "step" : undefined} onClick={() => backDrawer(i)}
                  className={cx("my-0.5 rounded-full border-[1.5px] px-2 py-0.5 font-cond text-xs font-semibold", isCur ? now : cx("bg-surface", rest))}>
                  {prettyRef(r)}
                </button>
              </li>
            );
          })}
        </ol>
        <CloseButton onClick={closeDrawer} label="Close trace" className="absolute right-2 top-2" />
      </nav>
      <div key={cur} className="overflow-auto px-[18px] pb-16">
        <Panel r={cur} />
      </div>
    </aside>
  );
}

function Panel({ r }: { r: string }) {
  switch (guessKind(r)) {
    case "line": return <LinePanel k={r} />;
    case "value": return <ValuePanel id={r} />;
    case "document": return <DocPanel r={r} />;
    case "finding": return <FindingPanel id={r} />;
    default: return <RefPanel r={r} />;
  }
}

function PanelHead({ eyebrow, title, children }: { eyebrow: ReactNode; title: ReactNode; children?: ReactNode }) {
  return (
    <header className="border-b border-rule-soft pb-2 pt-4">
      <div>{eyebrow}</div>
      <h2 className="mb-2 mt-1 text-lg">{title}</h2>
      {children}
    </header>
  );
}

function Big({ caption, children }: { caption: string; children: ReactNode }) {
  return <div className="flex flex-col"><span className="text-xs text-muted">{caption}</span><span className="text-[22px] font-semibold tabular">{children}</span></div>;
}

function History({ items }: { items: Data[] }) {
  if (!items.length) return null;
  return (
    <Section title="History">
      <ul className="text-sm">
        {items.map((h, i) => <li key={i} className={cx("py-0.5", h.undone && "line-through opacity-60")}><span className="text-muted">{when(h.sim_at)} {h.actor_name}</span> {h.text}</li>)}
      </ul>
    </Section>
  );
}

function FindingLinks({ title = "Findings", items, status }: { title?: string; items: Finding[]; status?: boolean }) {
  if (!items.length) return null;
  return (
    <Section title={title}>
      {items.map((f) => (
        <RowLink key={f.id} onClick={() => openRef(f.id)}>
          <Sev s={f.severity} /> {f.title} {status && <Pill tone={f.status === "open" ? "warning" : "ok"}>{f.status}</Pill>}
        </RowLink>
      ))}
    </Section>
  );
}

// ---------------------------------------------------------------- line
function LinePanel({ k }: { k: string }) {
  const { data: d, error } = useApi(`/api/line/${encodeURIComponent(k)}`);
  const [adj, setAdj] = useState(false);
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!d) return <Loading />;
  if (d.missing) return <p>No line {k} in this return.</p>;
  const changed = d.delta !== null && d.delta !== undefined && d.delta !== 0;
  return (
    <div>
      <PanelHead eyebrow={<><Key>{d.key}</Key> <span className="text-muted">{d.form_title}</span></>} title={d.label}>
        <div className="my-1.5 flex flex-wrap items-end gap-6">
          <Big caption="Engine v3">{changed ? <span className="text-lg text-muted line-through"><Money v={d.engine_value} /></span> : <Money v={d.engine_value} />}</Big>
          {changed && <Big caption="Workpaper"><span className="text-adjusted"><Money v={d.workpaper_value} /></span></Big>}
          <div className="flex items-center gap-1.5 text-sm text-muted"><VerifyMark s={d.verification.status} /> {verifyLabel(d.verification.status)}</div>
        </div>
        {d.needs_recompute && (
          <p className="rounded bg-warning-tint px-2.5 py-1.5 text-sm text-warning">
            Needs engine recompute: an upstream adjustment changes this line through engine logic ({d.stale[0]}). The tax effect is carried by that adjustment.
          </p>
        )}
        <Row>
          {can("adjust") && <Button onClick={() => setAdj(true)}>Adjust</Button>}
          <VerifyBox target={d.key} />
          <Attach target={d.key} />
        </Row>
      </PanelHead>
      {adj && <AdjustModal line={d} onClose={() => setAdj(false)} />}

      <FindingLinks items={d.findings} status />

      <Section title="How it was built">
        <p className="text-sm"><b>{d.rule}</b> {d.rule_text}{d.note ? <span className="text-muted"> {d.note}</span> : null}</p>
        {d.trace.inputs?.length > 0 && (
          <table className={TABLE}>
            <tbody>
              {d.trace.inputs.map((c: Data) => (
                <tr key={c.key} className="hover:bg-evidence-tint">
                  <td className={cx(TD, "w-3.5 text-center font-semibold text-muted")}>{c.sign === -1 ? "−" : c.sign === 1 ? "+" : ""}</td>
                  <td className={TD}>
                    <button type="button" className="text-left hover:text-evidence" onClick={() => openRef(c.key)}>
                      <VerifyMark s={c.verify === "unverified" ? "" : c.verify} /> <Key>{c.key}</Key> {c.label}
                    </button>
                  </td>
                  <td className={cx(TD, NUM)}><Money v={c.value} />{c.adjusted && <div className="font-semibold text-adjusted"><Money v={c.workpaper} /></div>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {d.summarized && (
          <p className="text-muted">
            {d.summarized.count} inputs totalling <Money v={d.summarized.sum} />. Showing the 12 largest and any that were adjusted or flagged ({d.summarized.flagged.length}). The full list is in Records, Sales detail.
          </p>
        )}
        {d.trace.sources?.length > 0 && <Sources items={d.trace.sources} />}
      </Section>

      {d.path_to_total.length > 1 && (
        <Section title="Where it goes">
          <div className="flex flex-wrap items-center gap-0.5">
            {d.path_to_total.map((p: Data, i: number) => (
              <span key={p.key} className="inline-flex items-center">
                {i > 0 && <span role="img" aria-label={p.linear ? "sum or carry" : "engine computation"} title={p.linear ? "Sum or carry" : "Engine computation"}
                  className={cx("mx-[3px] inline-block h-0.5 w-[18px] align-middle", p.linear ? "bg-muted" : "bg-[repeating-linear-gradient(90deg,rgb(var(--muted))_0_3px,transparent_3px_6px)]")} />}
                <Ref r={p.key} label={p.key} title={p.label} />
              </span>
            ))}
          </div>
          <p className="text-muted">Used by {d.used_by_count} line{d.used_by_count === 1 ? "" : "s"}. Dashed steps are engine computations (limits, tables), not plain sums.</p>
        </Section>
      )}

      {d.adjustments.length > 0 && <Section title="Adjustments">{d.adjustments.map((a: Adjustment) => <AdjustmentRow key={a.id} a={a} />)}</Section>}

      {(d.prior || d.variance) && (
        <Section title="Last year">
          {d.prior && <p>2024: <Money v={d.prior.value} /> <span className="text-muted">{d.prior.label}{d.prior.source ? `, from ${d.prior.source}` : ""}</span></p>}
          {d.variance && <VarianceBox v={d.variance} ex={d.explanation} />}
        </Section>
      )}

      {(d.version_changes.length > 0 || Object.values(d.versions).some((x) => x !== d.engine_value)) && (
        <Section title="Engine versions">
          <div className="flex flex-wrap gap-[18px] text-sm">{Object.entries(d.versions).map(([v, x]) => <span key={v}><b>{v}</b> <Money v={x} /></span>)}</div>
          {d.version_changes.map((c: Data, i: number) => (
            <p key={i} className="text-muted">{c.version}: {c.change} {c.old !== undefined ? <>from <Money v={c.old} /> </> : null}to <Money v={c.new} />. {c.trigger}</p>
          ))}
        </Section>
      )}

      <Section title="Verification">
        {d.verification.records.map((v: Data, i: number) => {
          const stale = d.verification.stale.some((s: Data) => s.at === v.at && s.by === v.by);
          return (
            <p key={i} className={stale ? "text-warning" : ""}>
              <VerifyMark s="verified" /> {v.method.replace(/_/g, " ")} by <Who id={v.by} /> {when(v.at)} at <Money v={v.value} />{v.note ? `: ${v.note}` : ""}{stale ? " (value changed since; re-verify)" : ""}
            </p>
          );
        })}
        {d.verification.machine.map((m: Data, i: number) => <p key={`m${i}`}><VerifyMark s="recalculated" /> {m.title}: {m.detail}</p>)}
        {!d.verification.records.length && !d.verification.machine.length && <p className="text-muted">Not verified yet.</p>}
      </Section>

      <Section title="Notes"><Notes target={d.key} notes={d.notes} /><Attachments items={d.attachments} /></Section>
      <History items={d.history} />
    </div>
  );
}

export function VarianceBox({ v, ex }: { v: Data; ex: Data | null }) {
  const [text, setText] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    try { await cmd({ type: "explain_variance", key: v.key, text }); setText(""); } catch { /* reported */ }
  };
  return (
    <div className="rounded bg-sunk px-2.5 py-1.5">
      <p>Change vs 2024 <Money v={v.change} sign /> {v.pct !== null ? `(${(v.pct * 100).toFixed(0)}%)` : "(new)"}: over the firm's threshold.</p>
      {ex ? <p><VerifyMark s="verified" /> Explained by <Who id={ex.by} />: {ex.text}</p> : can("verify") && (
        <form className="my-2 flex flex-wrap gap-2" onSubmit={submit}>
          <input aria-label="Explanation" className="min-w-[14rem] flex-1" placeholder="Explain the swing (e.g. moved to Texas mid-year)" value={text} onChange={(e) => setText(e.target.value)} />
          <Button type="submit" disabled={!text.trim()}>Explain</Button>
        </form>
      )}
    </div>
  );
}

function Sources({ items }: { items: Data[] }) {
  return (
    <ul className="my-2 flex flex-col rounded border border-rule-soft">
      {items.map((s, i) => (
        <li key={i} className="border-t border-rule-soft first:border-t-0">
          <button type="button" onClick={() => openRef(s.ref)}
            className="grid w-full grid-cols-[12px_56px_1fr] items-baseline gap-2 px-2.5 py-1.5 text-left text-sm hover:bg-evidence-tint sm:grid-cols-[12px_64px_1fr_auto_auto_auto]">
            <VerifyMark s={s.kind === "value" && s.verify === "verified" ? "verified" : ""} />
            <span className="font-cond font-semibold text-evidence">{s.kind === "value" ? `${s.doc} p${s.page}` : prettyRef(s.ref)}</span>
            <span>{s.title}</span>
            {s.kind === "value" ? (
              <>
                <span className="col-start-3 max-w-[220px] truncate font-cond text-muted sm:col-start-auto">“{s.text_as_read}”</span>
                <span className={cx("col-start-3 text-2xs tabular sm:col-start-auto", s.confidence < 0.9 ? "font-semibold text-warning" : "text-muted")}>{s.confidence.toFixed(2)}</span>
                {typeof s.value === "number" ? <span className={cx(NUM, "col-start-3 sm:col-start-auto")}><Money v={s.value} /></span> : <span />}
              </>
            ) : (
              <>
                {s.text ? <span className="col-start-3 max-w-[220px] truncate font-cond text-muted sm:col-start-auto">{String(s.text).slice(0, 120)}</span> : <span />}
                <span />
                {typeof s.value === "number" ? <span className={cx(NUM, "col-start-3 sm:col-start-auto")}><Money v={s.value} /></span> : <span />}
              </>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- value
function ValuePanel({ id }: { id: string }) {
  const boot = useBoot();
  const [reveal, setReveal] = useState(0);
  const { data: d, error } = useApi(`/api/value/${encodeURIComponent(id)}?reveal=${reveal}`);
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!d) return <Loading />;
  const sensitive = ["ssn", "account_number"].includes(d.value_type);
  return (
    <div>
      <PanelHead eyebrow={<><Key>{d.id}</Key> <span className="text-muted">field {d.field}</span></>} title={d.label}>
        <div className="my-1.5 flex flex-wrap items-end gap-6">
          <Big caption="Read as">“{d.text_as_read}”</Big>
          <Big caption="Confidence"><span className={d.confidence < 0.9 ? "text-warning" : ""}>{d.confidence.toFixed(2)}</span></Big>
        </div>
        <Row>
          <VerifyBox target={d.id} label="Verify against page" />
          {sensitive && boot.me.clearance && !reveal && <Button onClick={() => setReveal(1)} title="The view is logged">Reveal (logged)</Button>}
          {reveal ? <Pill tone="warning">Shown; this view was logged</Pill> : null}
        </Row>
      </PanelHead>
      <Section title="On the page">
        <Paper doc={d.document_id} title={d.doc_title} page={d.page} pageCount={d.page_count} text={d.page_text} values={d.page_values} layout={d.layout} focus={d.id} compact />
        <p><Button onClick={() => openRef(`${d.document_id}#page${d.page}`)}>Open the whole page</Button></p>
      </Section>
      <Section title="Where it landed">
        {d.landing_lines.length
          ? d.landing_lines.map((l: Data) => <RowLink key={l.key} onClick={() => openRef(l.key)}><Key>{l.key}</Key> {l.label}</RowLink>)
          : <p className="text-muted">{d.landing.reason}</p>}
      </Section>
      <FindingLinks items={d.findings} />
      {d.verifications.length > 0 && (
        <Section title="Verification">
          {d.verifications.map((v: Data, i: number) => <p key={i}><VerifyMark s="verified" /> {v.method.replace(/_/g, " ")} by <Who id={v.by} /> {when(v.at)}{v.note ? `: ${v.note}` : ""}</p>)}
        </Section>
      )}
      <Section title="Notes"><Notes target={d.id} notes={d.notes} /></Section>
    </div>
  );
}

// ---------------------------------------------------------------- document (pages in the drawer)
function DocPanel({ r }: { r: string }) {
  const m = r.match(/^(?:doc:)?(D\d\d)(?:#page?(\d+))?$/);
  const did = m?.[1] ?? r;
  const pg = m?.[2] ? parseInt(m[2], 10) : null;
  const { data: d, error } = useApi(`/api/document/${encodeURIComponent(did)}`);
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!d) return <Loading />;
  const pages: Page[] = pg ? d.pages.filter((p: Page) => p.page === pg) : d.pages.slice(0, 3);
  return (
    <div>
      <PanelHead eyebrow={<><Key>{d.id}</Key> <span className="text-muted">{d.type}, {d.issuer}, received {when(d.received_at)}</span></>} title={d.title}>
        <Row>
          <Button onClick={() => go(`doc/${d.id}${pg ? "/" + pg : ""}`)}>Open document view</Button>
          <VerifyBox target={d.id} label="Verify document" />
          <Attach target={d.id} />
        </Row>
        {d.related.length > 0 && <p>{d.related.map((x: Data) => <span key={x.ref} className="mr-3.5">{x.relation}: <Ref r={x.ref} /></span>)}</p>}
      </PanelHead>
      {pages.map((p) => <Paper key={p.page} doc={d.id} title={d.title} page={p.page} pageCount={d.page_count} text={p.text} values={p.values} layout={p.layout} unread={p.unread} compact />)}
      {!pg && d.pages.length > 3 && <p className="text-muted">{d.pages.length - 3} more pages in the document view.</p>}
      <FindingLinks title="Findings citing this document" items={d.findings} />
    </div>
  );
}

// ---------------------------------------------------------------- finding
function FindingPanel({ id }: { id: string }) {
  const { data: f, error } = useApi<Finding & Data>(`/api/finding/${encodeURIComponent(id)}`);
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!f) return <Loading />;
  return (
    <div>
      <PanelHead eyebrow={<><Sev s={f.severity} /> <span className="text-muted">{f.source === "engine" ? "Engine diagnostic" : "Independent check"} {f.code}</span></>} title={f.title}>
        <p className="text-[15px]">{f.summary}</p>
        <Row>
          <Effect e={f.effect} />
          {f.needs && <Pill tone="info">Needs {f.needs}</Pill>}
          <Pill tone={f.status === "open" ? "warning" : "ok"}>{f.status.replace("_", " ")}</Pill>
        </Row>
        {f.client_answer && <p className="rounded bg-evidence-tint px-2.5 py-1.5">Client answered: {f.client_answer}</p>}
      </PanelHead>
      <Section title="Decide"><FindingActions f={f} />{f.disposition && <p className="text-muted">{dispText(f)}</p>}</Section>
      <Section title="Evidence"><Sources items={f.evidence_resolved} /></Section>
      {f.lines.length > 0 && <Section title="Lines affected"><Row>{f.lines.map((l) => <Ref key={l} r={l} />)}</Row></Section>}
      {f.adjustments_full.length > 0 && <Section title="Adjustments made">{f.adjustments_full.map((a: Adjustment) => <AdjustmentRow key={a.id} a={a} />)}</Section>}
      <Section title="Notes"><Notes target={f.id} notes={f.notes_full} /></Section>
      <History items={f.history} />
    </div>
  );
}

// ---------------------------------------------------------------- anything else (answers, messages, prior-year records...)
function RefPanel({ r }: { r: string }) {
  const { data: d, error } = useApi(`/api/resolve?ref=${encodeURIComponent(r)}`);
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!d) return <Loading />;
  return (
    <div>
      <PanelHead eyebrow={<><Key>{r}</Key> <span className="text-muted">{String(d.kind).replace("_", " ")}</span></>} title={d.title} />
      {d.text && <blockquote className="my-3 border-l-[3px] border-rule px-3 py-1.5 text-[15px]">{d.text}</blockquote>}
      {d.by && <p className="text-muted">{d.by} {when(d.at)}</p>}
      {d.value !== undefined && d.value !== null && (typeof d.value === "object"
        ? <pre className="max-h-[360px] overflow-auto rounded bg-sunk p-2.5 text-xs">{JSON.stringify(d.value, null, 2)}</pre>
        : <p className="text-[22px] font-semibold"><Money v={d.value} /></p>)}
      {d.asset && <AssetCard a={d.asset} />}
      <Section title="Notes"><Notes target={r} notes={[]} /></Section>
    </div>
  );
}

function AssetCard({ a }: { a: Data }) {
  const rows: [string, ReactNode][] = [
    ["Activity", a.activity],
    ["Cost", <Money v={a.cost} />],
    ["Placed in service", a.placed_in_service],
    ["Method / life", `${a.method}, ${a.life_years} years`],
  ];
  if (a.federal?.depreciation_2025 !== undefined) rows.push(["Federal 2025 / accumulated", <><Money v={a.federal.depreciation_2025} /> / <Money v={a.federal.accumulated_end} /></>]);
  if (a.california?.depreciation_2025 !== undefined) rows.push(["California 2025 / accumulated", <><Money v={a.california.depreciation_2025} /> / <Money v={a.california.accumulated_end} /></>]);
  if (a.amt) rows.push(["AMT difference", <Money v={a.amt.difference_from_regular} />]);
  rows.push(["Disposed", a.disposed || "No"]);
  return (
    <table className={cx(TABLE, "my-2 text-xs")}>
      <tbody>{rows.map(([k, v]) => <tr key={k}><th scope="row" className={cx(TD, "text-left font-normal text-muted")}>{k}</th><td className={TD}>{v}</td></tr>)}</tbody>
    </table>
  );
}
