// Shared actions: adjust, verify, note threads, attachments, finding dispositions.
import { useRef, useState, type FormEvent } from "react";
import { api, bump, can, cmd, me, run, toast, useBoot, userLink, userName } from "./api";
import type { Adjustment, Data, Finding, Note } from "./types";
import { Button, Check, Effect, Field, Modal, Money, NUM, Pill, ReasonForm, Row, Segmented, TABLE, TD, TH, Who, cx, fmt, when } from "./ui";

export function AdjustModal({ line, onClose }: { line: Data; onClose: () => void }) {
  const boot = useBoot();
  const base: number = line.workpaper_value ?? line.engine_value ?? 0;
  const [mode, setMode] = useState<"value" | "delta">("value");
  const [v, setV] = useState(String(base));
  const [cat, setCat] = useState<string>(line.category);
  const num = parseFloat(v.replace(/,/g, ""));
  const delta = mode === "value" ? num - base : num;
  const valid = !Number.isNaN(delta) && delta !== 0;
  return (
    <Modal title={`Adjust ${line.key}`} onClose={onClose}>
      <p className="text-muted">{line.label}. The engine's value stays on record; the adjustment is a new entry with who, why and its tax effect.</p>
      <div className="my-1.5"><Segmented label="Enter as" value={mode} onChange={setMode} options={[["value", "New value"], ["delta", "Change by"]]} /></div>
      <Field label={mode === "value" ? "Workpaper value" : "Change"}><input inputMode="decimal" className="text-right" value={v} onChange={(e) => setV(e.target.value)} /></Field>
      <p>Engine <Money v={line.engine_value} /> → workpaper <Money v={base + (valid ? delta : 0)} /> (change <Money v={valid ? delta : 0} sign />)</p>
      <Field label="Tax effect measured as">
        <select value={cat} onChange={(e) => setCat(e.target.value)}>
          {Object.entries(boot.effect_categories).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
        </select>
      </Field>
      <ReasonForm submit="Record adjustment" onCancel={onClose} onSubmit={async (reason, authority) => {
        if (!valid) { toast("Enter a change", undefined, true); return; }
        await cmd({ type: "adjust", line: line.key, delta, reason, authority, category: cat });
        onClose();
      }} />
    </Modal>
  );
}

export function VerifyBox({ target, onDone, label = "Verify" }: { target: string | string[]; onDone?: () => void; label?: string }) {
  const boot = useBoot();
  const [open, setOpen] = useState(false);
  const [method, setMethod] = useState("agreed_to_source_document");
  const [note, setNote] = useState("");
  if (!can("verify")) return null;
  if (!open) return <Button onClick={() => setOpen(true)}>{label}</Button>;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await cmd(Array.isArray(target) ? { type: "verify", targets: target, method, note } : { type: "verify", target, method, note });
      setOpen(false);
      onDone?.();
    } catch { /* reported */ }
  };
  return (
    <form className="flex flex-wrap items-center gap-1.5" onSubmit={submit}>
      <select aria-label="Verification method" value={method} onChange={(e) => setMethod(e.target.value)}>
        {boot.standards.verification_types.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
      </select>
      <input aria-label="What you checked" placeholder="What you checked (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
      <Button variant="primary" type="submit">Record</Button>
      <Button onClick={() => setOpen(false)}>Cancel</Button>
    </form>
  );
}

export function Notes({ target, notes }: { target: string; notes: Note[] }) {
  const boot = useBoot();
  const [text, setText] = useState("");
  const [blocking, setBlocking] = useState(false);
  const [assignee, setAssignee] = useState("");
  const staff = boot.users.filter((u) => u.role !== "client" && u.id !== boot.me.id);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    try {
      await cmd({ type: "note", target, text, blocking, assignee: assignee || undefined });
      setText(""); setBlocking(false); setAssignee("");
    } catch { /* reported */ }
  };
  return (
    <div className="flex flex-col gap-2">
      {notes.map((n) => <Thread key={n.id} n={n} />)}
      {can("note") && (
        <form onSubmit={submit}>
          <textarea className="w-full" rows={2} aria-label="New note" placeholder="Note, question for a colleague, or review note" value={text} onChange={(e) => setText(e.target.value)} />
          <Row>
            <select value={assignee} onChange={(e) => setAssignee(e.target.value)} aria-label="Assign to">
              <option value="">Not assigned</option>
              {staff.map((u) => <option key={u.id} value={u.id}>Ask {u.name}</option>)}
            </select>
            {can("blocking_note") && <Check checked={blocking} onChange={setBlocking}>Blocks filing</Check>}
            <Button variant="primary" type="submit" disabled={!text.trim()}>Add note</Button>
          </Row>
        </form>
      )}
    </div>
  );
}

