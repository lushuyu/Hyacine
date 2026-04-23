<script module lang="ts">
  /**
   * Per-module state shared across every `<TimezoneCombobox>` instance:
   *
   * - `uidCounter` mints a unique DOM id per mount so multiple pickers on
   *   the same page don't collide on `id="tz-listbox"` (wizard + settings
   *   rendered together, unit-test harnesses that mount multiple, etc.).
   * - `offsetCache` memoises the result of `Intl.DateTimeFormat(...).
   *   formatToParts()` per IANA zone. The computation is ~0.5-2 ms per
   *   zone; with ~420 zones the first offset query (`UTC+8` →
   *   scan-all) used to spike the main thread. Caching across instances
   *   means any later mount inherits the warmed map.
   * - `warmOffsetCache(zones)` runs once (idempotent) on first mount
   *   during `requestIdleCallback` if available, else a deferred
   *   `setTimeout(0)`. User doesn't pay the cost up-front; the typing
   *   path can then rely on an O(1) lookup per zone.
   */
  let uidCounter = 0;

  const offsetCache = new Map<string, number | null>();
  let offsetCacheWarmed = false;

  function computeOffsetForZone(zone: string): number | null {
    try {
      const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: zone,
        timeZoneName: 'shortOffset'
      }).formatToParts(new Date());
      const name = parts.find((p) => p.type === 'timeZoneName')?.value ?? '';
      if (name === 'GMT' || name === 'UTC') return 0;
      const m = name.match(/([+-])(\d{1,2})(?::?(\d{2}))?/);
      if (!m) return null;
      const sign = m[1] === '+' ? 1 : -1;
      return sign * (parseInt(m[2], 10) * 60 + (m[3] ? parseInt(m[3], 10) : 0));
    } catch {
      return null;
    }
  }

  export function zoneOffsetMinutes(zone: string): number | null {
    const cached = offsetCache.get(zone);
    if (cached !== undefined) return cached;
    const result = computeOffsetForZone(zone);
    offsetCache.set(zone, result);
    return result;
  }

  export function warmOffsetCache(zones: readonly string[]): void {
    if (offsetCacheWarmed) return;
    offsetCacheWarmed = true;
    const doWarm = () => {
      for (const z of zones) {
        if (!offsetCache.has(z)) offsetCache.set(z, computeOffsetForZone(z));
      }
    };
    // Defer so the first paint ships before we spend ~100-500 ms on 420
    // Intl calls. `requestIdleCallback` exists on Chromium (so in Tauri's
    // WebKit2GTK / WebView2); Safari/WebKit doesn't yet, hence the
    // fallback.
    const idle = (globalThis as typeof globalThis & {
      requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
    }).requestIdleCallback;
    if (typeof idle === 'function') {
      idle(doWarm, { timeout: 1500 });
    } else {
      setTimeout(doWarm, 0);
    }
  }
</script>

