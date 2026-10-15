// API client, a small external store (read with useSyncExternalStore), hash routing and live updates.
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import type { Boot, Data, User } from "./types";

type Toast = { text: string; undo?: () => void; error?: boolean };

interface AppState {
  user: string;
  head: number; // last log sequence the client has seen; every data hook refetches when it moves
  boot: Boot | null;
  drawer: string[]; // the trace chain: refs pushed as you follow evidence
  toast: Toast | null;
  route: string;
}

const readUser = () => {
  try { return localStorage.getItem("wp.user") || "st-01"; } catch { return "st-01"; }
};

let state: AppState = { user: readUser(), head: 0, boot: null, drawer: [], toast: null, route: location.hash.slice(1) };
const listeners = new Set<() => void>();

function set(patch: Partial<AppState>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

export function useApp<T>(select: (s: AppState) => T): T {
  return useSyncExternalStore(subscribe, () => select(state));
}
export const getState = () => state;

/** The bootstrap payload; only call below the point where App has loaded it. */
export function useBoot(): Boot {
  const b = useApp((s) => s.boot);
  if (!b) throw new Error("bootstrap not loaded");
  return b;
}

// ---------------------------------------------------------------- server calls
export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

export async function api<T = Data>(path: string, opts: RequestInit = {}): Promise<T> {
  const r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-User": state.user, ...(opts.headers || {}) } });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(body.error || body.detail?.toString() || `Request failed (${r.status})`, r.status);
  return body as T;
}

const UNDOABLE = new Set(["adjustment.recorded", "verification.recorded", "finding.dispositioned", "document.dispositioned",
  "decision.recorded", "variance.explained", "household.corrected", "adjustment.approved", "signoff.recorded"]);
export const isUndoable = (kind: string) => UNDOABLE.has(kind);

type CommandResult = { head: number; events: { id: string; kind: string; batch?: string; text?: string }[] };

/** Send a command. Errors are shown as a toast and re-thrown so callers can keep a form open. */
export async function cmd(c: Data, quiet = false): Promise<CommandResult> {
  try {
    const r = await api<CommandResult>("/api/command", { method: "POST", body: JSON.stringify(c) });
    const first = r.events[0];
    const batch = r.events.find((e) => e.batch)?.batch;
    const canUndo = r.events.some((e) => UNDOABLE.has(e.kind));
    set({ head: r.head });
    if (!quiet) {
      const text = r.events.length > 2 ? `${first?.text ?? "Done"} (+${r.events.length - 1} more)` : (first?.text ?? "Done");
      toast(text, canUndo && first ? () => { void cmd(batch ? { type: "undo", batch } : { type: "undo", event: first.id }); } : undefined);
    }
    return r;
  } catch (e) {
    toast((e as Error).message, undefined, true);
    throw e;
  }
}

/** Fire-and-forget command from a click handler: failures are already reported by toast. */
export const run = (c: Data, quiet = false) => { cmd(c, quiet).catch(() => undefined); };

export async function loadBoot() {
  const boot = await api<Boot>("/api/bootstrap");
  set({ boot, head: boot.head });
  return boot;
}

export function setUser(id: string) {
  try { localStorage.setItem("wp.user", id); } catch { /* storage unavailable */ }
  set({ user: id, drawer: [], boot: null });
  void loadBoot();
}

/** Refresh after something outside the command flow changed (upload, clock). */
export const bump = () => set({ head: state.head + 1 });

// ---------------------------------------------------------------- data hook
/** GET a path; refetches whenever the shared log head or the acting user changes (live collaboration). */
export function useApi<T = Data>(path: string | null): { data: T | null; error: string | null; reload: () => void } {
  const head = useApp((s) => s.head);
  const user = useApp((s) => s.user);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!path) { setData(null); return; }
    const ctl = new AbortController();
    api<T>(path, { signal: ctl.signal })
      .then((d) => { setData(d); setError(null); })
      .catch((e: Error) => { if (e.name !== "AbortError") setError(e.message); });
    return () => ctl.abort();
  }, [path, head, user, n]);
  const reload = useCallback(() => setN((x) => x + 1), []);
  return { data, error, reload };
}

// ---------------------------------------------------------------- routing and the trace drawer
export function go(route: string) { location.hash = route; }
window.addEventListener("hashchange", () => set({ route: location.hash.slice(1), drawer: [] }));

export function openRef(ref: string, replace = false) {
  if (replace) return set({ drawer: [ref] });
  const i = state.drawer.indexOf(ref);
  set({ drawer: i >= 0 ? state.drawer.slice(0, i + 1) : [...state.drawer, ref] });
}
export const closeDrawer = () => set({ drawer: [] });
export const backDrawer = (i: number) => set({ drawer: state.drawer.slice(0, i + 1) });

// ---------------------------------------------------------------- toast
let toastTimer: ReturnType<typeof setTimeout> | undefined;
export function toast(text: string, undo?: () => void, error = false) {
  clearTimeout(toastTimer);
  set({ toast: { text, undo, error } });
  toastTimer = setTimeout(() => set({ toast: null }), undo ? 9000 : 4500);
}
export const dismissToast = () => { clearTimeout(toastTimer); set({ toast: null }); };

// ---------------------------------------------------------------- live updates
export function startStream(): () => void {
  let es: EventSource | null = null;
  let retry: ReturnType<typeof setTimeout> | undefined;
  const open = () => {
    es = new EventSource("/api/stream");
    es.onmessage = (m) => {
      const h = JSON.parse(m.data).head as number;
      if (h !== state.head) set({ head: h });
    };
    es.onerror = () => { es?.close(); retry = setTimeout(open, 3000); };
  };
  open();
  const beat = setInterval(() => {
    const where = state.drawer[state.drawer.length - 1] || state.route || "open items";
    api("/api/presence", { method: "POST", body: JSON.stringify({ where }) }).catch(() => undefined);
  }, 10000);
  return () => { es?.close(); clearTimeout(retry); clearInterval(beat); };
}

// ---------------------------------------------------------------- permissions and people
export const can = (perm: string) => !!state.boot?.perms.includes(perm);
export const me = (): User => state.boot!.me;
export const userName = (id: string) => state.boot?.users.find((u) => u.id === id)?.name || (id === "system" ? "System" : id);

/** Link for things the browser opens directly (exports, attachments). The demo identifies the
 *  acting user with a header; a plain link cannot send one, so these carry it as a parameter. */
export const userLink = (path: string) => `${path}${path.includes("?") ? "&" : "?"}x_user=${encodeURIComponent(state.user)}`;
