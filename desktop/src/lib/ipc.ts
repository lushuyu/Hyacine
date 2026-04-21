/**
 * Typed wrapper over `invoke()` — every backend entry point goes through here.
 * Secret values never travel back to the webview; only `has_*` booleans do.
 */
import { invoke } from '@tauri-apps/api/core';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';

export type ProbeKind = 'dns' | 'claude' | 'graph' | 'sendmail';

export interface ProbeResult {
  kind: ProbeKind;
  status: 'ok' | 'fail' | 'skipped' | 'running' | 'pending';
  latency_ms: number;
  detail: string;
}

export interface DeviceFlowEvent {
  state: 'awaiting_user' | 'approved' | 'failed' | 'cancelled';
  user_code?: string;
  verification_uri?: string;
  username?: string;
  detail?: string;
}

export interface PipelineProgress {
  stage: 'fetch' | 'classify' | 'llm' | 'render' | 'deliver';
  status: 'running' | 'ok' | 'fail';
}

export interface DryRunResult {
  ok: boolean;
  duration_ms: number;
  html: string;
  subject: string;
  summary: Record<string, number>;
  error?: string;
}

export interface WizardConfig {
  exists: boolean;
  recipient_email: string;
  timezone: string;
  llm_model: string;
  run_time: string;
  language: string;
  identity: { name: string; role: string; blurb: string };
  priorities: string[];
}

export const ipc = {
  // ── sidecar lifecycle ──────────────────────────────────────────────────
  async startSidecar(): Promise<void> {
    return invoke('sidecar_start');
  },
  async stopSidecar(): Promise<void> {
    return invoke('sidecar_stop');
  },
  async rpc<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    return invoke<T>('sidecar_rpc', { method, params });
  },
  async onEvent<T>(name: string, cb: (p: T) => void): Promise<UnlistenFn> {
    return listen<T>(name, (e) => cb(e.payload));
  },

  // ── secrets (keychain) ─────────────────────────────────────────────────
  secrets: {
    async set(service: string, value: string): Promise<void> {
      return invoke('secrets_set', { service, value });
    },
    async has(service: string): Promise<boolean> {
      return invoke<boolean>('secrets_has', { service });
    },
    async remove(service: string): Promise<void> {
      return invoke('secrets_remove', { service });
    },
    async testClaude(
      apiKey: string,
      model = 'claude-haiku-4-5'
    ): Promise<ProbeResult> {
      return invoke<ProbeResult>('secrets_test_claude', { apiKey, model });
    }
  },

  // ── wizard & settings ──────────────────────────────────────────────────
  config: {
    read: (): Promise<WizardConfig> => ipc.rpc('config.read'),
    write: (fields: Partial<Record<string, unknown>>): Promise<{ ok: boolean }> =>
      ipc.rpc('config.write', fields),
    bootstrap: (): Promise<{ ok: boolean; paths: Record<string, string> }> =>
      ipc.rpc('config.bootstrap'),
    readPrompt: (): Promise<{ exists: boolean; content: string }> =>
      ipc.rpc('config.read_prompt'),
    writePrompt: (content: string): Promise<{ ok: boolean }> =>
      ipc.rpc('config.write_prompt', { content }),
    readRules: (): Promise<{ exists: boolean; content: string }> =>
      ipc.rpc('config.read_rules'),
    writeRules: (content: string): Promise<{ ok: boolean }> =>
      ipc.rpc('config.write_rules', { content })
  },

  connectivity: {
    probe: (kind: ProbeKind, extra: Record<string, unknown> = {}) =>
      ipc.rpc<ProbeResult>('connectivity.probe', { kind, ...extra }),
    probeAll: (extra: Record<string, unknown> = {}) =>
      ipc.rpc<{ results: ProbeResult[]; ok: boolean }>('connectivity.probe_all', extra)
  },

  graph: {
    startDeviceFlow: () => ipc.rpc<{ started: boolean }>('graph.start_device_flow'),
    cancelDeviceFlow: () => ipc.rpc<{ ok: boolean }>('graph.cancel_device_flow'),
    me: () =>
      ipc.rpc<{
        signed_in: boolean;
        display_name?: string;
        user_principal_name?: string;
        mail?: string;
        error?: string;
      }>('graph.me')
  },

  pipeline: {
    dryRun: () => ipc.rpc<DryRunResult>('pipeline.dry_run'),
    run: () => ipc.rpc<{ ok: boolean; duration_ms: number; error?: string }>('pipeline.run'),
    history: (limit = 14) =>
      ipc.rpc<{ runs: Record<string, unknown>[] }>('pipeline.history', { limit })
  }
};
