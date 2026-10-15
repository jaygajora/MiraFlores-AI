// Shared UI primitives. Styling is Tailwind utilities; color always encodes evidence state (see tailwind.config.cjs).
import { useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type FormEvent, type ReactNode } from "react";
import { getState, openRef } from "./api";
import type { Effect as EffectT, Severity, VerifyStatus } from "./types";

export const cx = (...c: (string | false | null | undefined | 0)[]) => c.filter(Boolean).join(" ");

// ---------------------------------------------------------------- numbers and dates
export function fmt(x: unknown, opts: { sign?: boolean } = {}): string {
  if (x === null || x === undefined || x === "") return "";
  if (typeof x !== "number") return String(x);
  const abs = Math.abs(x);
  const s = abs.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: Number.isInteger(abs) ? 0 : 2 });
  if (opts.sign) return (x < 0 ? "−" : x > 0 ? "+" : "") + s;
  return x < 0 ? `(${s})` : s;
}

export function when(iso?: string | null) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function Money({ v, sign, className }: { v: unknown; sign?: boolean; className?: string }) {
  if (v === null || v === undefined) return <span className="text-muted">–</span>;
  return <span className={cx("tabular whitespace-nowrap", className)}>{fmt(v, { sign })}</span>;
}

export function Effect({ e, compact }: { e?: EffectT | null; compact?: boolean }) {
  if (!e) return null;
  const parts: [string, number | undefined][] = [["Fed tax", e.fed_tax], ["CA tax", e.ca_tax], ["Fed payments", e.fed_payments], ["CA payments", e.ca_payments]];
  const shown = parts.filter(([, v]) => v);
  if (!shown.length) return compact ? null : <span className="text-muted">No tax effect</span>;
  return (
    <span className="inline-flex flex-wrap gap-x-2.5 text-sm">
      {shown.map(([label, v]) => <span key={label}>{label} <Money v={v} sign className="font-semibold" /></span>)}
    </span>
  );
}

// ---------------------------------------------------------------- refs: the one interactive vocabulary
export type RefKind = "line" | "value" | "document" | "answer" | "message" | "prior_year" | "agency" | "asset" | "finding" | "household" | "parameter" | "timeline" | "event";

export function guessKind(r: string): RefKind {
  if (r.startsWith("ev-")) return "value";
  if (/^(doc:)?D\d\d/.test(r)) return "document";
  if (r.startsWith("qa-")) return "answer";
  if (r.startsWith("msg-") || r.startsWith("call-")) return "message";
  if (r.startsWith("py:")) return "prior_year";
  if (r.startsWith("agency:")) return "agency";
  if (r.startsWith("asset:")) return "asset";
  if (r.startsWith("F-") || r.startsWith("ENG-")) return "finding";
  if (r.startsWith("household:")) return "household";
  if (r.startsWith("ref:")) return "parameter";
  if (r.startsWith("timeline:")) return "timeline";
  if (r.startsWith("e-")) return "event";
  return "line";
}

