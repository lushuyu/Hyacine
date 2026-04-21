/**
 * Pure validators with rich error messages. Used by every wizard form so the
 * UI can surface issues as the user types, not only on submit.
 */

export function isEmail(v: string): boolean {
  // Deliberately simple: RFC5322 in full is too punishing for a setup screen.
  // We just gate against obvious typos. Graph will reject truly malformed ones.
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim());
}

/**
 * Accepts the three token shapes that can drive Hyacine:
 *   - `sk-ant-api…` — Console API key (x-api-key header)
 *   - `sk-ant-oat…` — Claude Code OAuth setup token (Authorization: Bearer)
 *   - anything else ≥ 20 chars without whitespace — bare OAuth/JWT bearer
 *
 * The last bucket is intentionally permissive: the existing
 * `hyacine.llm.claude_code` pipeline requires `CLAUDE_CODE_OAUTH_TOKEN`
 * which may not start with `sk-ant-` at all, depending on how the user
 * obtained it. We'd rather let the connectivity test catch a bad token
 * than block a valid one here. The 20-char floor rejects obvious
 * typos / stubs without asking about format.
 */
export function isClaudeKey(v: string): { ok: boolean; reason?: string } {
  const t = v.trim();
  if (!t) return { ok: false, reason: 'empty' };
  if (/\s/.test(t)) return { ok: false, reason: 'contains whitespace' };
  if (t.length < 20) return { ok: false, reason: 'too short (need ≥ 20 chars)' };
  return { ok: true };
}

/** Describe the token flavour for UI hints ("will be sent as x-api-key" etc). */
export function claudeKeyKind(v: string): 'console' | 'oauth' | 'bearer' {
  const t = v.trim();
  if (t.startsWith('sk-ant-api')) return 'console';
  if (t.startsWith('sk-ant-oat') || t.startsWith('sk-') && t.includes('-oat')) return 'oauth';
  return 'bearer';
}

export function maskKey(v: string): string {
  const t = v.trim();
  if (t.length <= 12) return '•'.repeat(t.length);
  return `${t.slice(0, 7)}…${t.slice(-4)}`;
}

export function redactKeys(s: string): string {
  return s.replace(/sk-ant-[A-Za-z0-9_\-]+/g, (m) => `${m.slice(0, 7)}[REDACTED]`);
}

export function isTz(v: string): boolean {
  try {
    Intl.DateTimeFormat(undefined, { timeZone: v });
    return true;
  } catch {
    return false;
  }
}

export function commonTimezones(): string[] {
  // A short curated list; the full IANA set is overkill for a picker.
  return [
    'UTC',
    'America/Los_Angeles',
    'America/Denver',
    'America/Chicago',
    'America/New_York',
    'America/Toronto',
    'America/Sao_Paulo',
    'Europe/London',
    'Europe/Berlin',
    'Europe/Paris',
    'Europe/Madrid',
    'Europe/Amsterdam',
    'Europe/Zurich',
    'Europe/Stockholm',
    'Africa/Johannesburg',
    'Asia/Dubai',
    'Asia/Kolkata',
    'Asia/Bangkok',
    'Asia/Singapore',
    'Asia/Hong_Kong',
    'Asia/Shanghai',
    'Asia/Tokyo',
    'Asia/Seoul',
    'Australia/Sydney',
    'Pacific/Auckland'
  ];
}
