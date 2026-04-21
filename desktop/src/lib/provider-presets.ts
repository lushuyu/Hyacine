/**
 * Static mirror of hyacine.llm.providers.BUILTIN_PRESETS so the wizard has
 * something to show when the sidecar can't answer providers.list (fresh
 * install without Python on PATH, sidecar crashed, etc.). Keep this in
 * sync with src/hyacine/llm/providers.py.
 *
 * The canonical source for anything runtime — auth, routing, dispatch —
 * is the Python side; this copy is UI-only.
 */
import type { ProviderPreset } from './ipc';

export const FALLBACK_PRESETS: ProviderPreset[] = [
  {
    id: 'claude-code-oauth',
    name: 'Claude (Claude Code OAuth)',
    category: 'official',
    api_format: 'anthropic_cli',
    base_url: '',
    default_model: 'sonnet',
    secret_slug: 'claude-code-oauth',
    docs_url: 'https://docs.anthropic.com/en/docs/claude-code',
    icon_color: '#8b5cf6',
    notes: 'Uses the `claude` CLI under the hood.',
    models: ['sonnet', 'opus', 'haiku']
  },
  {
    id: 'anthropic-console',
    name: 'Anthropic Console',
    category: 'official',
    api_format: 'anthropic_http',
    base_url: 'https://api.anthropic.com',
    default_model: 'claude-sonnet-4-5',
    secret_slug: 'anthropic-console',
    docs_url: 'https://console.anthropic.com/settings/keys',
    icon_color: '#8b5cf6',
    notes: '',
    models: ['claude-sonnet-4-5', 'claude-haiku-4-5', 'claude-opus-4-5']
  },
  {
    id: 'deepseek-anthropic',
    name: 'DeepSeek (Anthropic-compatible)',
    category: 'relay',
    api_format: 'anthropic_http',
    base_url: 'https://api.deepseek.com/anthropic',
    default_model: 'deepseek-chat',
    secret_slug: 'deepseek-anthropic',
    docs_url: 'https://platform.deepseek.com/',
    icon_color: '#2563eb',
    notes: '',
    models: ['deepseek-chat', 'deepseek-reasoner']
  },
  {
    id: 'kimi-anthropic',
    name: 'Kimi (Moonshot) Anthropic',
    category: 'cn_official',
    api_format: 'anthropic_http',
    base_url: 'https://api.moonshot.cn/anthropic',
    default_model: 'kimi-k2-0905-preview',
    secret_slug: 'kimi-anthropic',
    docs_url: 'https://platform.moonshot.cn/',
    icon_color: '#0ea5e9',
    notes: '',
    models: []
  },
  {
    id: 'zhipu-glm-anthropic',
    name: 'Zhipu GLM (Anthropic-compatible)',
    category: 'cn_official',
    api_format: 'anthropic_http',
    base_url: 'https://open.bigmodel.cn/api/anthropic',
    default_model: 'glm-4.6',
    secret_slug: 'zhipu-glm-anthropic',
    docs_url: 'https://bigmodel.cn/',
    icon_color: '#10b981',
    notes: '',
    models: []
  },
  {
    id: 'openai',
    name: 'OpenAI',
    category: 'official',
    api_format: 'openai_chat',
    base_url: 'https://api.openai.com/v1',
    default_model: 'gpt-4.1-mini',
    secret_slug: 'openai',
    docs_url: 'https://platform.openai.com/api-keys',
    icon_color: '#10b981',
    notes: '',
    models: ['gpt-4.1', 'gpt-4.1-mini', 'gpt-4o', 'gpt-4o-mini']
  },
  {
    id: 'groq',
    name: 'Groq',
    category: 'official',
    api_format: 'openai_chat',
    base_url: 'https://api.groq.com/openai/v1',
    default_model: 'llama-3.3-70b-versatile',
    secret_slug: 'groq',
    docs_url: 'https://console.groq.com/keys',
    icon_color: '#f97316',
    notes: '',
    models: []
  },
  {
    id: 'ollama-local',
    name: 'Ollama (local)',
    category: 'local',
    api_format: 'openai_chat',
    base_url: 'http://localhost:11434/v1',
    default_model: 'llama3.3',
    secret_slug: 'ollama-local',
    docs_url: 'https://ollama.ai/',
    icon_color: '#64748b',
    notes: 'No API key required; run `ollama serve` first.',
    models: []
  }
];

/** Render any caught error (Tauri AppError, Error, etc.) as a user-readable string. */
export function formatError(e: unknown): string {
  if (!e) return 'unknown error';
  if (typeof e === 'string') return e;
  if (e instanceof Error) return e.message;
  if (typeof e === 'object') {
    const obj = e as Record<string, unknown>;
    if (typeof obj.message === 'string') {
      const kind = typeof obj.kind === 'string' ? `[${obj.kind}] ` : '';
      return `${kind}${obj.message}`;
    }
    try {
      return JSON.stringify(e);
    } catch {
      /* fall through */
    }
  }
  return String(e);
}
