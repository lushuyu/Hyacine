<script lang="ts">
  import { goto } from '$app/navigation';
  import { wizard, setTheme, type Theme } from '$lib/stores';
  import { lang, t } from '$lib/i18n';
  import { ipc } from '$lib/ipc';
  import Pansy from '$lib/brand/Pansy.svelte';
  import { Moon, Sun, MonitorSmartphone } from 'lucide-svelte';

  const langs: Array<{ value: 'en' | 'zh-CN'; label: string }> = [
    { value: 'en', label: 'English' },
    { value: 'zh-CN', label: '中文' }
  ];
  const themes: Array<{ value: Theme; label: string; icon: typeof Sun }> = [
    { value: 'light', label: 'Light', icon: Sun },
    { value: 'dark', label: 'Dark', icon: Moon },
    { value: 'auto', label: 'System', icon: MonitorSmartphone }
  ];

  async function next() {
    try {
      await ipc.config.bootstrap();
    } catch {
      /* sidecar not ready — ok; we'll retry on save */
    }
    await goto('/wizard/identity/');
  }

  function pickLang(v: 'en' | 'zh-CN') {
    lang.set(v);
    wizard.update((w) => ({ ...w, lang: v, delivery: { ...w.delivery, language: v } }));
  }
  function pickTheme(v: Theme) {
    wizard.update((w) => ({ ...w, theme: v }));
    setTheme(v);
  }
</script>

<div class="animate-fade-in space-y-9 text-center">
  <header class="flex flex-col items-center gap-4">
    <Pansy size={52} />
    <div class="space-y-2">
      <h1 class="serif text-4xl font-semibold text-[rgb(var(--fg))]">
        {$t('welcome')}
      </h1>
      <p class="text-sm text-[rgb(var(--fg-muted))]">{$t('tagline')}</p>
    </div>
  </header>

  <section class="space-y-3 text-left">
    <h2 class="text-xs font-semibold text-[rgb(var(--fg-muted))]">
      {$t('language')}
    </h2>
    <div class="grid grid-cols-2 gap-3">
      {#each langs as l (l.value)}
        {@const active = $wizard.lang === l.value}
        <button
          class="pick-card flex items-center justify-center text-[15px] font-medium"
          class:pick-card-selected={active}
          class:text-[rgb(var(--accent))]={active}
          onclick={() => pickLang(l.value)}
        >
          {l.label}
        </button>
      {/each}
    </div>
  </section>

  <section class="space-y-3 text-left">
    <h2 class="text-xs font-semibold text-[rgb(var(--fg-muted))]">
      {$t('theme')}
    </h2>
    <div class="grid grid-cols-3 gap-3">
      {#each themes as th (th.value)}
        {@const Icon = th.icon}
        {@const active = $wizard.theme === th.value}
        <button
          class="pick-card flex flex-col items-center gap-2 py-5 text-[13px] font-medium"
          class:pick-card-selected={active}
          class:text-[rgb(var(--accent))]={active}
          onclick={() => pickTheme(th.value)}
        >
          <Icon size="22" />
          {th.label}
        </button>
      {/each}
    </div>
  </section>

  <div class="flex justify-end pt-2">
    <button class="btn-primary px-6" onclick={next}>{$t('getStarted')}</button>
  </div>
</div>
