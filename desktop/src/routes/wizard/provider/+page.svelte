<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { ipc, type ApiFormat, type ProbeResult, type ProviderPreset } from '$lib/ipc';
  import { FALLBACK_PRESETS, formatError } from '$lib/provider-presets';
  import { pushToast, wizard } from '$lib/stores';
  import { t } from '$lib/i18n';
  import { isClaudeKey, maskKey } from '$lib/validators';
  import {
    AlertTriangle,
    Check,
    ExternalLink,
    Eye,
    EyeOff,
    Loader2,
    Lock,
    ShieldCheck,
    Sparkles
  } from 'lucide-svelte';

  // Catalogue loaded from the sidecar once on mount. We group by category
  // in the UI so the picker doesn't feel like a flat 50-item list.
  // Start with the bundled fallback so the picker is never empty, even
  // when the sidecar is unreachable (fresh install without Python on PATH,
  // sidecar crashed, slow first launch, etc). If providers.list succeeds
  // we replace this with the authoritative Python-side list.
  let presets = $state<ProviderPreset[]>(FALLBACK_PRESETS);
  let loadingPresets = $state(true);
  let sidecarWarning = $state<string>('');

  // The currently picked preset id, or 'custom' for a user-supplied endpoint.
  let selectedId = $state<string>('claude-code-oauth');
  // Custom-provider form state — only visible when selectedId === 'custom'.
  let customFormat = $state<ApiFormat>('openai_chat');
  let customBaseUrl = $state('');
  let customModel = $state('');

  // Key entry state.
  let key = $state('');
  let showKey = $state(false);
  let revealTimer: ReturnType<typeof setTimeout> | null = null;
  const validity = $derived(isClaudeKey(key));

  // Test state.
  let testing = $state(false);
  let testOk = $state<boolean | null>(null);
  let testDetail = $state('');
  let latencyMs = $state<number | null>(null);
  let existingForSlug = $state(false);

  const selectedPreset = $derived(presets.find((p) => p.id === selectedId));
  const effectiveFormat = $derived<ApiFormat>(
    selectedId === 'custom' ? customFormat : (selectedPreset?.api_format ?? 'anthropic_cli')
  );
  const requiresKey = $derived(effectiveFormat !== 'anthropic_cli');
  const requiresBaseUrl = $derived(selectedId === 'custom');

  // The keychain slug that will hold the secret for this selection.
  const slug = $derived(
    selectedId === 'custom' ? 'custom' : (selectedPreset?.secret_slug ?? selectedId)
  );

  onMount(async () => {
    try {
      const res = await ipc.providers.list();
      if (res.providers?.length) {
        presets = res.providers;
      }
    } catch (e) {
      // Sidecar unreachable — stick with FALLBACK_PRESETS. Show a warning
      // so the user knows live testing / custom config won't work until
      // the sidecar comes back, but don't block them from picking a
      // provider.
      sidecarWarning = formatError(e);
    }
    try {
      const cur = await ipc.providers.current();
      if (cur.current?.id) selectedId = cur.current.id;
    } catch {
      /* current() also fails when the sidecar is down; keep default */
    }
    loadingPresets = false;
    await refreshExistingKey();
  });

  async function refreshExistingKey() {
    if (!slug || slug === 'custom') {
      existingForSlug = false;
      return;
    }
    try {
      existingForSlug = await ipc.secrets.has(slug);
    } catch {
      existingForSlug = false;
    }
  }

  function toggleShow() {
    showKey = !showKey;
    if (revealTimer) clearTimeout(revealTimer);
    if (showKey) revealTimer = setTimeout(() => (showKey = false), 3000);
  }

  async function runTest() {
    if (requiresKey && !validity.ok && !existingForSlug) {
      pushToast('error', `Invalid key: ${validity.reason}`);
      return;
    }
    testing = true;
    testOk = null;
    testDetail = '';
    try {
      const res: ProbeResult = await ipc.providers.test({
        provider_id: selectedId === 'custom' ? '' : selectedId,
        base_url: requiresBaseUrl ? customBaseUrl : undefined,
        api_format: selectedId === 'custom' ? customFormat : undefined,
        api_key: key || undefined,
        model: selectedId === 'custom' ? customModel || undefined : undefined
      });
      testOk = res.status === 'ok';
      testDetail = res.detail;
      latencyMs = res.latency_ms;
      if (testOk) pushToast('success', `Provider reachable (${res.latency_ms}ms)`);
    } catch (e) {
      testOk = false;
      testDetail = formatError(e);
    } finally {
      testing = false;
    }
  }

  async function next() {
    const trimmed = key.trim();
    // Persist the key for every selection that has one — built-in slug
    // or the stable 'custom' slug. Skipping custom meant pipeline runs
    // could never find their credential.
    if (trimmed && validity.ok) {
      await ipc.secrets.set(slug, trimmed);
      key = '';
    }
    try {
      // For custom endpoints we leave llm_provider empty and write the
      // api_format + base_url directly — the Python resolve() helper
      // picks those up. The preset path clears them so stale overrides
      // can't shadow a fresh selection.
      const fields: Record<string, unknown> = {};
      if (selectedId === 'custom') {
        fields.llm_provider = '';
        fields.llm_api_format = customFormat;
        fields.llm_base_url = customBaseUrl;
        if (customModel) fields.llm_model = customModel;
      } else if (selectedPreset) {
        fields.llm_provider = selectedId;
        fields.llm_api_format = '';
        fields.llm_base_url = '';
        fields.llm_model = selectedPreset.default_model;
      }
      await ipc.config.write(fields);
    } catch (e) {
      pushToast('error', `Failed to save provider choice: ${formatError(e)}`);
      return;
    }

    wizard.update((w) => ({
      ...w,
      claude: {
        has_key: existingForSlug || (trimmed !== '' && validity.ok),
        tested: testOk === true,
        last_latency_ms: latencyMs
      }
    }));
    await goto('/wizard/graph/');
  }

  async function clearStoredKey() {
    if (slug === 'custom') return;
    await ipc.secrets.remove(slug);
    existingForSlug = false;
    testOk = null;
    testDetail = '';
    pushToast('info', 'Stored key cleared.');
  }

  const grouped = $derived(
    presets.reduce<Record<string, ProviderPreset[]>>((acc, p) => {
      (acc[p.category] ||= []).push(p);
      return acc;
    }, {})
  );
  const categoryLabels: Record<string, string> = {
    official: 'Official',
    relay: 'Anthropic-compatible relay',
    cn_official: 'China-region official',
    aggregator: 'Aggregator',
    local: 'Local / self-hosted',
    custom: 'Custom'
  };
  const categoryOrder = ['official', 'relay', 'cn_official', 'aggregator', 'local', 'custom'];

  function kindLabel(fmt: ApiFormat): string {
    if (fmt === 'anthropic_cli') return 'Claude CLI';
    if (fmt === 'anthropic_http') return 'Anthropic HTTP';
    return 'OpenAI-compatible';
  }
