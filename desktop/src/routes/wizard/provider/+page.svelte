<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { ipc, type ApiFormat, type ProbeResult, type ProviderPreset } from '$lib/ipc';
  import { FALLBACK_PRESETS, formatError } from '$lib/provider-presets';
  import { pushToast, sidecarError, wizard } from '$lib/stores';
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

  // Start with the bundled fallback so the picker is never empty, even
  // when the sidecar is unreachable (fresh install without Python on
  // PATH, sidecar crashed, slow first launch, etc). If providers.list
  // succeeds we replace this with the authoritative Python-side list.
  let presets = $state<ProviderPreset[]>(FALLBACK_PRESETS);
  let loadingPresets = $state(true);

  // The currently picked preset id, or 'custom' for a user-supplied endpoint.
  let selectedId = $state<string>('claude-code-oauth');
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

  // Local providers (Ollama, LM Studio, a localhost base URL) don't
  // need a key — the sidecar already drops the Authorization header
  // when the api_key is empty. Matches the backend's own rule.
  const isLocalProvider = $derived(
    selectedPreset?.category === 'local' ||
      (selectedId === 'custom' &&
        (customBaseUrl.startsWith('http://localhost') ||
          customBaseUrl.startsWith('http://127.0.0.1')))
  );
  const requiresKey = $derived(effectiveFormat !== 'anthropic_cli' && !isLocalProvider);
  const requiresBaseUrl = $derived(selectedId === 'custom');

  // Keychain slug for the secret. Preset providers use their own id;
  // custom endpoints share a single stable slug so the pipeline's
  // resolve() helper can always find the key.
  const slug = $derived(
    selectedId === 'custom' ? 'custom' : (selectedPreset?.secret_slug ?? selectedId)
  );

  onMount(async () => {
    try {
      const res = await ipc.providers.list();
      if (res.providers?.length) {
        presets = res.providers;
      }
    } catch {
      // Sidecar unreachable — stick with FALLBACK_PRESETS. The banner
      // that reads $sidecarError (set by the root layout) surfaces the
      // startup failure; swallowing the RPC error here avoids a
      // duplicate toast.
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

  // Reset key-stored state + sync with the keychain every time the
  // active slug changes, including when the user switches to Custom —
  // Custom uses the stable 'custom' slug, so it CAN have a stored key
  // from a previous session.
  async function refreshExistingKey() {
    if (!slug) {
      existingForSlug = false;
      return;
    }
    try {
      existingForSlug = await ipc.secrets.has(slug);
    } catch {
      existingForSlug = false;
    }
  }

  function onPickPreset(id: string) {
    selectedId = id;
    testOk = null;
    testDetail = '';
    latencyMs = null;
    refreshExistingKey();
  }

  function toggleShow() {
    showKey = !showKey;
    if (revealTimer) clearTimeout(revealTimer);
    if (showKey) revealTimer = setTimeout(() => (showKey = false), 3000);
  }

  async function runTest() {
    // When a key is already stored in the keychain we don't prompt for
    // one again — we pass api_key: undefined and let the sidecar fall
    // back to HYACINE_LLM_API_KEY, which the Rust parent populates from
    // the active provider's keychain slot at spawn time.
    const usingStored = existingForSlug && !key;
    if (!usingStored && requiresKey && !validity.ok) {
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
        api_key: usingStored ? undefined : key || undefined,
        model: selectedId === 'custom' ? customModel || undefined : undefined
      });
      testOk = res.status === 'ok';
      testDetail = res.detail;
      latencyMs = res.latency_ms;
      if (testOk) pushToast('success', `${$t('providerReachableToast')} (${res.latency_ms}ms)`);
    } catch (e) {
      testOk = false;
      testDetail = formatError(e);
    } finally {
      testing = false;
    }
  }

  async function next() {
    const trimmed = key.trim();
    if (trimmed && validity.ok) {
      await ipc.secrets.set(slug, trimmed);
      key = '';
    }
    try {
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
    await ipc.secrets.remove(slug);
    existingForSlug = false;
    testOk = null;
    testDetail = '';
    pushToast('info', $t('providerKeyClearedToast'));
  }

  const grouped = $derived(
    presets.reduce<Record<string, ProviderPreset[]>>((acc, p) => {
      (acc[p.category] ||= []).push(p);
      return acc;
    }, {})
  );
  const categoryOrder = ['official', 'relay', 'cn_official', 'aggregator', 'local', 'custom'];
  const categoryLabelKey: Record<string, Parameters<typeof $t>[0]> = {
    official: 'providerCategoryOfficial',
    relay: 'providerCategoryRelay',
    cn_official: 'providerCategoryCnOfficial',
    aggregator: 'providerCategoryAggregator',
    local: 'providerCategoryLocal',
    custom: 'providerCategoryCustom'
  };

  function kindLabelKey(fmt: ApiFormat): Parameters<typeof $t>[0] {
    if (fmt === 'anthropic_cli') return 'providerFmtAnthropicCli';
    if (fmt === 'anthropic_http') return 'providerFmtAnthropicHttp';
    return 'providerFmtOpenaiChat';
  }
</script>

<div class="animate-fade-in space-y-6">
  <header class="space-y-2">
    <h1 class="serif text-2xl font-semibold text-[rgb(var(--fg))]">{$t('providerTitle')}</h1>
    <p class="text-sm text-[rgb(var(--fg-muted))]">{$t('providerSubtitle')}</p>
  </header>

  {#if $sidecarError}
    <!-- Sidecar is down — offline catalogue only. Keep the picker usable. -->
    <div class="card p-4 border-amber-500/40 bg-amber-50/30 dark:bg-amber-900/10 text-sm space-y-2">
      <div class="font-medium text-amber-700 dark:text-amber-400">
        {$t('sidecarUnreachableTitle')}
      </div>
      <div class="text-xs text-[rgb(var(--fg-muted))]">
        {$t('sidecarUnreachableBody')}
      </div>
      <div class="font-mono text-[11px] text-[rgb(var(--fg-muted))] whitespace-pre-wrap break-all">
        {$sidecarError}
      </div>
    </div>
  {/if}

  {#if loadingPresets}
    <div class="card flex items-center gap-2 p-4 text-sm text-[rgb(var(--fg-muted))]">
      <Loader2 size="14" class="animate-spin" />
      {$t('providerLoadingCatalogue')}
    </div>
  {:else}
    <section class="space-y-4">
      {#each categoryOrder as cat (cat)}
        {#if grouped[cat]?.length}
          <div class="space-y-2">
            <h2 class="text-[11px] font-semibold uppercase tracking-wider text-[rgb(var(--fg-muted))]">
              {$t(categoryLabelKey[cat])}
            </h2>
            <div class="grid grid-cols-2 gap-2">
              {#each grouped[cat] as p (p.id)}
                <button
                  class="pick-card flex items-start gap-3 !p-3 text-left"
                  class:pick-card-selected={selectedId === p.id}
                  onclick={() => onPickPreset(p.id)}
                >
                  <span
                    class="mt-1 inline-block h-3 w-3 flex-shrink-0 rounded-full"
                    style:background-color={p.icon_color || '#94a3b8'}
                  ></span>
                  <span class="flex-1 space-y-0.5">
                    <span class="block text-sm font-medium">{p.name}</span>
                    <span class="block text-[11px] text-[rgb(var(--fg-muted))]">
                      {$t(kindLabelKey(p.api_format))} · {p.default_model}
                    </span>
                  </span>
                </button>
              {/each}
            </div>
          </div>
        {/if}
      {/each}

      <!-- Custom entry — mirrors preset button handler so test state resets. -->
      <div class="space-y-2">
        <h2 class="text-[11px] font-semibold uppercase tracking-wider text-[rgb(var(--fg-muted))]">
          {$t('providerCategoryCustom')}
        </h2>
        <button
          class="pick-card flex w-full items-start gap-3 !p-3 text-left"
          class:pick-card-selected={selectedId === 'custom'}
          onclick={() => onPickPreset('custom')}
        >
          <Sparkles size="14" class="mt-1 flex-shrink-0 text-[rgb(var(--accent))]" />
          <span class="flex-1">
            <span class="block text-sm font-medium">{$t('providerCustom')}</span>
            <span class="block text-[11px] text-[rgb(var(--fg-muted))]">
              {$t('providerCustomSubtitle')}
            </span>
          </span>
        </button>
      </div>
    </section>
  {/if}

  <!-- Privacy notice -->
  <div
    class="card flex gap-3 p-4"
    style:background-image="linear-gradient(135deg, rgba(201,184,240,0.18) 0%, rgba(232,155,180,0.10) 100%)"
    style:border-color="rgb(var(--accent-soft) / 0.55)"
  >
    <ShieldCheck size="20" class="mt-0.5 flex-shrink-0 text-[rgb(var(--accent))]" />
    <div class="text-sm leading-relaxed">
      <strong class="mb-1 block">{$t('providerPrivacyHeader')}</strong>
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
            ? $t('providerCustomBaseUrlAnthropicPH')
            : $t('providerCustomBaseUrlOpenaiPH')}
        />
        <p class="mt-1 text-[11px] text-[rgb(var(--fg-muted))]">
          {customFormat === 'anthropic_http'
            ? $t('providerAnthropicHelp')
            : $t('providerOpenaiHelp')}
        </p>
      </label>
    </div>
  {/if}

  <!-- Key input — only rendered when the provider actually needs auth -->
  {#if requiresKey}
    {#if existingForSlug}
      <div class="card flex items-center gap-3 p-4">
        <Lock size="18" class="text-[rgb(var(--accent))]" />
        <div class="flex-1">
          <div class="text-sm font-medium">{$t('providerKeyStored')}</div>
          <div class="text-xs text-[rgb(var(--fg-muted))]">{$t('providerKeyStoredNote')} {slug}</div>
        </div>
        <button class="btn-ghost !text-xs" onclick={clearStoredKey}>{$t('providerReplace')}</button>
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
          <p class="text-xs text-[rgb(var(--fg-muted))]">{$t('providerKeyLooksGood')} {maskKey(key)}</p>
        {/if}
      </label>
    {/if}
  {:else if effectiveFormat === 'anthropic_cli'}
    <div class="card flex items-start gap-3 p-4 text-sm">
      <Sparkles size="16" class="mt-0.5 text-[rgb(var(--accent))]" />
      <div class="space-y-1">
        <div class="font-medium">
          {$t('providerCliHeader')}
          <code class="rounded bg-[rgb(var(--border)/0.4)] px-1.5 py-0.5 font-mono text-[11px]">claude</code>
          CLI
        </div>
        <p class="text-[rgb(var(--fg-muted))]">{$t('providerCliBody')}</p>
        <p class="text-[rgb(var(--fg-muted))]">
          <code class="rounded bg-[rgb(var(--border)/0.4)] px-1.5 py-0.5 font-mono text-[11px]">{$t('providerCliSetupCmd')}</code>
        </p>
        {#if selectedPreset?.docs_url}
          <a
            href={selectedPreset.docs_url}
            target="_blank"
            rel="noopener"
            class="inline-flex items-center gap-1 text-xs text-[rgb(var(--accent))] hover:underline"
          >
            {$t('providerDocs')} <ExternalLink size="10" />
          </a>
        {/if}
      </div>
    </div>
  {/if}

  <!-- Test row -->
  <div class="flex items-center gap-3">
    <button
      class="btn-secondary"
      disabled={testing ||
        (requiresKey && !existingForSlug && !validity.ok) ||
        (requiresBaseUrl && !customBaseUrl)}
      onclick={runTest}
    >
      {#if testing}
        <Loader2 size="14" class="animate-spin" /> {$t('testing')}
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