<script lang="ts">
  /**
   * Non-filtering timezone picker. HTML <datalist> hides unmatched entries —
   * that trips users who type "UTC+8", "shanghai", "newyork" and see an
   * empty list. This component keeps every IANA zone visible at all times;
   * typing only picks the *best* match, scrolls it into view, and highlights
   * it. Click, Enter, or Arrow+Enter commits; plain text entry still works
   * for unusual zones since isTz() is the source of truth for validity.
   */
  import { onMount } from 'svelte';
  import { allTimezones } from '$lib/validators';

  let {
    value = $bindable(''),
    placeholder = '',
    id
  }: {
    value?: string;
    placeholder?: string;
    id?: string;
  } = $props();

  const zones = allTimezones();

  // Per-instance DOM ids. `uidCounter` lives at module scope, so every
  // combobox on the page gets a distinct listbox/option id — no ARIA
  // collisions when the wizard and the settings pane share a viewport.
  const uid = `tz-combo-${++uidCounter}`;
  const listboxId = `${uid}-listbox`;
  const optionId = (i: number): string => `${uid}-opt-${i}`;

  let hostEl: HTMLDivElement | undefined = $state();
  let inputEl: HTMLInputElement | undefined = $state();
  let listEl: HTMLUListElement | undefined = $state();
  let open = $state(false);
  // -1 means "follow the best fuzzy match"; ≥ 0 means the user pressed
  // ↑/↓ and wants that index locked until they type again.
  let navIdx = $state(-1);

  function normalize(s: string): string {
    return s.toLowerCase().replace(/[\s_\-/]/g, '');
  }

  /** "UTC+8", "GMT-5:30", "+08:00", "-5" → offset in minutes. */
  function parseOffsetQuery(q: string): number | null {
    const m = q.trim().match(/^(?:UTC|GMT)?\s*([+-])\s*(\d{1,2})(?:\s*:?\s*(\d{2}))?$/i);
    if (!m) return null;
    const sign = m[1] === '+' ? 1 : -1;
    const hours = parseInt(m[2], 10);
    const mins = m[3] ? parseInt(m[3], 10) : 0;
    if (hours > 14 || mins >= 60) return null;
    return sign * (hours * 60 + mins);
  }

  function score(query: string, zone: string): number {
    if (!query) return 0;
    const offset = parseOffsetQuery(query);
    if (offset !== null) {
      const zo = zoneOffsetMinutes(zone);
      return zo === offset ? 800 - Math.min(zone.length, 40) : 0;
    }
    const q = normalize(query);
    const z = normalize(zone);
    if (!q) return 0;
    if (z === q) return 1000;
    if (z.startsWith(q)) return 700 - z.length;
    const idx = z.indexOf(q);
    if (idx >= 0) return 400 - idx;
    // subsequence fallback: "laang" → "Los_Angeles"
    let zi = 0;
    for (const ch of q) {
      const hit = z.indexOf(ch, zi);
      if (hit < 0) return 0;
      zi = hit + 1;
    }
    return 100 - z.length * 0.1;
  }

  const bestIdx = $derived.by(() => {
    if (!value) return -1;
    let best = -1;
    let bestScore = 0;
    for (let i = 0; i < zones.length; i++) {
      const s = score(value, zones[i]);
      if (s > bestScore) {
        bestScore = s;
        best = i;
      }
    }
    return best;
  });

  const activeIdx = $derived(navIdx >= 0 ? navIdx : bestIdx);

  $effect(() => {
    if (!open) return;
    const i = activeIdx;
    if (i < 0 || !listEl) return;
    const li = listEl.children.item(i) as HTMLElement | null;
    li?.scrollIntoView({ block: 'nearest' });
  });

  function pick(i: number) {
    if (i < 0 || i >= zones.length) return;
    value = zones[i];
    open = false;
    navIdx = -1;
    inputEl?.focus();
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      if (open) {
        e.preventDefault();
        open = false;
      }
      return;
    }
    if (e.key === 'Enter') {
      if (open && activeIdx >= 0) {
        e.preventDefault();
        pick(activeIdx);
      }
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      open = true;
      const base = navIdx < 0 ? Math.max(activeIdx, -1) : navIdx;
      navIdx = Math.min(base + 1, zones.length - 1);
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      open = true;
      const base = navIdx < 0 ? Math.max(activeIdx, 0) : navIdx;
      navIdx = Math.max(base - 1, 0);
      return;
    }
  }

  function onDocumentDown(e: MouseEvent) {
    if (!hostEl) return;
    if (!hostEl.contains(e.target as Node)) open = false;
  }

  /** Close when focus leaves the component entirely (Tab, Shift-Tab, or
   *  clicking a focusable element elsewhere). `relatedTarget` is the
   *  element that will receive focus next; when it lives inside the host
   *  (picked option, input re-focus after pick) we keep the list open.
   *  Mouse clicks on options fire `onmousedown` with preventDefault, so
   *  focus stays on the input and this handler doesn't fight them. */
  function onFocusOut(e: FocusEvent) {
    const next = e.relatedTarget as Node | null;
    if (!next || !hostEl?.contains(next)) open = false;
  }

  onMount(() => {
    warmOffsetCache(zones);
    document.addEventListener('mousedown', onDocumentDown);
    return () => document.removeEventListener('mousedown', onDocumentDown);
  });

  function highlight(
    zone: string,
    query: string
  ): { pre: string; hit: string; post: string } | null {
    if (!query) return null;
    if (parseOffsetQuery(query) !== null) return null;
    const ql = query.trim().toLowerCase();
    if (!ql) return null;
    const i = zone.toLowerCase().indexOf(ql);
    if (i < 0) return null;
    return {
      pre: zone.slice(0, i),
      hit: zone.slice(i, i + ql.length),
      post: zone.slice(i + ql.length)
    };
  }

  function fmtOffset(zone: string): string {
    const m = zoneOffsetMinutes(zone);
    if (m === null) return '';
    if (m === 0) return 'UTC';
    const sign = m >= 0 ? '+' : '-';
    const a = Math.abs(m);
    const hh = Math.floor(a / 60);
    const mm = a % 60;
    return mm ? `UTC${sign}${hh}:${mm.toString().padStart(2, '0')}` : `UTC${sign}${hh}`;
  }
</script>

<div bind:this={hostEl} class="relative" onfocusout={onFocusOut}>
  <input
    {id}
    bind:this={inputEl}
    class="input"
    {placeholder}
    bind:value
    oninput={() => (navIdx = -1)}
    onfocus={() => (open = true)}
    onclick={() => (open = true)}
    onkeydown={onKeyDown}
    autocomplete="off"
    autocapitalize="off"
    autocorrect="off"
    spellcheck="false"
    role="combobox"
    aria-expanded={open}
    aria-autocomplete="list"
    aria-controls={listboxId}
    aria-activedescendant={open && activeIdx >= 0 ? optionId(activeIdx) : undefined}
  />
  {#if open}
    <ul
      bind:this={listEl}
      id={listboxId}
      role="listbox"
      class="absolute left-0 right-0 z-20 mt-1 max-h-64 overflow-y-auto rounded-xl border
             border-[rgb(var(--border))] bg-[rgb(var(--bg-elev))] py-1 text-sm shadow-lg"
    >
      {#each zones as z, i (z)}
        {@const hl = highlight(z, value)}
        {@const active = i === activeIdx}
        <li
          id={optionId(i)}
          role="option"
          aria-selected={active}
          onmousedown={(e) => {
            e.preventDefault();
            pick(i);
          }}
          class="flex cursor-pointer items-center justify-between gap-3 px-3 py-1.5"
          style:background={active ? 'rgb(var(--accent-soft) / 0.25)' : ''}
        >
          <span class="truncate">
            {#if hl}
              {hl.pre}<mark
                class="bg-transparent p-0 font-semibold text-[rgb(var(--accent))]">{hl.hit}</mark
              >{hl.post}
            {:else}
              {z}
            {/if}
          </span>
          <span class="shrink-0 text-xs text-[rgb(var(--fg-muted))]">{fmtOffset(z)}</span>
        </li>
      {/each}
    </ul>
  {/if}
</div>
