<script lang="ts">
  import { onMount } from 'svelte';
  import { ipc } from '$lib/ipc';
  import { t } from '$lib/i18n';

  interface RunSummary {
    date?: string;
    /** Raw RunStatus value — e.g. success / failed / pending / running. */
    status?: string;
    /** Normalised bucket produced by the sidecar — 'ok' | 'fail' | 'pending' | 'running'. */
    status_ui?: string;
    [k: string]: unknown;
  }

  let runs = $state<RunSummary[]>([]);
  let selected = $state<RunSummary | null>(null);
  let loading = $state(true);

  onMount(async () => {
    try {
      const h = await ipc.pipeline.history(14);
      runs = (h.runs as RunSummary[]) ?? [];
    } finally {
      loading = false;
    }
  });

  function cellColor(r?: RunSummary) {
    if (!r) return 'bg-[rgb(var(--border)/0.3)]';
    const ui = r.status_ui ?? r.status ?? '';
    if (ui === 'ok') return 'bg-brand-400';
    if (ui === 'fail') return 'bg-red-400';
    return 'bg-amber-300';
  }

  // 14-cell strip, oldest first.
  const cells = $derived(
    Array.from({ length: 14 }, (_, i) => runs[13 - i] as RunSummary | undefined)
  );
</script>

<div class="mx-auto max-w-4xl px-8 py-10 space-y-8">
  <header class="space-y-1">
    <h1 class="text-2xl font-semibold">{$t('dashboardTitle')}</h1>
    <p class="text-sm text-[rgb(var(--fg-muted))]">{$t('dashboardSubtitle')}</p>
  </header>

  <section class="card p-5 space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-sm font-medium">{$t('dashboardActivityTitle')}</h2>
      <span class="text-xs text-[rgb(var(--fg-muted))]">{$t('dashboardActivityLegend')}</span>
    </div>
    <div class="flex gap-1.5">
      {#each cells as r, i (i)}
        <button
          class="h-10 flex-1 rounded-md transition-all hover:scale-[1.05] {cellColor(r)}"
          class:ring-2={selected === r}
          class:ring-brand-500={selected === r}
          onclick={() => (selected = r ?? null)}
          aria-label="run cell"
        ></button>
      {/each}
    </div>
  </section>

  {#if loading}
    <div class="text-sm text-[rgb(var(--fg-muted))]">{$t('dashboardLoadingHistory')}</div>
  {:else if selected}
    <section class="card p-5 space-y-3">
      <h2 class="text-sm font-medium">{$t('dashboardRunDetails')}</h2>
      <pre
        class="rounded bg-[rgb(var(--border)/0.3)] p-3 text-xs overflow-x-auto font-mono">{JSON.stringify(selected, null, 2)}</pre>
    </section>
  {:else if runs.length === 0}
    <div class="card p-8 text-center text-sm text-[rgb(var(--fg-muted))]">
      {$t('dashboardNoRuns')}
    </div>
  {/if}
</div>
