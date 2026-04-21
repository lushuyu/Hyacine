/**
 * Pure validators with rich error messages. Used by every wizard form so the
 * UI can surface issues as the user types, not only on submit.
 */

export function isEmail(v: string): boolean {
  // Deliberately simple: RFC5322 in full is too punishing for a setup screen.
  // We just gate against obvious typos. Graph will reject truly malformed ones.
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim());
}

export function isClaudeKey(v: string): { ok: boolean; reason?: string } {
  const t = v.trim();
  if (!t) return { ok: false, reason: 'empty' };
  if (!t.startsWith('sk-ant-')) return { ok: false, reason: 'expected prefix sk-ant-' };
  if (t.length < 40) return { ok: false, reason: 'too short' };
  if (/\s/.test(t)) return { ok: false, reason: 'contains whitespace' };
  return { ok: true };
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
