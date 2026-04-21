<script lang="ts">
  import { onMount } from 'svelte';
  import { ipc } from '$lib/ipc';
  import { pushToast } from '$lib/stores';
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
      pushToast('error', String(e));
    }
  });

  async function save() {
    saving = true;
    try {
      await ipc.config.writePrompt(content);
      original = content;
      pushToast('success', 'Prompt saved');
    } catch (e) {
      pushToast('error', String(e));
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
        r.ok ? `Dry run succeeded in ${r.duration_ms}ms` : `Failed: ${r.error}`
      );
    } finally {
      testing = false;
    }
  }
</script>

<div class="mx-auto max-w-4xl px-8 py-10 space-y-6">
  <header class="flex items-center justify-between">
    <div class="space-y-1">
      <h1 class="text-2xl font-semibold">Prompt Lab</h1>
      <p class="text-sm text-[rgb(var(--fg-muted))]">
        This is the system prompt Claude sees on every run.
      </p>
    </div>
    <div class="flex gap-2">
      <button class="btn-secondary" onclick={testPrompt} disabled={testing}>
        <Play size="14" />
        {testing ? 'Running…' : 'Dry-run'}
      </button>
      <button class="btn-primary" onclick={save} disabled={!dirty || saving}>
        <Save size="14" />
        {saving ? 'Saving…' : 'Save'}
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
