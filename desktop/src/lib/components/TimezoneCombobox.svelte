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

  const offsetCache = new Map<string, number | null>();
  function zoneOffsetMinutes(zone: string): number | null {
    const cached = offsetCache.get(zone);
    if (cached !== undefined) return cached;
    let result: number | null = null;
    try {
      const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: zone,
        timeZoneName: 'shortOffset'
      }).formatToParts(new Date());
      const name = parts.find((p) => p.type === 'timeZoneName')?.value ?? '';
      if (name === 'GMT' || name === 'UTC') {
        result = 0;
      } else {
        const m = name.match(/([+-])(\d{1,2})(?::?(\d{2}))?/);
        if (m) {
          const sign = m[1] === '+' ? 1 : -1;
          result = sign * (parseInt(m[2], 10) * 60 + (m[3] ? parseInt(m[3], 10) : 0));
        }
      }
    } catch {
      result = null;
    }
    offsetCache.set(zone, result);
    return result;
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

  onMount(() => {
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

<div bind:this={hostEl} class="relative">
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
    aria-controls="tz-listbox"
  />
  {#if open}
    <ul
      bind:this={listEl}
      id="tz-listbox"
      role="listbox"
      class="absolute left-0 right-0 z-20 mt-1 max-h-64 overflow-y-auto rounded-xl border
             border-[rgb(var(--border))] bg-[rgb(var(--bg-elev))] py-1 text-sm shadow-lg"
    >
      {#each zones as z, i (z)}
        {@const hl = highlight(z, value)}
        {@const active = i === activeIdx}
        <li
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
