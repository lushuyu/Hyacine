<script lang="ts">
  import { goto } from '$app/navigation';
  import { wizard } from '$lib/stores';
  import { t } from '$lib/i18n';
  import { isEmail, isTz, systemTimezone } from '$lib/validators';
  import TimezoneCombobox from '$lib/components/TimezoneCombobox.svelte';

  let email = $state($wizard.delivery.email);
  let tz = $state($wizard.delivery.timezone || systemTimezone() || 'UTC');
  let outLang = $state<'en' | 'zh-CN'>($wizard.delivery.language);

  const emailOk = $derived(isEmail(email));
  const tzOk = $derived(isTz(tz));
  const canNext = $derived(emailOk && tzOk);

  async function next() {
    wizard.update((w) => ({
      ...w,
      delivery: { email, timezone: tz, language: outLang }
    }));
    await goto('/wizard/provider/');
  }
</script>

<div class="space-y-8 animate-fade-in">
  <header class="space-y-2">
    <h1 class="text-2xl font-semibold">{$t('delivery')}</h1>
    <p class="text-sm text-[rgb(var(--fg-muted))]">
      Hyacine sends the summary to this address every morning, via your own Outlook account.
    </p>
  </header>

  <div class="grid grid-cols-2 gap-5">
    <label class="col-span-2 block">
      <span class="mb-1.5 block text-xs font-semibold text-[rgb(var(--fg-muted))]"
        >{$t('deliveryEmail')}</span
      >
      <input
        class="input"
        type="email"
        bind:value={email}
        placeholder="alice@example.com"
      />
      {#if email && !emailOk}
        <p class="mt-1 text-xs text-red-500">{$t('deliveryEmailInvalid')}</p>
      {/if}
    </label>

    <label class="block">
      <span class="mb-1.5 block text-xs font-semibold text-[rgb(var(--fg-muted))]"
        >{$t('deliveryTz')}</span
      >
      <TimezoneCombobox bind:value={tz} placeholder={$t('deliveryTzPlaceholder')} />
      {#if tz && !tzOk}
        <p class="mt-1 text-xs text-red-500">{$t('deliveryTzInvalid')}</p>
      {/if}
    </label>

    <label class="block">
      <span class="mb-1.5 block text-xs font-semibold text-[rgb(var(--fg-muted))]"
        >{$t('deliveryLang')}</span
      >
      <select class="input" bind:value={outLang}>
        <option value="en">English</option>
        <option value="zh-CN">中文</option>
      </select>
    </label>
  </div>

  <!-- fake "email header" preview -->
  <div class="card p-4 font-mono text-xs text-[rgb(var(--fg-muted))] space-y-1">
    <div><span class="text-[rgb(var(--fg))]">{$t('deliveryPreviewTo')}:</span> {email || '—'}</div>
    <div><span class="text-[rgb(var(--fg))]">{$t('deliveryPreviewFrom')}:</span> {$t('deliveryPreviewFromVal')}</div>
    <div><span class="text-[rgb(var(--fg))]">{$t('deliveryPreviewSubject')}:</span> {$t('deliveryPreviewSubjectVal')} {tz}</div>
    <div>
      <span class="text-[rgb(var(--fg))]">{$t('deliveryPreviewLanguage')}:</span>
      {outLang === 'zh-CN' ? '中文' : 'English'}
    </div>
  </div>

  <div class="flex justify-end">
    <button class="btn-primary" disabled={!canNext} onclick={next}>{$t('continue')}</button>
  </div>
</div>
