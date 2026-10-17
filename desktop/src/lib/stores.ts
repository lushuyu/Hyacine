import { writable } from 'svelte/store';
import { ipc, type WizardConfig } from '$lib/ipc';

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
  /** True once the fields above were seeded from config.read, so an empty
   *  `priorities` is the saved (or the user's) list, not a default. */
  seeded: boolean;
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
  schedule: { run_time: '08:00', startup: true, tray: true },
  seeded: false
};

export const wizard = writable<WizardState>(initial);

/**
 * Seed the wizard from the saved config.yaml. The preview and done steps
 * write these fields back, so re-entering the wizard (Settings → Rotate /
 * switch, Re-run wizard, or a restart mid-setup) must start from the
 * user's values, not the blank defaults above.
 */
export function seedWizard(c: WizardConfig) {
  wizard.update((w) => {
    if (!c.exists) return { ...w, seeded: true };
    const id = (c.identity ?? {}) as Partial<WizardState['identity']>;
    // config.read fills timezone / run_time / language with YamlConfig
    // defaults when they're missing. A saved recipient means the delivery
    // step was saved, so only then are they the user's own choices.
    const delivered = !!c.recipient_email;
    return {
      ...w,
      identity: { name: id.name ?? '', role: id.role ?? '', blurb: id.blurb ?? '' },
      priorities: Array.isArray(c.priorities) ? [...c.priorities] : [],
      delivery: delivered
        ? {
            email: c.recipient_email,
            timezone: c.timezone || w.delivery.timezone,
            language: c.language === 'zh-CN' ? 'zh-CN' : 'en'
          }
        : w.delivery,
      schedule: delivered && c.run_time ? { ...w.schedule, run_time: c.run_time } : w.schedule,
      seeded: true
    };
  });
}

/** `seedWizard` from a fresh config.read. Errors leave the store alone. */
export async function loadWizardFromConfig(): Promise<void> {
  try {
    seedWizard(await ipc.config.read());
  } catch {
    /* sidecar unreachable: the preview step still skips blank fields */
  }
}

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
