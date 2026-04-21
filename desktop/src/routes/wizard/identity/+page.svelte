<script lang="ts">
  import { goto } from '$app/navigation';
  import { wizard } from '$lib/stores';
  import { t } from '$lib/i18n';

  let name = $state($wizard.identity.name);
  let role = $state($wizard.identity.role);
  let blurb = $state($wizard.identity.blurb);

  const canNext = $derived(name.trim().length >= 2 && role.trim().length >= 2);

  async function next() {
    wizard.update((w) => ({ ...w, identity: { name, role, blurb } }));
    await goto('/wizard/priorities/');
  }
</script>

<div class="space-y-8 animate-fade-in">
  <header class="space-y-2">
    <h1 class="text-2xl font-semibold">{$t('identity')}</h1>
    <p class="text-sm text-[rgb(var(--fg-muted))]">
      Claude uses this to tone the briefing. It stays on your machine.
    </p>
  </header>

  <div class="grid grid-cols-5 gap-6">
    <div class="col-span-3 space-y-5">
      <label class="block">
        <span class="mb-1.5 block text-xs font-semibold text-[rgb(var(--fg-muted))]"
          >{$t('identityName')}</span
        >
        <input class="input" bind:value={name} placeholder="Alice Chen" />
      </label>

      <label class="block">
        <span class="mb-1.5 block text-xs font-semibold text-[rgb(var(--fg-muted))]"
          >{$t('identityRole')}</span
        >
        <input class="input" bind:value={role} placeholder="Senior PM, Platform" />
      </label>

      <label class="block">
        <span class="mb-1.5 block text-xs font-semibold text-[rgb(var(--fg-muted))]"
          >{$t('identityBlurb')}</span
        >
        <textarea
          class="input min-h-[120px] resize-y"
          bind:value={blurb}
          placeholder="I own the billing platform roadmap. Prioritise messages from my director, legal, and paying customers."
        ></textarea>
      </label>
    </div>

    <!-- live preview card -->
    <aside class="col-span-2 hidden lg:block">
      <div class="card sticky top-0 p-4 text-xs space-y-2">
        <div class="text-[10px] font-semibold uppercase tracking-wider text-[rgb(var(--fg-muted))]">
          Preview
        </div>
        <div class="font-semibold">{name || 'Your name'}</div>
        <div class="text-[rgb(var(--fg-muted))]">{role || 'Your role'}</div>
        <div class="mt-2 text-[rgb(var(--fg-muted))] whitespace-pre-wrap">
          {blurb || 'A short description Claude can use to tone the briefing.'}
        </div>
      </div>
    </aside>
  </div>

  <div class="flex justify-end">
    <button class="btn-primary" disabled={!canNext} onclick={next}>{$t('continue')}</button>
  </div>
</div>
