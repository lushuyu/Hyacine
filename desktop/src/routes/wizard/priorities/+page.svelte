<script lang="ts">
  import { goto } from '$app/navigation';
  import { wizard } from '$lib/stores';
  import { t } from '$lib/i18n';
  import { X, Plus } from 'lucide-svelte';
  import { flip } from 'svelte/animate';
  import { scale } from 'svelte/transition';

  const suggested = [
    'CEO',
    'board',
    'billing',
    'legal',
    'security',
    'on-call',
    'investor',
    'key customer',
    'director'
  ];

  let tags = $state([...$wizard.priorities]);
  let draft = $state('');

  function toggle(tag: string) {
    tags = tags.includes(tag) ? tags.filter((x) => x !== tag) : [...tags, tag];
  }
  function remove(tag: string) {
    tags = tags.filter((x) => x !== tag);
  }
  function add() {
    const v = draft.trim();
    if (!v || tags.includes(v)) return;
    tags = [...tags, v];
    draft = '';
  }
  function keydown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault();
      add();
    }
  }

  async function next() {
    wizard.update((w) => ({ ...w, priorities: tags }));
    await goto('/wizard/delivery/');
  }
</script>

<div class="space-y-8 animate-fade-in">
  <header class="space-y-2">
    <h1 class="text-2xl font-semibold">{$t('priorities')}</h1>
    <p class="text-sm text-[rgb(var(--fg-muted))]">{$t('prioritiesHint')}</p>
  </header>

  <!-- selected -->
  <section class="card p-4 min-h-[88px]">
    <div class="flex flex-wrap gap-2">
      {#each tags as tag (tag)}
        <span
          animate:flip={{ duration: 240 }}
          in:scale={{ start: 0.8, duration: 180 }}
          out:scale={{ start: 0.8, duration: 140 }}
          class="chip chip-active gap-1.5"
        >
          {tag}
          <button class="opacity-70 hover:opacity-100" onclick={() => remove(tag)} aria-label="remove">
            <X size="12" />
          </button>
        </span>
      {/each}
      {#if tags.length === 0}
        <span class="text-sm text-[rgb(var(--fg-muted))]">
          {$t('prioritiesEmpty')}
        </span>
      {/if}
    </div>
  </section>

  <!-- add custom -->
  <div class="flex gap-2">
    <input
      class="input flex-1"
      bind:value={draft}
      onkeydown={keydown}
      placeholder={$t('prioritiesAddPlaceholder')}
    />
    <button class="btn-secondary" onclick={add} aria-label="add">
      <Plus size="16" />
    </button>
  </div>

  <!-- suggestions -->
  <section class="space-y-2">
    <h2 class="text-xs font-semibold uppercase tracking-wider text-[rgb(var(--fg-muted))]">
      {$t('prioritiesSuggested')}
    </h2>
    <div class="flex flex-wrap gap-2">
      {#each suggested as s (s)}
        <button
          class="chip"
          class:chip-active={tags.includes(s)}
          onclick={() => toggle(s)}
        >
          {s}
        </button>
      {/each}
    </div>
  </section>

  <div class="flex justify-end">
    <button class="btn-primary" onclick={next}>{$t('continue')}</button>
  </div>
</div>
