<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { ipc } from '$lib/ipc';
  import { pushToast } from '$lib/stores';
  import { setTheme, type Theme } from '$lib/stores';
  import { KeyRound, RefreshCw, Trash2, LogOut } from 'lucide-svelte';

  let cfg = $state<{
    recipient_email: string;
    timezone: string;
    llm_model: string;
    run_time: string;
    language: 'en' | 'zh-CN';
  } | null>(null);
  let hasKey = $state(false);
  let currentProvider = $state<{ id: string; name: string; secret_slug: string } | null>(null);
  let me = $state<{ signed_in: boolean; display_name?: string; user_principal_name?: string }>({
    signed_in: false
  });
  let theme = $state<Theme>(
    (typeof localStorage !== 'undefined'
      ? (localStorage.getItem('hyacine.theme') as Theme)
      : null) ?? 'auto'
  );

  async function reload() {
    const c = await ipc.config.read();
    cfg = {
      recipient_email: c.recipient_email,
      timezone: c.timezone,
      llm_model: c.llm_model,
      run_time: c.run_time,
      language: (c.language as 'en' | 'zh-CN') ?? 'en'
    };
    try {
      const cur = await ipc.providers.current();
      currentProvider = cur.current;
      hasKey = currentProvider
        ? await ipc.secrets.has(currentProvider.secret_slug)
        : false;
    } catch {
      currentProvider = null;
      hasKey = false;
    }
    me = await ipc.graph.me();
  }

  onMount(reload);

  async function saveCfg() {
    if (!cfg) return;
    await ipc.config.write(cfg);
    pushToast('success', 'Settings saved');
  }

  async function rotateProviderKey() {
    if (currentProvider) {
      await ipc.secrets.remove(currentProvider.secret_slug);
    }
    await goto('/wizard/provider/');
  }

  async function rerunWizard() {
    await goto('/wizard/welcome/');
  }

  async function signOutGraph() {
    // Clear the stored auth record by re-running wizard; we don't touch cache
    // here because azure-identity's token cache is managed by the sidecar.
    pushToast('info', 'Rerun the wizard to re-authenticate Microsoft Graph.');
  }

  function pickTheme(t: Theme) {
    theme = t;
    setTheme(t);
  }
</script>

{#if cfg}
  <div class="mx-auto max-w-3xl px-8 py-10 space-y-10">
    <header class="space-y-1">
      <h1 class="text-2xl font-semibold">Settings</h1>
      <p class="text-sm text-[rgb(var(--fg-muted))]">Edit your configuration any time.</p>
    </header>

    <!-- Appearance -->
    <section class="space-y-3">
      <h2 class="text-xs font-semibold uppercase tracking-wider text-[rgb(var(--fg-muted))]">
        Appearance
      </h2>
      <div class="flex gap-2">
        {#each ['light', 'dark', 'auto'] as t}
          <button
            class="chip"
            class:chip-active={theme === t}
            onclick={() => pickTheme(t as Theme)}
          >
            {t}
          </button>
        {/each}
      </div>
    </section>

    <!-- Delivery -->
    <section class="space-y-3">
      <h2 class="text-xs font-semibold uppercase tracking-wider text-[rgb(var(--fg-muted))]">
        Delivery
      </h2>
      <div class="card p-5 space-y-4">
        <label class="block">
          <span class="mb-1 block text-xs text-[rgb(var(--fg-muted))]">Recipient email</span>
          <input class="input" bind:value={cfg.recipient_email} />
        </label>
        <div class="grid grid-cols-3 gap-3">
          <label class="block">
            <span class="mb-1 block text-xs text-[rgb(var(--fg-muted))]">Timezone</span>
            <input class="input" bind:value={cfg.timezone} />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs text-[rgb(var(--fg-muted))]">Run time</span>
            <input class="input" type="time" bind:value={cfg.run_time} />
          </label>
          <label class="block">
            <span class="mb-1 block text-xs text-[rgb(var(--fg-muted))]">Language</span>
            <select class="input" bind:value={cfg.language}>
              <option value="en">English</option>
              <option value="zh-CN">中文</option>
            </select>
          </label>
        </div>
        <label class="block">
          <span class="mb-1 block text-xs text-[rgb(var(--fg-muted))]">Claude model</span>
          <select class="input" bind:value={cfg.llm_model}>
            <option value="sonnet">sonnet</option>
            <option value="opus">opus</option>
            <option value="haiku">haiku</option>
          </select>
        </label>
        <div class="flex justify-end">
          <button class="btn-primary" onclick={saveCfg}>Save</button>
        </div>
      </div>
    </section>

    <!-- Credentials -->
    <section class="space-y-3">
      <h2 class="text-xs font-semibold uppercase tracking-wider text-[rgb(var(--fg-muted))]">
        Credentials
      </h2>
      <div class="card p-5 space-y-4">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <KeyRound size="18" class="text-brand-500" />
            <div>
              <div class="text-sm font-medium">
                LLM provider{currentProvider ? ` · ${currentProvider.name}` : ''}
              </div>
              <div class="text-xs text-[rgb(var(--fg-muted))]">
                {hasKey
                  ? `Key stored for ${currentProvider?.secret_slug ?? '—'}`
                  : currentProvider
                    ? 'No key stored for this provider'
                    : 'No provider selected yet'}
              </div>
            </div>
          </div>
          <button class="btn-secondary" onclick={rotateProviderKey}>
            <RefreshCw size="14" /> {currentProvider ? 'Rotate / switch' : 'Configure'}
          </button>
        </div>
        <div class="h-px bg-[rgb(var(--border))]"></div>
        <div class="flex items-center justify-between">
          <div>
            <div class="text-sm font-medium">Microsoft account</div>
            <div class="text-xs text-[rgb(var(--fg-muted))]">
              {me.signed_in
                ? `${me.display_name ?? ''} <${me.user_principal_name ?? ''}>`
                : 'Not signed in'}
            </div>
          </div>
          <button class="btn-secondary" onclick={signOutGraph}>
            <LogOut size="14" /> Sign out
          </button>
        </div>
      </div>
    </section>

    <!-- Danger -->
    <section class="space-y-3">
      <h2 class="text-xs font-semibold uppercase tracking-wider text-red-500">Advanced</h2>
      <div class="card p-5 space-y-3 border-red-500/30">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-sm font-medium">Re-run setup wizard</div>
            <div class="text-xs text-[rgb(var(--fg-muted))]">
              Walks through every step again without deleting stored data.
            </div>
          </div>
          <button class="btn-secondary" onclick={rerunWizard}>Re-run</button>
        </div>
      </div>
    </section>
  </div>
{:else}
  <div class="mx-auto max-w-3xl px-8 py-10 text-sm text-[rgb(var(--fg-muted))]">Loading…</div>
{/if}
