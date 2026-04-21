<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { ipc } from '$lib/ipc';
  import { wizard, pushToast } from '$lib/stores';
  import { t } from '$lib/i18n';
  import { isClaudeKey, maskKey } from '$lib/validators';
  import { Eye, EyeOff, Lock, Check, AlertTriangle, Loader2, ShieldCheck } from 'lucide-svelte';

  let key = $state('');
  let show = $state(false);
  let testing = $state(false);
  let ok = $state<boolean | null>(null);
  let detail = $state('');
  let latency = $state<number | null>(null);
  let hasExisting = $state(false);
  let revealTimer: ReturnType<typeof setTimeout> | null = null;

  const validity = $derived(isClaudeKey(key));

  onMount(async () => {
    try {
      hasExisting = await ipc.secrets.has('claude');
      if (hasExisting) {
        ok = true;
        detail = 'An existing key is stored in the system keychain.';
      }
    } catch {
      /* sidecar/keyring not ready — treat as no key */
    }
  });

  function toggleShow() {
    show = !show;
    if (revealTimer) clearTimeout(revealTimer);
    if (show) revealTimer = setTimeout(() => (show = false), 3000);
  }

  async function test() {
    if (!validity.ok) {
      pushToast('error', `Invalid key: ${validity.reason}`);
      return;
    }
    testing = true;
    ok = null;
    detail = '';
    try {
      const r = await ipc.secrets.testClaude(key);
      ok = r.status === 'ok';
      detail = r.detail;
      latency = r.latency_ms;
      if (ok) pushToast('success', `Claude reachable in ${r.latency_ms}ms`);
    } catch (e) {
      ok = false;
      detail = String(e);
    } finally {
      testing = false;
    }
  }

  async function next() {
    if (key && validity.ok) {
      await ipc.secrets.set('claude', key.trim());
      // Blank the in-memory copy; from here on we only ever hold `has_key`.
      key = '';
    }
    const has = await ipc.secrets.has('claude');
    wizard.update((w) => ({
      ...w,
      claude: { has_key: has, tested: ok === true, last_latency_ms: latency }
    }));
    if (!has) {
      pushToast('error', 'Please save a valid key before continuing.');
      return;
    }
    await goto('/wizard/graph/');
  }

  async function clearKey() {
    await ipc.secrets.remove('claude');
    hasExisting = false;
    ok = null;
    detail = '';
    latency = null;
    pushToast('info', 'Stored key cleared.');
  }
</script>

<div class="space-y-6 animate-fade-in">
  <header class="space-y-2">
    <h1 class="text-2xl font-semibold">{$t('claudeTitle')}</h1>
    <p class="text-sm text-[rgb(var(--fg-muted))]">
      You'll need an Anthropic API key (format <code class="rounded bg-[rgb(var(--border)/0.4)] px-1.5 py-0.5 text-[11px] font-mono">sk-ant-…</code>).
    </p>
  </header>

  <!-- Privacy notice -->
  <div class="card flex gap-3 p-4 border-brand-400/40 bg-brand-50/30 dark:bg-brand-900/10">
    <ShieldCheck size="20" class="mt-0.5 flex-shrink-0 text-brand-500" />
    <div class="text-sm leading-relaxed">
      <strong class="block mb-1">Privacy</strong>
      <p class="text-[rgb(var(--fg-muted))]">{$t('claudePrivacy')}</p>
    </div>
  </div>

  <!-- key input -->
  {#if hasExisting}
    <div class="card flex items-center gap-3 p-4">
      <Lock size="18" class="text-brand-500" />
      <div class="flex-1">
        <div class="text-sm font-medium">Key stored</div>
        <div class="text-xs text-[rgb(var(--fg-muted))]">{detail || 'In OS keychain.'}</div>
      </div>
      <button class="btn-ghost !text-xs" onclick={clearKey}>Replace</button>
    </div>
  {:else}
    <label class="block space-y-1.5">
      <span class="block text-xs font-semibold text-[rgb(var(--fg-muted))]">
        {$t('claudeKeyLabel')}
      </span>
      <div class="relative">
        {#if show}
          <input
            class="input pr-20 font-mono text-xs"
            type="text"
            bind:value={key}
            placeholder="sk-ant-api03-…"
            autocomplete="off"
            spellcheck="false"
          />
        {:else}
          <input
            class="input pr-20 font-mono text-xs"
            type="password"
            bind:value={key}
            placeholder="sk-ant-api03-…"
            autocomplete="off"
            spellcheck="false"
          />
        {/if}
        <button
          type="button"
          class="absolute inset-y-0 right-2 my-auto h-7 px-2 rounded text-[rgb(var(--fg-muted))] hover:text-[rgb(var(--fg))]"
          onclick={toggleShow}
          aria-label={show ? 'Hide key' : 'Show key'}
        >
          {#if show}<EyeOff size="14" />{:else}<Eye size="14" />{/if}
        </button>
      </div>
      {#if key && !validity.ok}
        <p class="text-xs text-red-500">{validity.reason}</p>
      {:else if key && validity.ok}
        <p class="text-xs text-[rgb(var(--fg-muted))]">Matches format — {maskKey(key)}</p>
      {/if}
    </label>

    <div class="flex items-center gap-3">
      <button
        class="btn-secondary"
        disabled={!validity.ok || testing}
        onclick={test}
      >
        {#if testing}
          <Loader2 size="14" class="animate-spin" /> Testing…
        {:else}
          {$t('claudeTest')}
        {/if}
      </button>
      {#if ok === true}
        <span class="inline-flex items-center gap-1.5 text-sm text-green-600 dark:text-green-400">
          <Check size="14" />
          {$t('claudeOk')}{latency ? ` · ${latency}ms` : ''}
        </span>
      {:else if ok === false}
        <span class="inline-flex items-center gap-1.5 text-sm text-red-500">
          <AlertTriangle size="14" />
          {$t('claudeBad')}
        </span>
      {/if}
    </div>
    {#if ok === false && detail}
      <div class="card p-3 text-xs font-mono text-[rgb(var(--fg-muted))] whitespace-pre-wrap">
        {detail}
      </div>
    {/if}
  {/if}

  <div class="flex justify-end pt-2">
    <button
      class="btn-primary"
      disabled={!hasExisting && (!validity.ok || ok !== true)}
      onclick={next}
    >
      {$t('continue')}
    </button>
  </div>
</div>
