import { writable } from 'svelte/store';

export type Theme = 'light' | 'dark' | 'auto';
export type Lang = 'en' | 'zh-CN';

export interface WizardState {
  step: number; // 0..9
  lang: Lang;
  theme: Theme;
  identity: { name: string; role: string; blurb: string };
  priorities: string[];
  delivery: { email: string; timezone: string; language: Lang };
  claude: { has_key: boolean; tested: boolean; last_latency_ms: number | null };
  graph: { signed_in: boolean; display_name: string; upn: string };
  connectivity: { ok: boolean; results: Record<string, unknown>[] };
  preview: { html: string; subject: string; summary: Record<string, number> } | null;
  schedule: { run_time: string; startup: boolean; tray: boolean };
}

const initial: WizardState = {
  step: 0,
  lang: 'en',
  theme: 'auto',
  identity: { name: '', role: '', blurb: '' },
  priorities: [],
  delivery: { email: '', timezone: '', language: 'en' },
  claude: { has_key: false, tested: false, last_latency_ms: null },
  graph: { signed_in: false, display_name: '', upn: '' },
  connectivity: { ok: false, results: [] },
  preview: null,
  schedule: { run_time: '08:00', startup: true, tray: true }
};

export const wizard = writable<WizardState>(initial);

export function setTheme(t: Theme) {
  try {
    localStorage.setItem('hyacine.theme', t);
  } catch {
    /* ignore — storage may be disabled */
  }
  const m = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const dark = t === 'dark' || (t === 'auto' && m);
  document.documentElement.classList.toggle('dark', dark);
}

export const toast = writable<{ id: number; kind: 'info' | 'error' | 'success'; msg: string }[]>(
  []
);

/**
 * Global sidecar error surface. The root layout populates this on
 * startup if `ipc.startSidecar()` throws (CI-built installer without a
 * Python runtime, `hyacine` package not installed, etc.). Wizard steps
 * and the main app read it to show a banner explaining why RPC calls
 * might be failing — otherwise users just see opaque "not started"
 * errors deep inside every feature that needs the sidecar.
 */
export const sidecarError = writable<string>('');

let tid = 0;
export function pushToast(kind: 'info' | 'error' | 'success', msg: string, ttl = 3500) {
  const id = ++tid;
  toast.update((list) => [...list, { id, kind, msg }]);
  setTimeout(() => {
    toast.update((list) => list.filter((t) => t.id !== id));
  }, ttl);
}
