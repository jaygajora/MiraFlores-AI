// A simulated source page.
//
// Two renderers share one contract: (doc, page, text, values with character spans).
//  - Form view lays the page out as paper: heading, labelled boxes, ledger tables
//    (the layout is computed on the server from the printed content).
//  - Text view shows the printed content verbatim: the ground truth.
// Every extracted value is an anchor (a real button); clicking one continues the trace.
// A PDF renderer would implement the same props, placing anchors by position.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { openRef } from "./api";
import type { Block, PageValue, Span } from "./types";
import { Segmented, cx } from "./ui";

type Anchor = PageValue & { a: number; b: number };
type Ctx = { text: string; anchors: Anchor[]; focus?: string };
type View = "form" | "text";

const readPref = (): View => { try { return localStorage.getItem("wp.pageview") === "text" ? "text" : "form"; } catch { return "form"; } };

export function Paper(props: {
  doc: string; title: string; page: number; pageCount?: number; text: string; values: PageValue[]; focus?: string;
  unread?: boolean; compact?: boolean; layout?: Block[];
}) {
  const { doc, title, page, pageCount, text, values, focus, unread, compact, layout } = props;
  const [view, setView] = useState<View>(readPref);
  const anchors: Anchor[] = values.filter((v) => v.span).map((v) => ({ ...v, a: v.span![0], b: v.span![1] })).sort((x, y) => x.a - y.a || y.b - x.b);
  const missing = values.filter((v) => !v.span);
  const canForm = !!layout?.length;
  const mode: View = canForm ? view : "text";
  const pick = (m: View) => { try { localStorage.setItem("wp.pageview", m); } catch { /* storage unavailable */ } setView(m); };
  const ctx: Ctx = { text, anchors, focus };
  const ref = useRef<HTMLElement>(null);

  // Scroll the focused value into view inside a compact page.
  useEffect(() => {
    const el = ref.current?.querySelector<HTMLElement>("[data-focus='true']");
    const box = ref.current?.querySelector<HTMLElement>("[data-scroll]");
    if (el && box && box.scrollHeight > box.clientHeight) {
      const top = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
      box.scrollTop = Math.max(0, top - box.clientHeight / 3);
    }
  }, [focus, mode]);

  return (
    <figure ref={ref} className={cx("my-3.5 max-w-[min(760px,100%)] rounded-sm border bg-page shadow-paper", unread ? "border-dashed border-warning" : "border-page-edge")}>
      <figcaption className="flex flex-wrap items-baseline gap-2 border-b border-rule-soft px-3 py-1.5 text-xs text-muted">
        <span className="font-cond font-semibold text-ink">{doc}</span>
        <span className="min-w-0 flex-1 truncate">{title}</span>
        <span>Page {page}{pageCount ? ` of ${pageCount}` : ""}</span>
        {canForm && <Segmented size="sm" label="Page view" value={mode} onChange={pick} options={[["form", "Form"], ["text", "Text"]]} />}
      </figcaption>
      {unread && <div className="bg-warning-tint px-3 py-1 text-xs font-semibold text-warning">The pipeline did not read this page.</div>}
      {mode === "text" ? (
        <div data-scroll className={cx("whitespace-pre-wrap font-serif", compact ? "max-h-80 overflow-auto px-3.5 py-3 text-sm leading-[1.75]" : "px-[22px] pb-[22px] pt-[18px] text-base leading-[1.9]")}>
          {seg(ctx, 0, text.length)}
        </div>
      ) : (
        <div data-scroll className={cx("font-serif", compact ? "max-h-[360px] overflow-auto px-3.5 pb-3.5 pt-3" : "px-3 pb-4 pt-3.5 sm:px-[26px] sm:pb-[26px] sm:pt-[22px]")}>
          {layout!.map((b, i) => <BlockView key={i} b={b} ctx={ctx} compact={compact} />)}
        </div>
      )}
      {missing.length > 0 && !compact && (
        <div className="border-t border-dashed border-rule px-3 py-1.5 text-xs text-warning">
          Read from this page but not found in its text:{" "}
          {missing.map((m) => <button type="button" key={m.id} className="px-0.5 font-cond font-medium text-evidence underline" onClick={() => openRef(m.id)}>{m.label}</button>)}
        </div>
      )}
    </figure>
  );
}

