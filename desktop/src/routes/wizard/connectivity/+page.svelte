<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { ipc, type ProbeKind, type ProbeResult } from '$lib/ipc';
  import { wizard } from '$lib/stores';
  import { t } from '$lib/i18n';
  import { Check, X, Loader2, Minus, ChevronDown } from 'lucide-svelte';
  import { slide } from 'svelte/transition';

  const kinds: ProbeKind[] = ['dns', 'claude', 'graph', 'sendmail'];
  const labelKey: Record<ProbeKind, Parameters<typeof $t>[0]> = {
    dns: 'connectivityDns',
    claude: 'connectivityClaude',
    graph: 'connectivityGraph',
    sendmail: 'connectivitySendmail'
  };

  let results = $state<Record<ProbeKind, ProbeResult | null>>({
    dns: null,
    claude: null,
    graph: null,
    sendmail: null
  });
  let running = $state<Record<ProbeKind, boolean>>({
    dns: true,
    claude: true,
    graph: true,
    sendmail: false
  });
  let expanded = $state<Record<ProbeKind, boolean>>({
    dns: false,
    claude: false,
    graph: false,
    sendmail: false
  });
  let sendmailEnabled = $state(false);

  onMount(async () => {
    await runAll();
  });

  async function runAll() {
    results = { dns: null, claude: null, graph: null, sendmail: null };
    for (const k of kinds) running[k] = k !== 'sendmail' || sendmailEnabled;

    // Run independent probes concurrently so total wizard time tracks the
    // slowest single request, not the sum. Every promise clears its own
    // `running` flag via finally() — otherwise a rejection (sidecar not
    // started, Rust command errored, etc.) would leave the UI spinning
    // forever because the .then hand-off never runs.
    const drive = <K extends ProbeKind>(k: K, p: Promise<ProbeResult>) =>
      p
        .then((r) => {
          results[k] = r;
        })
        .catch((e: unknown) => {
          results[k] = {
            kind: k,
            status: 'fail',
            latency_ms: 0,
            detail: String((e as Error)?.message ?? e)
          };
        })
        .finally(() => {
          running[k] = false;
        });

    const tasks: Promise<void>[] = [
      drive('dns', ipc.connectivity.probe('dns')),
      drive('claude', ipc.cmd<ProbeResult>('rust_probe_claude')),
      drive('graph', ipc.cmd<ProbeResult>('rust_probe_graph'))
    ];
    if (sendmailEnabled) {
      tasks.push(
        drive(
          'sendmail',
          ipc.cmd<ProbeResult>('rust_probe_sendmail', { recipient: $wizard.delivery.email })
        )
      );
    }
    await Promise.allSettled(tasks);
  }

  const allDone = $derived(
    kinds.every((k) => (k === 'sendmail' && !sendmailEnabled) || results[k] !== null)
  );
  const allOk = $derived(
    kinds.every(
      (k) =>
        (k === 'sendmail' && !sendmailEnabled) ||
        results[k]?.status === 'ok' ||
        results[k]?.status === 'skipped'
    )
  );

  async function next() {
    const cast = Object.values(results).filter(Boolean) as ProbeResult[];
    wizard.update((w) => ({
      ...w,
      connectivity: { ok: allOk, results: cast as unknown as Record<string, unknown>[] }
    }));
    await goto('/wizard/preview/');
  }
</script>

<div class="space-y-6 animate-fade-in">
  <header class="space-y-2">
    <h1 class="text-2xl font-semibold">{$t('connectivityTitle')}</h1>
    <p class="text-sm text-[rgb(var(--fg-muted))]">{$t('connectivitySubtitle')}</p>
  </header>

  <div class="space-y-2">
    {#each kinds as k (k)}
      {@const r = results[k]}
      {@const isRunning = running[k]}
      {@const skipped = k === 'sendmail' && !sendmailEnabled}
      <div class="card p-4">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 flex items-center justify-center rounded-full">
            {#if skipped}
              <Minus size="16" class="text-[rgb(var(--fg-muted))]" />
            {:else if isRunning}
              <Loader2 size="16" class="animate-spin text-brand-500" />
            {:else if r?.status === 'ok'}
              <div class="bg-green-500/20 rounded-full p-1.5">
                <Check size="14" class="text-green-500" />
              </div>
            {:else if r?.status === 'fail'}
              <div class="bg-red-500/20 rounded-full p-1.5">
                <X size="14" class="text-red-500" />
              </div>
            {:else}
              <Loader2 size="16" class="animate-spin text-brand-500" />
            {/if}
          </div>
          <div class="flex-1">
            <div class="text-sm font-medium">{$t(labelKey[k])}</div>
            <div class="text-xs text-[rgb(var(--fg-muted))]">
              {#if skipped}
                {$t('connectivityStatusNotRunning')}
              {:else if isRunning}
                {$t('connectivityStatusRunning')}
              {:else if r}
                {r.status === 'ok'
                  ? $t('connectivityStatusOk')
                  : r.status === 'fail'
                    ? $t('connectivityStatusFail')
                    : $t('connectivityStatusSkipped')}
                {#if r.latency_ms}· {r.latency_ms}ms{/if}
              {/if}
            </div>
          </div>
          {#if r && r.detail && !skipped}
            <button
              class="btn-ghost !p-1.5"
              onclick={() => (expanded[k] = !expanded[k])}
              aria-label="toggle"
            >
              <span
                class="inline-block transition-transform duration-200"
                style:transform={expanded[k] ? 'rotate(180deg)' : ''}
              >
                <ChevronDown size="16" />
              </span>
            </button>
          {/if}
        </div>
        {#if expanded[k] && r}
          <div
            transition:slide={{ duration: 200 }}
            class="mt-3 rounded-md bg-[rgb(var(--border)/0.35)] px-3 py-2 font-mono text-xs text-[rgb(var(--fg-muted))] whitespace-pre-wrap"
          >
            {r.detail}
          </div>
        {/if}
      </div>
    {/each}
  </div>

  <label class="flex items-center gap-2 text-sm text-[rgb(var(--fg-muted))]">
    <input
      type="checkbox"
      bind:checked={sendmailEnabled}
      onchange={() => runAll()}
      class="h-4 w-4 rounded border-[rgb(var(--border))] accent-brand-500"
    />
    {$t('connectivityIncludeSendmail')}
  </label>

  <div class="flex items-center justify-between">
    <button class="btn-ghost" onclick={runAll}>{$t('connectivityRerun')}</button>
    <div class="flex gap-2">
      <button class="btn-ghost" onclick={next}>{$t('skip')}</button>
      <button class="btn-primary" disabled={!allDone || !allOk} onclick={next}>
        {$t('continue')}
      </button>
    </div>
  </div>
</div>
