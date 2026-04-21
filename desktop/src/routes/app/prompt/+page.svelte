<script lang="ts">
  import { onMount } from 'svelte';
  import { ipc } from '$lib/ipc';
  import { formatError } from '$lib/provider-presets';
  import { pushToast } from '$lib/stores';
  import { t } from '$lib/i18n';
  import { Save, Play } from 'lucide-svelte';

  let content = $state('');
  let original = $state('');
  let saving = $state(false);
  let testing = $state(false);
  const dirty = $derived(content !== original);

  onMount(async () => {
    try {
      const r = await ipc.config.readPrompt();
      content = r.content;
      original = r.content;
    } catch (e) {
      pushToast('error', formatError(e));
    }
  });

  async function save() {
    saving = true;
    try {
      await ipc.config.writePrompt(content);
      original = content;
      pushToast('success', $t('promptSaved'));
    } catch (e) {
      pushToast('error', formatError(e));
    } finally {
      saving = false;
    }
  }

  async function testPrompt() {
    testing = true;
    try {
      // A dry run uses the on-disk prompt, so save first if dirty.
      if (dirty) await save();
      const r = await ipc.pipeline.dryRun();
      pushToast(
        r.ok ? 'success' : 'error',
        r.ok
          ? `${$t('promptDryRunSucceeded')} ${r.duration_ms}ms`
          : `${$t('providerBad')}: ${r.error ?? ''}`
      );
    } finally {
      testing = false;
    }
  }
</script>

<div class="mx-auto max-w-4xl px-8 py-10 space-y-6">
  <header class="flex items-center justify-between">
    <div class="space-y-1">
      <h1 class="text-2xl font-semibold">{$t('promptTitle')}</h1>
      <p class="text-sm text-[rgb(var(--fg-muted))]">{$t('promptSubtitle')}</p>
    </div>
    <div class="flex gap-2">
      <button class="btn-secondary" onclick={testPrompt} disabled={testing}>
        <Play size="14" />
        {testing ? $t('running') : $t('promptDryRun')}
      </button>
      <button class="btn-primary" onclick={save} disabled={!dirty || saving}>
        <Save size="14" />
        {saving ? $t('saving') : $t('save')}
      </button>
    </div>
  </header>

  <textarea
    class="input min-h-[520px] font-mono text-[13px] leading-relaxed"
    bind:value={content}
    spellcheck="false"
    placeholder="# Hyacine identity …"
  ></textarea>
</div>