export function Thread({ n }: { n: Note }) {
  const [reply, setReply] = useState("");
  const open = n.status === "open";
  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (!reply.trim()) return;
    try { await cmd({ type: "reply", note: n.id, text: reply }); setReply(""); } catch { /* reported */ }
  };
  return (
    <div className={cx("rounded border bg-surface px-2.5 py-2", n.blocking && open ? "border-error" : "border-rule-soft", !open && "opacity-75")}>
      <div className="flex flex-wrap gap-1.5">
        {n.blocking && <Pill tone="error">Blocks filing</Pill>}
        {n.assignee && <Pill tone="info">For {userName(n.assignee)}</Pill>}
        <Pill tone={open ? "warning" : "ok"}>{n.status}</Pill>
      </div>
      {n.thread.map((m, i) => (
        <div key={i}><Who id={m.by} /> <span className="text-muted">{when(m.at)}</span><p className="mb-1.5 mt-0.5">{m.text}</p></div>
      ))}
      {open ? (
        <form className="my-2 flex flex-wrap items-center gap-2" onSubmit={send}>
          <input aria-label="Reply" placeholder="Reply" value={reply} onChange={(e) => setReply(e.target.value)} className="min-w-[12rem] flex-1" />
          <Button type="submit" disabled={!reply.trim()}>Reply</Button>
          {can("resolve_note") && <Button onClick={() => run({ type: "resolve_note", note: n.id, text: reply || undefined })}>Resolve</Button>}
        </form>
      ) : can("note") && <Button onClick={() => run({ type: "reopen_note", note: n.id })}>Reopen</Button>}
    </div>
  );
}

const MAX_UPLOAD = 8 * 1024 * 1024;

export function Attach({ target }: { target: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  if (!can("attach")) return null;
  const upload = async (f: File) => {
    if (f.size > MAX_UPLOAD) { toast(`${f.name} is over 8 MB`, undefined, true); return; }
    setBusy(true);
    try {
      const buf = new Uint8Array(await f.arrayBuffer());
      let bin = "";
      for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
      await api("/api/upload", { method: "POST", body: JSON.stringify({ target, name: f.name, mime: f.type, content: btoa(bin) }) });
      toast(`Attached ${f.name} as evidence`);
      bump();
    } catch (err) {
      toast((err as Error).message, undefined, true);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  return (
    <>
      <Button disabled={busy} onClick={() => input.current?.click()}>{busy ? "Attaching…" : "Attach file"}</Button>
      <input ref={input} type="file" className="hidden" aria-hidden tabIndex={-1} onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); }} />
    </>
  );
}

export function Attachments({ items }: { items?: Data[] }) {
  if (!items?.length) return null;
  return (
    <ul className="pl-[18px] text-sm">
      {items.map((a) => (
        <li key={a.file.id}>
          <a href={userLink(`/api/files/${a.file.id}`)} target="_blank" rel="noopener noreferrer">{a.name}</a>{" "}
          <span className="text-muted">{fmt(a.file.size)} bytes, <Who id={a.by} />, {when(a.at)}, sha256 {a.file.sha256.slice(0, 10)}</span>
        </li>
      ))}
    </ul>
  );
}