const LOW = 0.9;
const status = (s?: Anchor) => s?.landing?.status || "none";

function tip(s: Anchor) {
  const where = s.landing?.lines?.length ? " → " + s.landing.lines.join(", ") : s.landing?.reason ? " – " + s.landing.reason : "";
  return `${s.label} (${s.id}, confidence ${s.confidence.toFixed(2)})${where}`;
}

// Text between a and b, with every anchor inside it drawn as a clickable mark.
function seg(ctx: Ctx, a: number, b: number): ReactNode[] {
  const out: ReactNode[] = [];
  let pos = a;
  for (const s of ctx.anchors) {
    if (s.b <= a || s.a >= b || s.a < pos) continue;
    if (s.a > pos) out.push(ctx.text.slice(pos, s.a));
    out.push(<Mark key={`${s.id}-${s.a}`} s={s} focus={ctx.focus} text={ctx.text.slice(Math.max(s.a, a), Math.min(s.b, b))} />);
    pos = Math.min(s.b, b);
  }
  if (pos < b) out.push(ctx.text.slice(pos, b));
  return out;
}

const MARK: Record<string, string> = {
  used: "bg-evidence-tint border-b-2 border-evidence",
  informational: "border-b border-dotted border-muted",
  not_used: "border-b border-dotted border-muted",
  superseded: "line-through decoration-muted border-b border-dotted border-muted",
  duplicate: "line-through decoration-muted border-b border-dotted border-muted",
};

function Mark({ s, focus, text }: { s: Anchor; focus?: string; text: string }) {
  const isFocus = s.id === focus;
  return (
    <button type="button" data-focus={isFocus} title={tip(s)} aria-label={`${s.label}: ${text}`}
      onClick={(e) => { e.stopPropagation(); openRef(s.id); }}
      className={cx("inline whitespace-pre-wrap px-px text-left font-sans text-[0.95em]",
        isFocus ? "rounded-sm bg-evidence text-on-accent ring-[3px] ring-evidence/25" : cx(MARK[status(s)], "hover:bg-evidence/25"),
        s.confidence < LOW && "underline decoration-warning decoration-wavy decoration-2 underline-offset-4")}>
      {text}
    </button>
  );
}

/** Legend swatches for the document view. */
export function MarkLegend() {
  return (
    <span className="inline-flex flex-wrap gap-2.5 text-xs">
      <span className={cx("px-px", MARK.used)}>used</span>
      <span className={cx("px-px", MARK.informational)}>read, not an input</span>
      <span className={cx("px-px", MARK.superseded)}>superseded</span>
      <span className="px-px underline decoration-warning decoration-wavy decoration-2 underline-offset-4">low confidence</span>
    </span>
  );
}

function anchorsIn(ctx: Ctx, span: Span | null | undefined) {
  if (!span) return [];
  return ctx.anchors.filter((s) => s.a < span[1] && span[0] < s.b);
}

const BOX_RAIL: Record<string, string> = { used: "shadow-[inset_3px_0_rgb(var(--evidence))]", informational: "shadow-[inset_3px_0_rgb(var(--rule))]", not_used: "shadow-[inset_3px_0_rgb(var(--rule))]" };
const WRAP_COLS = new Set(["item", "place", "detail", "term", "purpose"]);

