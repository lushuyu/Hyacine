<script lang="ts">
  import { goto } from '$app/navigation';
  import { wizard, setTheme, type Theme } from '$lib/stores';
  import { lang, t } from '$lib/i18n';
  import { ipc } from '$lib/ipc';
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

<div class="space-y-10 animate-fade-in">
  <header class="space-y-2 text-center">
    <h1 class="text-3xl font-semibold tracking-tight">{$t('welcome')}</h1>
    <p class="text-sm text-[rgb(var(--fg-muted))]">{$t('tagline')}</p>
  </header>

  <section class="space-y-3">
    <h2 class="text-xs font-semibold uppercase tracking-wider text-[rgb(var(--fg-muted))]">
      {$t('language')}
    </h2>
    <div class="grid grid-cols-2 gap-3">
      {#each langs as l (l.value)}
        <button
          class="card flex items-center justify-center px-4 py-4 text-sm font-medium transition-all"
          class:ring-2={$wizard.lang === l.value}
          class:ring-brand-400={$wizard.lang === l.value}
          class:shadow-md={$wizard.lang === l.value}
          onclick={() => pickLang(l.value)}
        >
          {l.label}
        </button>
      {/each}
    </div>
  </section>

  <section class="space-y-3">
    <h2 class="text-xs font-semibold uppercase tracking-wider text-[rgb(var(--fg-muted))]">
      {$t('theme')}
    </h2>
    <div class="grid grid-cols-3 gap-3">
      {#each themes as th (th.value)}
        {@const Icon = th.icon}
        <button
          class="card flex flex-col items-center gap-2 px-4 py-5 text-sm font-medium transition-all"
          class:ring-2={$wizard.theme === th.value}
          class:ring-brand-400={$wizard.theme === th.value}
          onclick={() => pickTheme(th.value)}
        >
          <Icon size="20" />
          {th.label}
        </button>
      {/each}
    </div>
  </section>

  <div class="flex justify-end pt-4">
    <button class="btn-primary" onclick={next}>{$t('getStarted')}</button>
  </div>
</div>
