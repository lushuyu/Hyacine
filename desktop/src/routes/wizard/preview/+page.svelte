<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { ipc, type PipelineProgress, type DryRunResult } from '$lib/ipc';
  import { wizard, pushToast } from '$lib/stores';
  import { t } from '$lib/i18n';
  import { Check, Loader2, Play } from 'lucide-svelte';
  import type { UnlistenFn } from '@tauri-apps/api/event';

  const stages = ['fetch', 'classify', 'llm', 'render', 'deliver'] as const;
  const labels: Record<(typeof stages)[number], string> = {
    fetch: 'Fetch inbox & calendar',
    classify: 'Classify messages',
    llm: 'Invoke Claude',
    render: 'Render HTML',
    deliver: 'Deliver (dry run)'
  };

  let status = $state<Record<string, 'pending' | 'running' | 'ok' | 'fail'>>({
    fetch: 'pending',
    classify: 'pending',
    llm: 'pending',
    render: 'pending',
    deliver: 'pending'
  });
  let running = $state(false);
  let done = $state(false);
  let result = $state<DryRunResult | null>(null);
  let unsub: UnlistenFn | null = null;

  async function saveConfigFirst() {
    const w = $wizard;
    await ipc.config.write({
      recipient_email: w.delivery.email,
      timezone: w.delivery.timezone,
      language: w.delivery.language,
      run_time: w.schedule.run_time,
      identity: w.identity,
      priorities: w.priorities
    });
  }

  async function runPreview() {
    running = true;
    done = false;
    status = { fetch: 'running', classify: 'pending', llm: 'pending', render: 'pending', deliver: 'pending' };
    try {
      await saveConfigFirst();
    } catch (e) {
      pushToast('error', 'Failed to save config: ' + String(e));
    }
    try {
      result = await ipc.pipeline.dryRun();
      done = !!result?.ok;

      // Only overwrite stages the `rpc:pipeline.progress` stream hasn't
      // already marked — the event-driven updates are authoritative. For
      // any stage still in 'pending'/'running' when the RPC returns, take
      // its terminal colour from `result.ok` so we never claim success on
      // a failed run.
      const terminal: 'ok' | 'fail' = result?.ok ? 'ok' : 'fail';
      for (const s of stages) {
        if (status[s] === 'pending' || status[s] === 'running') {
          status[s] = terminal;
        }
      }
      if (!result?.ok && result?.error) {
        pushToast('error', `Dry run failed: ${result.error}`);
      }
      wizard.update((w) => ({
        ...w,
        preview: result ? { html: result.html, subject: result.subject, summary: result.summary } : null
      }));
    } catch (e) {
      for (const s of stages) {
        if (status[s] === 'pending' || status[s] === 'running') status[s] = 'fail';
      }
      pushToast('error', String(e));
    } finally {
      running = false;
    }
  }

  onMount(async () => {
    unsub = await ipc.onEvent<PipelineProgress>('rpc:pipeline.progress', (e) => {
      status[e.stage] = e.status;
    });
    await runPreview();
  });

  onDestroy(() => unsub?.());

  async function next() {
    await goto('/wizard/done/');
  }
</script>

<div class="space-y-6 animate-fade-in">
  <header class="space-y-2">
    <h1 class="text-2xl font-semibold">{$t('previewTitle')}</h1>
    <p class="text-sm text-[rgb(var(--fg-muted))]">
      We'll run the full pipeline once without sending an email, so you can see what Claude produces.
    </p>
  </header>

  <!-- stages -->
  <div class="card p-4 space-y-2">
    {#each stages as s}
      <div class="flex items-center gap-3 text-sm">
        <div class="w-6 h-6 flex items-center justify-center">
          {#if status[s] === 'running'}
            <Loader2 size="14" class="animate-spin text-brand-500" />
          {:else if status[s] === 'ok'}
            <Check size="14" class="text-green-500" />
          {:else if status[s] === 'fail'}
            <span class="text-red-500">✕</span>
          {:else}
            <span class="h-1.5 w-1.5 rounded-full bg-[rgb(var(--border))]"></span>
          {/if}
        </div>
        <span class:text-[rgb(var(--fg-muted))]={status[s] === 'pending'}>{labels[s]}</span>
      </div>
    {/each}
  </div>

  <!-- rendered email -->
  {#if result?.html}
    <div class="space-y-2">
      <div class="flex items-center justify-between">
        <h2 class="text-xs font-semibold uppercase tracking-wider text-[rgb(var(--fg-muted))]">
          Rendered preview
        </h2>
        <div class="text-xs text-[rgb(var(--fg-muted))]">
          {result.duration_ms} ms
        </div>
      </div>
      <div class="card overflow-hidden">
        <iframe
          title="preview"
          srcdoc={result.html}
          sandbox=""
          class="h-[420px] w-full border-0 bg-white"
        ></iframe>
      </div>
      {#if result.subject}
        <p class="text-xs text-[rgb(var(--fg-muted))]">
          Subject: <span class="font-mono">{result.subject}</span>
        </p>
      {/if}
    </div>
  {/if}

  <div class="flex justify-between">
    <button class="btn-secondary" disabled={running} onclick={runPreview}>
      <Play size="14" />
      {running ? 'Running…' : 'Run again'}
    </button>
    <button class="btn-primary" disabled={!done} onclick={next}>{$t('continue')}</button>
  </div>
</div>
