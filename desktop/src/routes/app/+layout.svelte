<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { ipc } from '$lib/ipc';
  import { t, type MsgKey } from '$lib/i18n';
  import { LayoutDashboard, FileText, List, Settings, Play, Dot } from 'lucide-svelte';
  import { fade } from 'svelte/transition';
  import HyacineLogo from '$lib/brand/HyacineLogo.svelte';

  let { children } = $props();

  type Status = 'ok' | 'warn' | 'err' | 'unknown';
  let status = $state<Status>('unknown');
  let running = $state(false);

  const tabs: { path: string; labelKey: MsgKey; icon: typeof LayoutDashboard }[] = [
    { path: '/app/dashboard/', labelKey: 'navDashboard', icon: LayoutDashboard },
    { path: '/app/prompt/', labelKey: 'navPromptLab', icon: FileText },
    { path: '/app/rules/', labelKey: 'navRules', icon: List },
    { path: '/app/settings/', labelKey: 'navSettings', icon: Settings }
  ];

  onMount(async () => {
    try {
      const h = await ipc.pipeline.history(1);
      const last = h.runs?.[0] as { status_ui?: string } | undefined;
      if (!last) {
        status = 'unknown';
      } else if (last.status_ui === 'ok') {
        status = 'ok';
      } else if (last.status_ui === 'fail') {
        status = 'err';
      } else {
        status = 'warn';
      }
    } catch {
      status = 'unknown';
    }
  });

  async function runNow() {
    running = true;
    try {
      await ipc.pipeline.run();
      status = 'ok';
    } catch {
      status = 'err';
    } finally {
      running = false;
    }
  }

  const statusColor = $derived(
    status === 'ok'
      ? 'text-green-500'
      : status === 'warn'
        ? 'text-amber-500'
        : status === 'err'
          ? 'text-red-500'
          : 'text-[rgb(var(--fg-muted))]'
  );
</script>

<div class="flex h-full bg-[rgb(var(--bg))]">
  <!-- Sidebar -->
  <aside
    class="flex w-56 flex-col border-r border-[rgb(var(--border))] bg-[rgb(var(--bg-chrome))] p-3"
  >
    <div class="mb-6 flex items-center gap-2 px-2 py-3">
      <HyacineLogo size={24} text="Hyacine" />
    </div>

    <nav class="flex-1 space-y-0.5">
      {#each tabs as tab (tab.path)}
        {@const Icon = tab.icon}
        {@const active = $page.url.pathname.startsWith(tab.path)}
        <button
          class="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm transition-all
                 hover:bg-[rgb(var(--accent-soft)/0.18)]
                 {active
            ? 'bg-[rgb(var(--accent-soft)/0.28)] font-medium text-[rgb(var(--fg))]'
            : 'text-[rgb(var(--fg-muted))]'}"
          onclick={() => goto(tab.path)}
        >
          <Icon size="16" />
          {$t(tab.labelKey)}
        </button>
      {/each}
    </nav>

    <div class="space-y-2 border-t border-[rgb(var(--border))] pt-3">
      <button class="btn-primary w-full" disabled={running} onclick={runNow}>
        <Play size="14" />
        {running ? $t('runningNow') : $t('runNow')}
      </button>
      <div class="flex items-center gap-1.5 px-1 text-xs text-[rgb(var(--fg-muted))]">
        <Dot size="18" class={statusColor} strokeWidth="6" />
        {status === 'ok'
          ? $t('lastRunOk')
          : status === 'err'
            ? $t('lastRunFail')
            : status === 'warn'
              ? $t('lastRunWarn')
              : $t('lastRunNone')}
      </div>
    </div>
  </aside>

  <!-- Main -->
  <section class="relative flex-1 overflow-hidden">
    {#key $page.url.pathname}
      <div in:fade={{ duration: 180 }} class="h-full overflow-y-auto">
        {@render children()}
      </div>
    {/key}
  </section>
</div>