</script>

<div class="space-y-6 animate-fade-in">
  <header class="space-y-2">
    <h1 class="text-2xl font-semibold">{$t('providerTitle')}</h1>
    <p class="text-sm text-[rgb(var(--fg-muted))]">{$t('providerSubtitle')}</p>
  </header>

  {#if sidecarWarning}
    <!-- Sidecar is down — offline catalogue only. Keep the picker usable. -->
    <div class="card p-4 border-amber-500/40 bg-amber-50/30 dark:bg-amber-900/10 text-sm space-y-1">
      <div class="font-medium text-amber-700 dark:text-amber-400">
        Sidecar unreachable — showing the bundled provider list only.
      </div>
      <div class="text-xs text-[rgb(var(--fg-muted))]">
        Connectivity testing and custom endpoints need the Python sidecar
        to respond. You can still pick a preset; test once the app relaunches.
      </div>
      <div class="font-mono text-[11px] text-[rgb(var(--fg-muted))]">
        {sidecarWarning}
      </div>
    </div>
  {/if}

  <!-- Preset picker -->
  {#if loadingPresets}
    <div class="card flex items-center gap-2 p-4 text-sm text-[rgb(var(--fg-muted))]">
      <Loader2 size="14" class="animate-spin" /> Loading provider catalogue…
    </div>
  {:else}
    <section class="space-y-4">
      {#each categoryOrder as cat (cat)}
        {#if grouped[cat]?.length}
          <div class="space-y-2">
            <h2 class="text-[11px] font-semibold uppercase tracking-wider text-[rgb(var(--fg-muted))]">
              {categoryLabels[cat] ?? cat}
            </h2>
            <div class="grid grid-cols-2 gap-2">
              {#each grouped[cat] as p (p.id)}
                <button
                  class="card flex items-start gap-3 p-3 text-left transition-all"
                  class:ring-2={selectedId === p.id}
                  class:ring-brand-400={selectedId === p.id}
                  onclick={() => {
                    selectedId = p.id;
                    testOk = null;
                    refreshExistingKey();
                  }}
                >
                  <span
                    class="mt-1 inline-block h-3 w-3 rounded-full flex-shrink-0"
                    style:background-color={p.icon_color || '#94a3b8'}
                  ></span>
                  <span class="flex-1 space-y-0.5">
                    <span class="block text-sm font-medium">{p.name}</span>
                    <span class="block text-[11px] text-[rgb(var(--fg-muted))]">
                      {kindLabel(p.api_format)} · {p.default_model}
                    </span>
                  </span>
                </button>
              {/each}
            </div>
          </div>
        {/if}
      {/each}

      <!-- Custom entry -->
      <div class="space-y-2">
        <h2 class="text-[11px] font-semibold uppercase tracking-wider text-[rgb(var(--fg-muted))]">
          {categoryLabels.custom}
        </h2>
        <button
          class="card flex items-start gap-3 p-3 text-left transition-all w-full"
          class:ring-2={selectedId === 'custom'}
          class:ring-brand-400={selectedId === 'custom'}
          onclick={() => (selectedId = 'custom')}
        >
          <Sparkles size="14" class="mt-1 text-brand-500 flex-shrink-0" />
          <span class="flex-1">
            <span class="block text-sm font-medium">{$t('providerCustom')}</span>
            <span class="block text-[11px] text-[rgb(var(--fg-muted))]">
              Point at any OpenAI-compatible or Anthropic-compatible endpoint.
            </span>
          </span>
        </button>
      </div>
    </section>
  {/if}

  <!-- Privacy notice -->
  <div class="card flex gap-3 p-4 border-brand-400/40 bg-brand-50/30 dark:bg-brand-900/10">
    <ShieldCheck size="20" class="mt-0.5 flex-shrink-0 text-brand-500" />
    <div class="text-sm leading-relaxed">
      <strong class="block mb-1">Privacy</strong>
      <p class="text-[rgb(var(--fg-muted))]">{$t('providerPrivacy')}</p>
    </div>
  </div>

  <!-- Custom-endpoint form -->
  {#if selectedId === 'custom'}
    <div class="card space-y-3 p-4">
      <div class="grid grid-cols-2 gap-3">
        <label class="block">
          <span class="mb-1 block text-xs text-[rgb(var(--fg-muted))]">{$t('providerApiFormat')}</span>
          <select class="input" bind:value={customFormat}>
            <option value="anthropic_http">Anthropic HTTP (/v1/messages + x-api-key)</option>
            <option value="openai_chat">OpenAI-compatible (/v1/chat/completions)</option>
          </select>
        </label>
        <label class="block">
          <span class="mb-1 block text-xs text-[rgb(var(--fg-muted))]">{$t('providerModel')}</span>
          <input class="input" bind:value={customModel} placeholder="gpt-4o-mini" />
        </label>
      </div>
      <label class="block">
        <span class="mb-1 block text-xs text-[rgb(var(--fg-muted))]">{$t('providerBaseUrl')}</span>
        <input
          class="input"
          bind:value={customBaseUrl}
          placeholder={customFormat === 'anthropic_http'
            ? 'https://api.example.com         (no trailing /v1 — we append /v1/messages)'
            : 'https://api.example.com/v1      (we append /chat/completions)'}
        />
        <p class="mt-1 text-[11px] text-[rgb(var(--fg-muted))]">
          {customFormat === 'anthropic_http'
            ? 'Anthropic-compatible: set the host + base path, we append /v1/messages.'
            : 'OpenAI-compatible: include the /v1 segment, we append /chat/completions.'}
        </p>
      </label>
    </div>
  {/if}

  <!-- Key input (hidden for anthropic_cli — that flow uses `claude setup-token`) -->
  {#if requiresKey}
    {#if existingForSlug}
      <div class="card flex items-center gap-3 p-4">
        <Lock size="18" class="text-brand-500" />
        <div class="flex-1">
          <div class="text-sm font-medium">Key stored</div>
          <div class="text-xs text-[rgb(var(--fg-muted))]">Slug: {slug}</div>
        </div>
        <button class="btn-ghost !text-xs" onclick={clearStoredKey}>Replace</button>
      </div>
    {:else}
      <label class="block space-y-1.5">
        <span class="block text-xs font-semibold text-[rgb(var(--fg-muted))]">
          {$t('providerKeyLabel')}
        </span>
        <div class="relative">
          {#if showKey}
            <input
              class="input pr-20 font-mono text-xs"
              type="text"
              bind:value={key}
              autocomplete="off"
              spellcheck="false"
              placeholder="sk-…"
            />
          {:else}
            <input
              class="input pr-20 font-mono text-xs"
              type="password"
              bind:value={key}
              autocomplete="off"
              spellcheck="false"
              placeholder="sk-…"
            />
          {/if}
          <button
            type="button"
            class="absolute inset-y-0 right-2 my-auto h-7 px-2 rounded text-[rgb(var(--fg-muted))] hover:text-[rgb(var(--fg))]"
            onclick={toggleShow}
            aria-label={showKey ? 'Hide key' : 'Show key'}
          >
            {#if showKey}<EyeOff size="14" />{:else}<Eye size="14" />{/if}
          </button>
        </div>
        {#if key && !validity.ok}
          <p class="text-xs text-red-500">{validity.reason}</p>
        {:else if key && validity.ok}
          <p class="text-xs text-[rgb(var(--fg-muted))]">Looks good — {maskKey(key)}</p>
        {/if}
      </label>
    {/if}
  {:else}
    <div class="card flex items-start gap-3 p-4 text-sm">
      <Sparkles size="16" class="mt-0.5 text-brand-500" />
      <div class="space-y-1">
        <div class="font-medium">
          Uses the <code class="rounded bg-[rgb(var(--border)/0.4)] px-1.5 py-0.5 font-mono text-[11px]">claude</code> CLI
        </div>
        <p class="text-[rgb(var(--fg-muted))]">
          Run <code class="rounded bg-[rgb(var(--border)/0.4)] px-1.5 py-0.5 font-mono text-[11px]">claude setup-token</code>
          in your terminal to authenticate; Hyacine picks up the resulting token
          via the <code class="rounded bg-[rgb(var(--border)/0.4)] px-1.5 py-0.5 font-mono text-[11px]">claude -p</code>
          subprocess. No key is needed in this screen.
        </p>
        {#if selectedPreset?.docs_url}
          <a
            href={selectedPreset.docs_url}
            target="_blank"
            rel="noopener"
            class="inline-flex items-center gap-1 text-xs text-brand-500 hover:underline"
          >
            Docs <ExternalLink size="10" />
          </a>
        {/if}
      </div>
    </div>
  {/if}

  <!-- Test row -->
  <div class="flex items-center gap-3">
    <button
      class="btn-secondary"
      disabled={testing || (requiresKey && !existingForSlug && !validity.ok) || (requiresBaseUrl && !customBaseUrl)}
      onclick={runTest}
    >
      {#if testing}
        <Loader2 size="14" class="animate-spin" /> Testing…
      {:else}
        {$t('providerTest')}
      {/if}
    </button>
    {#if testOk === true}
      <span class="inline-flex items-center gap-1.5 text-sm text-green-600 dark:text-green-400">
        <Check size="14" />
        {$t('providerOk')}{latencyMs ? ` · ${latencyMs}ms` : ''}
      </span>
    {:else if testOk === false}
      <span class="inline-flex items-center gap-1.5 text-sm text-red-500">
        <AlertTriangle size="14" />
        {$t('providerBad')}
      </span>
    {/if}
  </div>
  {#if testOk === false && testDetail}
    <div class="card p-3 text-xs font-mono text-[rgb(var(--fg-muted))] whitespace-pre-wrap">
      {testDetail}
    </div>
  {/if}

  <div class="flex justify-end pt-2">
    <button
      class="btn-primary"
      disabled={requiresKey && !existingForSlug && !validity.ok}
      onclick={next}
    >
      {$t('continue')}
    </button>
  </div>
</div>
