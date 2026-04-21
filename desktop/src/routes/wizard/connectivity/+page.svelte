<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { ipc, type ProbeKind, type ProbeResult } from '$lib/ipc';
  import { wizard } from '$lib/stores';
  import { t } from '$lib/i18n';
  import { Check, X, Loader2, Minus, ChevronDown } from 'lucide-svelte';
  import { slide } from 'svelte/transition';

  const kinds: ProbeKind[] = ['dns', 'claude', 'graph', 'sendmail'];
  const labels: Record<ProbeKind, string> = {
    dns: 'DNS + outbound TCP',
    claude: 'Anthropic API',
    graph: 'Microsoft Graph',
    sendmail: 'SendMail (test to self)'
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

    // Run the independent probes concurrently so total wizard time tracks
    // the slowest single request, not the sum. Each promise clears its own
    // `running` flag on resolution so the UI can stream checkmarks in.
    const tasks: Promise<void>[] = [
      ipc.connectivity.probe('dns').then((r) => {
        results.dns = r;
        running.dns = false;
      }),
      ipc.cmd<ProbeResult>('rust_probe_claude').then((r) => {
        results.claude = r;
        running.claude = false;
      }),
      ipc.cmd<ProbeResult>('rust_probe_graph').then((r) => {
        results.graph = r;
        running.graph = false;
      })
    ];
    if (sendmailEnabled) {
      tasks.push(
        ipc
          .cmd<ProbeResult>('rust_probe_sendmail', { recipient: $wizard.delivery.email })
          .then((r) => {
            results.sendmail = r;
            running.sendmail = false;
          })
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
    <p class="text-sm text-[rgb(var(--fg-muted))]">
      Four checks in parallel — they should finish in a few seconds.
    </p>
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
            <div class="text-sm font-medium">{labels[k]}</div>
            <div class="text-xs text-[rgb(var(--fg-muted))]">
              {#if skipped}
                Not running (optional)
              {:else if isRunning}
                Running…
              {:else if r}
                {r.status === 'ok' ? 'OK' : r.status === 'fail' ? 'Failed' : 'Skipped'}
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
    Also send a one-time test email to myself
  </label>

  <div class="flex items-center justify-between">
    <button class="btn-ghost" onclick={runAll}>Re-run checks</button>
    <div class="flex gap-2">
      <button class="btn-ghost" onclick={next}>{$t('skip')}</button>
      <button class="btn-primary" disabled={!allDone || !allOk} onclick={next}>
        {$t('continue')}
      </button>
    </div>
  </div>
</div>