function BlockView({ b, ctx, compact }: { b: Block; ctx: Ctx; compact?: boolean }) {
  if (b.type === "heading") {
    return <h4 className="mb-2.5 border-b-2 border-ink pb-2 text-base font-semibold tracking-tight">{b.spans.map(([a, z], i) => <span key={i}>{seg(ctx, a, z)} </span>)}</h4>;
  }
  if (b.type === "text") {
    return <p className="my-2 max-w-none text-[13.5px] leading-[1.7]">{b.spans.map(([a, z], i) => <span key={i}>{i > 0 ? "; " : ""}{seg(ctx, a, z)}</span>)}</p>;
  }
  if (b.type === "fields") {
    return (
      <div className={cx("my-2.5 grid border-l border-t border-page-edge", compact ? "grid-cols-[repeat(auto-fill,minmax(130px,1fr))]" : "grid-cols-[repeat(auto-fill,minmax(130px,1fr))] sm:grid-cols-[repeat(auto-fill,minmax(168px,1fr))]")}>
        {b.items.map((f, i) => {
          const an = anchorsIn(ctx, f.value_span);
          const first = an[0];
          const st = status(first);
          const isFocus = an.some((x) => x.id === ctx.focus);
          const value = ctx.text.slice(f.value_span[0], f.value_span[1]);
          const cls = cx("relative flex min-h-[54px] flex-col justify-between gap-1.5 border-b border-r border-page-edge px-2 pb-1.5 pt-[5px] text-left font-sans",
            BOX_RAIL[st], isFocus && "z-[1] bg-evidence-tint outline outline-2 -outline-offset-2 outline-evidence", first && "hover:bg-evidence-tint");
          const body = (
            <>
              <span className="font-cond text-2xs leading-tight text-muted">{f.label}</span>
              <span className={cx("break-words text-right text-[15px] font-medium tabular",
                (st === "superseded" || st === "duplicate") && "text-muted line-through",
                an.some((x) => x.confidence < LOW) && "underline decoration-warning decoration-wavy underline-offset-4",
                isFocus && "font-semibold text-evidence")}>{value}</span>
            </>
          );
          return first
            ? <button type="button" key={i} data-focus={isFocus} className={cls} title={tip(first)} onClick={() => openRef(first.id)}>{body}</button>
            : <div key={i} className={cls} title="Printed on the page; not extracted">{body}</div>;
        })}
      </div>
    );
  }
  return (
    <div className="my-2 mb-3 overflow-x-auto">
      <table className="w-full border-collapse font-sans text-[12.5px] tabular">
        <thead>
          <tr>{b.columns.map((c) => <th key={c.key} scope="col" className={cx("whitespace-nowrap border-b-[3px] border-double border-page-edge px-1.5 py-1 text-left font-cond text-2xs font-semibold text-muted", c.numeric && "text-right")}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {b.rows.map((r, ri) => {
            const focusRow = b.columns.some((c) => anchorsIn(ctx, r[c.key]).some((x) => x.id === ctx.focus));
            return (
              <tr key={ri} className={focusRow ? "bg-evidence-tint" : ""}>
                {b.columns.map((c) => {
                  const span = r[c.key];
                  if (!span) return <td key={c.key} className="border-b border-rule-soft" />;
                  const an = anchorsIn(ctx, span);
                  const st = status(an[0]);
                  const isFocus = an.some((x) => x.id === ctx.focus);
                  const text = ctx.text.slice(span[0], span[1]);
                  return (
                    <td key={c.key} className={cx("border-b border-rule-soft px-1.5 py-[3px] align-top", c.numeric && "text-right", !WRAP_COLS.has(c.key) && "whitespace-nowrap",
                      isFocus && "bg-evidence text-on-accent", (st === "superseded" || st === "duplicate") && "text-muted line-through")}>
                      {an[0] ? (
                        <button type="button" data-focus={isFocus} title={tip(an[0])} onClick={() => openRef(an[0].id)}
                          className={cx("w-full", c.numeric ? "text-right" : "text-left", !isFocus && st === "used" && "underline decoration-evidence/45 underline-offset-[3px]", !isFocus && "hover:bg-evidence-tint")}>
                          {text}
                        </button>
                      ) : text}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