export function prettyRef(r: string): string {
  const m = r.match(/^(?:doc:)?(D\d\d)#page?(\d+)$/);
  if (m) return `${m[1]} p${m[2]}`;
  if (r.startsWith("py:/return_2024/lines/")) return `2024 ${r.slice(22)}`;
  if (r.startsWith("py:/")) return "2024 record";
  if (r.startsWith("agency:/irs")) return "IRS transcript";
  if (r.startsWith("agency:/ftb")) return "FTB account";
  if (r.startsWith("agency:")) return "agency record";
  if (r.startsWith("ref:fx.SEK.")) return `SEK ${r.slice(11).replace("_", " ")}`;
  if (r.startsWith("ref:param.")) return r.slice(10);
  if (r.startsWith("household:")) return r.slice(10);
  if (r.startsWith("asset:")) return r.slice(6);
  return r;
}

export function Ref({ r, label, title }: { r: string; label?: string; title?: string }) {
  if (!r) return null;
  return (
    <button type="button" title={title || r}
      className="px-0.5 font-cond font-medium text-evidence underline decoration-evidence/35 underline-offset-2 hover:decoration-evidence"
      onClick={(e) => { e.stopPropagation(); openRef(r); }}>
      {label || prettyRef(r)}
    </button>
  );
}

/** A full-width row that opens a ref: a real button, so it is reachable by keyboard. */
export function RowLink({ onClick, children, className }: { onClick: () => void; children: ReactNode; className?: string }) {
  return (
    <button type="button" onClick={onClick}
      className={cx("block w-full border-t border-rule-soft py-1.5 text-left first:border-t-0 hover:text-evidence", className)}>
      {children}
    </button>
  );
}

// ---------------------------------------------------------------- marks, pills, tags
export type Tone = "error" | "warning" | "ok" | "info" | "neutral" | "adjusted";
const TONE: Record<Tone, string> = {
  error: "bg-error-tint text-error", warning: "bg-warning-tint text-warning", ok: "bg-verified/15 text-verified",
  info: "bg-evidence-tint text-evidence", neutral: "bg-sunk text-muted", adjusted: "bg-adjusted-tint text-adjusted",
};

export function Pill({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={cx("inline-block whitespace-nowrap rounded-full px-2 py-px text-xs", TONE[tone], className)}>{children}</span>;
}

export function Tag({ children, ok }: { children: ReactNode; ok?: boolean }) {
  return <span className={cx("mr-1 inline-block rounded-sm border border-rule-soft px-1.5 text-xs", ok ? "text-verified" : "text-muted")}>{children}</span>;
}

export function Count({ n }: { n: number }) {
  return <span className="ml-1 text-[0.8em] font-normal text-muted">{n}</span>;
}

export function Key({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cx("whitespace-nowrap font-cond font-semibold", className)}>{children}</span>;
}

export function Badge({ n, title }: { n: number; title?: string }) {
  return <span title={title} className="ml-1.5 inline-grid h-[18px] min-w-[18px] place-items-center rounded-full bg-error-tint px-1.5 text-2xs font-semibold text-error">{n}</span>;
}

const VMARK: Record<string, string> = {
  verified: "bg-verified border-verified", recalculated: "border-recalc bg-recalc/20", stale: "border-warning bg-warning-tint",
  unverified: "border-rule", "": "border-rule",
};
const VLABEL: Record<string, string> = { verified: "Verified by a person", recalculated: "Recalculated independently", stale: "Changed since verified; re-verify", unverified: "Not verified", "": "Not verified" };

/** A filled square is a person's check; an outlined teal one is an independent recalculation. */
export function VerifyMark({ s }: { s: VerifyStatus | string }) {
  return <span role="img" aria-label={VLABEL[s] ?? s} title={VLABEL[s] ?? s} className={cx("inline-block h-[9px] w-[9px] shrink-0 rounded-[2px] border-[1.5px] align-middle", VMARK[s] ?? VMARK[""])} />;
}
export const verifyLabel = (s: string) => VLABEL[s] ?? s;

const SEV: Record<Severity, string> = { error: "bg-error", warning: "bg-warning", info: "bg-muted" };
export const SEV_RAIL: Record<Severity, string> = { error: "border-l-error", warning: "border-l-warning", info: "border-l-rule" };
export function Sev({ s }: { s: Severity }) {
  return <span role="img" aria-label={s} title={s} className={cx("inline-block h-2 w-2 shrink-0 rounded-full align-middle", SEV[s])} />;
}

// ---------------------------------------------------------------- controls
type Variant = "default" | "primary" | "ghost" | "danger";
const BTN: Record<Variant, string> = {
  default: "border-rule bg-surface text-ink hover:border-muted",
  primary: "border-evidence bg-evidence text-on-accent hover:bg-evidence/90",
  ghost: "border-transparent bg-transparent text-evidence hover:bg-evidence-tint",
  danger: "border-error bg-surface text-error hover:bg-error-tint",
};
export const buttonClass = (variant: Variant = "default", className?: string) =>
  cx("inline-flex items-center gap-1.5 whitespace-nowrap rounded border px-[11px] py-[5px] text-sm no-underline disabled:cursor-not-allowed disabled:opacity-50", BTN[variant], className);

export function Button({ variant = "default", className, type = "button", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button type={type} className={buttonClass(variant, className)} {...rest} />;
}

export function Field({ label, children, className }: { label: ReactNode; children: ReactNode; className?: string }) {
  return <label className={cx("my-2 flex flex-col gap-1 text-sm text-muted [&>input]:text-ink [&>select]:text-ink [&>textarea]:text-ink", className)}>{label}{children}</label>;
}

export function Check({ checked, onChange, children, className }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode; className?: string }) {
  return (
    <label className={cx("flex items-start gap-1.5 text-ink", className)}>
      <input type="checkbox" className="mt-[3px]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{children}</span>
    </label>
  );
}

export function Row({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("my-2 flex flex-wrap items-center gap-2", className)}>{children}</div>;
}

export function Segmented<T extends string>({ value, options, onChange, label, size = "md" }: { value: T; options: [T, string][]; onChange: (v: T) => void; label: string; size?: "sm" | "md" }) {
  return (
    <span role="group" aria-label={label} className="inline-flex overflow-hidden rounded border border-rule">
      {options.map(([k, t]) => (
        <button key={k} type="button" aria-pressed={value === k} onClick={() => onChange(k)}
          className={cx(size === "sm" ? "px-2 py-px text-2xs" : "px-3 py-[5px] text-sm",
            value === k ? (size === "sm" ? "bg-ink text-surface" : "bg-evidence-tint font-semibold text-evidence") : "bg-surface text-muted")}>
          {t}
        </button>
      ))}
    </span>
  );
}

export function Tabs<T extends string>({ value, tabs, onChange }: { value: T; tabs: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div role="tablist" className="mb-4 mt-2 flex gap-0.5 overflow-x-auto border-b border-rule">
      {tabs.map(([k, t]) => (
        <button key={k} role="tab" type="button" aria-selected={value === k} onClick={() => onChange(k)}
          className={cx("-mb-px whitespace-nowrap border-b-2 px-3 py-2", value === k ? "border-evidence font-semibold text-ink" : "border-transparent text-muted hover:text-ink")}>
          {t}
        </button>
      ))}
    </div>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("my-2 rounded border border-rule bg-surface p-3", className)}>{children}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="my-3 rounded border border-dashed border-rule p-7 text-muted">{children}</div>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div role="status" className="p-7 text-muted">{label}</div>;
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return <div role="alert" className="my-3 rounded border border-error bg-error-tint p-4 text-error">{children}</div>;
}

export function Section({ title, children, className }: { title?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={cx("border-b border-rule-soft pb-2.5 last:border-b-0", className)}>{title && <h3>{title}</h3>}{children}</section>;
}

export function Who({ id }: { id: string }) {
  const u = getState().boot?.users.find((x) => x.id === id);
  return <span className="font-semibold">{u ? u.name : id === "system" ? "System" : id}</span>;
}

// ---------------------------------------------------------------- dialogs
/** Accessible modal: labelled, traps Tab inside, closes on Escape, and returns focus to where it was. */
export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const el = ref.current!;
    el.querySelector<HTMLElement>("input,textarea,select,button:not([data-close])")?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); close.current(); }
      if (e.key !== "Tab") return;
      const f = [...el.querySelectorAll<HTMLElement>("a[href],button:not(:disabled),input:not(:disabled),select,textarea,[tabindex]:not([tabindex='-1'])")];
      if (!f.length) return;
      const [first, last] = [f[0], f[f.length - 1]];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    el.addEventListener("keydown", key);
    return () => { el.removeEventListener("keydown", key); before?.focus?.(); };
  }, []);
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-[rgb(15_22_30/0.42)] p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId}
        className={cx("max-h-[90vh] w-full overflow-auto rounded-md bg-surface shadow-modal", wide ? "max-w-[900px]" : "max-w-[560px]")}>
        <header className="flex items-center justify-between border-b border-rule px-4 py-3">
          <h2 id={titleId} className="m-0">{title}</h2>
          <CloseButton onClick={onClose} label="Close dialog" />
        </header>
        <div className="px-4 pb-4 pt-2">{children}</div>
      </div>
    </div>
  );
}

