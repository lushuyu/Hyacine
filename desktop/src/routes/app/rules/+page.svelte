<script lang="ts">
  import { onMount } from 'svelte';
  import { ipc } from '$lib/ipc';
  import { pushToast } from '$lib/stores';
  import { Save } from 'lucide-svelte';

  let content = $state('');
  let original = $state('');
  let saving = $state(false);
  const dirty = $derived(content !== original);

  onMount(async () => {
    try {
      const r = await ipc.config.readRules();
      content = r.content;
      original = r.content;
    } catch (e) {
      pushToast('error', String(e));
    }
  });

  async function save() {
    saving = true;
    try {
      await ipc.config.writeRules(content);
      original = content;
      pushToast('success', 'Rules saved');
    } catch (e) {
      pushToast('error', String(e));
    } finally {
      saving = false;
    }
  }
</script>

<div class="mx-auto max-w-4xl px-8 py-10 space-y-6">
  <header class="flex items-center justify-between">
    <div class="space-y-1">
      <h1 class="text-2xl font-semibold">Rules</h1>
      <p class="text-sm text-[rgb(var(--fg-muted))]">
        YAML classifier rules — promote/demote messages before they reach Claude.
      </p>
    </div>
    <button class="btn-primary" onclick={save} disabled={!dirty || saving}>
      <Save size="14" />
      {saving ? 'Saving…' : 'Save'}
    </button>
  </header>

  <textarea
    class="input min-h-[520px] font-mono text-[13px] leading-relaxed"
    bind:value={content}
    spellcheck="false"
    placeholder="# rules.yaml"
  ></textarea>
</div>