export function FindingActions({ f, compact }: { f: Finding; compact?: boolean }) {
  const boot = useBoot();
  const [mode, setMode] = useState<"" | "dismiss" | "client" | "decide">("");
  if (!can("dispose_finding")) return null;
  const open = f.status === "open" || f.status === "client_answered";
  if (!open) {
    return (
      <Row>
        <span className="text-muted">{dispText(f)}</span>
        {f.disposition && <Button onClick={() => run({ type: "undo", event: f.disposition!.id })} title="Undo the disposition (and any adjustments in the same action)">Undo</Button>}
      </Row>
    );
  }
  const has = f.suggestions.length > 0;
  const done = () => setMode("");
  return (
    <div className="my-1.5">
      <Row>
        {has
          ? <Button variant="primary" onClick={() => run({ type: "accept_finding", finding: f.id })}>Accept and adjust</Button>
          : <Button variant="primary" aria-expanded={mode === "decide"} onClick={() => setMode(mode === "decide" ? "" : "decide")}>{f.kind === "planning" || f.kind === "judgment" ? "Record decision" : "Resolve"}</Button>}
        <Button aria-expanded={mode === "client"} onClick={() => setMode(mode === "client" ? "" : "client")}>Ask the client</Button>
        <Button aria-expanded={mode === "dismiss"} onClick={() => setMode(mode === "dismiss" ? "" : "dismiss")}>Dismiss</Button>
      </Row>
      {mode === "dismiss" && <ReasonForm submit="Dismiss finding" placeholder="Why this is not a problem" onCancel={done}
        onSubmit={(reason, authority) => cmd({ type: "dismiss_finding", finding: f.id, reason, authority }).then(done)} />}
      {mode === "decide" && <ReasonForm submit="Record" placeholder="What you decided and why" onCancel={done}
        onSubmit={(reason, authority) => cmd({ type: "decide", topic: f.id, choice: "resolved", rationale: reason, authority: authority || "Firm judgment", finding: f.id }).then(done)} />}
      {mode === "client" && <ClientAsk f={f} onDone={done} />}
      {!compact && has && (
        <table className={cx(TABLE, "my-2 text-xs")}>
          <thead><tr><th className={TH}>Line</th><th className={cx(TH, "text-right")}>Change</th><th className={TH}>Measured as</th><th className={TH}>Note</th></tr></thead>
          <tbody>
            {f.suggestions.map((s, i) => (
              <tr key={i}><td className={TD}>{s.line}</td><td className={cx(TD, NUM)}><Money v={s.delta} sign /></td><td className={TD}>{boot.effect_categories[s.category]}</td><td className={TD}>{s.note}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ClientAsk({ f, onDone }: { f: Finding; onDone: () => void }) {
  const [text, setText] = useState(f.needs ? `Please confirm: ${f.title}. ${f.summary.slice(0, 220)}` : "");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    try { await cmd({ type: "finding_to_client", finding: f.id, text }); onDone(); } catch { /* reported */ }
  };
  return (
    <form onSubmit={submit}>
      <Field label="Question for the client (they see this in their portal; the answer becomes evidence)"><textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} required /></Field>
      <div className="flex justify-end gap-2"><Button onClick={onDone}>Cancel</Button><Button variant="primary" type="submit" disabled={!text.trim()}>Send to client</Button></div>
    </form>
  );
}

const DISP: Record<string, string> = { adjusted: "Adjusted", accepted: "Accepted", dismissed: "Dismissed", waiting_client: "Waiting on client", decided: "Decision recorded", deferred: "Deferred" };

export function dispText(f: Finding) {
  const d = f.disposition;
  if (!d) return "";
  return `${DISP[d.disposition] || d.disposition} by ${userName(d.by)} ${when(d.at)}${d.reason ? ": " + d.reason : ""}${d.authority ? " (" + d.authority + ")" : ""}`;
}

export function AdjustmentRow({ a }: { a: Adjustment }) {
  const [reverting, setReverting] = useState(false);
  const active = a.status !== "reverted";
  const approved = a.approvals?.map((x) => `${x.level} ${userName(x.by)}`).join(", ");
  return (
    <div className={cx("my-1.5 flex justify-between gap-2.5 rounded-r border-l-[3px] px-2.5 py-2 text-sm", active ? "border-l-adjusted bg-adjusted-tint" : "border-l-rule bg-sunk opacity-70")}>
      <div>
        <b><Money v={a.delta} sign /></b> on {a.line}{" "}
        <span className="text-muted">({a.engine_value !== null && a.engine_value !== undefined ? <>engine <Money v={a.engine_value} /></> : "new line"})</span>
        <div>{a.reason}{a.authority ? <span className="text-muted"> Authority: {a.authority}</span> : null}</div>
        <div className="text-muted">
          <Who id={a.by} /> {when(a.at)}. <Effect e={a.effect} />{approved ? `. Approved: ${approved}` : ". Not yet approved"}
          {!active ? `. Reverted: ${a.revert_reason || ""}` : ""}
        </div>
      </div>
      {active && (
        <div className="flex flex-col gap-1">
          {(can("approve:reviewer") || can("approve:partner")) && a.by !== me().id && <Button onClick={() => run({ type: "approve_adjustment", adjustment: a.id })}>Approve</Button>}
          {can("adjust") && <Button onClick={() => setReverting(true)}>Revert</Button>}
        </div>
      )}
      {reverting && (
        <Modal title={`Revert ${fmt(a.delta, { sign: true })} on ${a.line}`} onClose={() => setReverting(false)}>
          <p className="text-muted">The adjustment stays in the log; a revert is a new entry with your reason.</p>
          <ReasonForm authority={false} submit="Revert adjustment" placeholder="Why revert this adjustment" onCancel={() => setReverting(false)}
            onSubmit={(reason) => cmd({ type: "revert_adjustment", adjustment: a.id, reason }).then(() => setReverting(false))} />
        </Modal>
      )}
    </div>
  );
}