export function CloseButton({ onClick, label, className }: { onClick: () => void; label: string; className?: string }) {
  return <button type="button" data-close onClick={onClick} aria-label={label} className={cx("px-2 py-0.5 text-[22px] leading-none text-muted hover:text-ink", className)}>×</button>;
}

/** Replaces window.confirm: says what will happen and what gets recorded. */
export function ConfirmDialog({ title, children, confirm, variant = "primary", onConfirm, onClose }: {
  title: string; children: ReactNode; confirm: string; variant?: Variant; onConfirm: () => Promise<unknown> | void; onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={title} onClose={onClose}>
      <div className="text-sm">{children}</div>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant={variant} disabled={busy} onClick={async () => {
          setBusy(true);
          try { await onConfirm(); onClose(); } catch { setBusy(false); }
        }}>{confirm}</Button>
      </div>
    </Modal>
  );
}

/** The small form every judgment needs: a reason, and the authority relied on. */
export function ReasonForm({ onSubmit, submit = "Save", authority = true, placeholder = "Why", initial = "", extra, onCancel }: {
  onSubmit: (reason: string, authority: string) => Promise<unknown> | void; submit?: string; authority?: boolean; placeholder?: string;
  initial?: string; extra?: ReactNode; onCancel?: () => void;
}) {
  const [reason, setReason] = useState(initial);
  const [auth, setAuth] = useState("");
  const [busy, setBusy] = useState(false);
  const handle = async (e: FormEvent) => {
    e.preventDefault();
    if (!reason.trim()) return;
    setBusy(true);
    try { await onSubmit(reason.trim(), auth.trim()); } catch { /* the toast reported it; keep the form */ } finally { setBusy(false); }
  };
  return (
    <form onSubmit={handle}>
      <Field label="Reason"><textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder={placeholder} rows={3} required /></Field>
      {authority && <Field label="Authority relied on"><input value={auth} onChange={(e) => setAuth(e.target.value)} placeholder="Code section, regulation, publication or firm policy" /></Field>}
      {extra}
      <div className="mt-2 flex justify-end gap-2">
        {onCancel && <Button onClick={onCancel}>Cancel</Button>}
        <Button variant="primary" type="submit" disabled={busy || !reason.trim()}>{submit}</Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- tables
export const TABLE_WRAP = "overflow-x-auto rounded border border-rule bg-surface";
export const TABLE = "w-full border-collapse text-sm";
export const TH = "sticky top-0 whitespace-nowrap border-b border-rule bg-sunk px-2.5 py-[7px] text-left text-xs font-semibold text-muted";
export const TD = "border-b border-rule-soft px-2.5 py-1.5 align-top";
export const NUM = "text-right tabular whitespace-nowrap";
export const ROW_CLICK = "cursor-pointer hover:bg-evidence-tint";

export type Col = { key: string; label: string; type?: "money" | "ref" | "status" | string };

/** Server-described tables (records, what-ifs). Rows with a ref open it; the ref cell is a keyboard-reachable button. */
export function DataTable({ columns, rows, onRow }: { columns: Col[]; rows: Record<string, unknown>[]; onRow?: (r: Record<string, unknown>) => void }) {
  return (
    <div className={TABLE_WRAP}>
      <table className={TABLE}>
        <thead><tr>{columns.map((c) => <th key={c.key} scope="col" className={cx(TH, c.type === "money" && "text-right")}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={cx("[&:last-child>td]:border-b-0", onRow && r.ref ? ROW_CLICK : "", r.adj ? "[&>td:first-child]:shadow-[inset_3px_0_rgb(var(--adjusted))]" : "")}
              onClick={onRow && r.ref ? () => onRow(r) : undefined}>
              {columns.map((c, ci) => (
                <td key={c.key} className={cx(TD, c.type === "money" && NUM)}>
                  {ci === 0 && onRow && r.ref && c.type !== "ref"
                    ? <button type="button" className="text-left hover:text-evidence" onClick={(e) => { e.stopPropagation(); onRow(r); }}><Cell c={c} v={r[c.key]} row={r} /></button>
                    : <Cell c={c} v={r[c.key]} row={r} />}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Cell({ c, v, row }: { c: Col; v: unknown; row: Record<string, unknown> }) {
  if (c.type === "money") {
    return <>{v === null || v === undefined ? "" : <Money v={v} />}{c.key === "workpaper" && row.stale ? <span className="ml-1 font-semibold text-warning" title="Needs engine recompute: upstream adjustment">↻</span> : null}</>;
  }
  if (c.type === "ref") return typeof v === "string" && v ? <Ref r={v} /> : null;
  if (c.type === "status") {
    const s = String(v ?? "");
    const tone = /^(ok|done)$/i.test(s) ? "text-verified" : /^(open|no)$/i.test(s) ? "font-semibold text-error" : "";
    return s ? <span className={cx("text-xs", tone)}>{s}</span> : null;
  }
  return <>{v === null || v === undefined ? "" : String(v)}</>;
}
