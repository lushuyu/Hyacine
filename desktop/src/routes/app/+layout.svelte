<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { ipc } from '$lib/ipc';
  import { LayoutDashboard, FileText, List, Settings, Play, Dot } from 'lucide-svelte';
  import { fade } from 'svelte/transition';

  let { children } = $props();

  type Status = 'ok' | 'warn' | 'err' | 'unknown';
  let status = $state<Status>('unknown');
  let running = $state(false);

  const tabs = [
    { path: '/app/dashboard/', label: 'Dashboard', icon: LayoutDashboard },
    { path: '/app/prompt/', label: 'Prompt Lab', icon: FileText },
    { path: '/app/rules/', label: 'Rules', icon: List },
    { path: '/app/settings/', label: 'Settings', icon: Settings }
  ];

  onMount(async () => {
    try {
      const h = await ipc.pipeline.history(1);
      const last = h.runs?.[0] as { status_ui?: string } | undefined;
      // `status_ui` is the sidecar's normalised bucket ('ok' | 'fail' |
      // 'pending' | 'running'). The raw DB value lives in `status`; we
      // don't use it for the badge.
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
    class="flex w-56 flex-col border-r border-[rgb(var(--border))] bg-[rgb(var(--bg-elev))] p-3"
  >
    <div class="mb-6 flex items-center gap-2 px-2 py-3">
      <svg width="24" height="24" viewBox="0 0 64 64">
        <defs>
          <linearGradient id="sg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#a78bfa" />
            <stop offset="1" stop-color="#6d28d9" />
          </linearGradient>
        </defs>
        <rect width="64" height="64" rx="14" fill="url(#sg)" />
        <path d="M18 44 V20 H26 V30 H38 V20 H46 V44 H38 V34 H26 V44 Z" fill="#fff" />
      </svg>
      <span class="text-sm font-semibold tracking-tight">Hyacine</span>
    </div>

    <nav class="flex-1 space-y-0.5">
      {#each tabs as tab (tab.path)}
        {@const Icon = tab.icon}
        {@const active = $page.url.pathname.startsWith(tab.path)}
        <button
          class="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-all hover:bg-[rgb(var(--border)/0.35)] {active
            ? 'bg-[rgb(var(--border)/0.5)] font-medium'
            : ''}"
          onclick={() => goto(tab.path)}
        >
          <Icon
            size="16"
            color={active ? 'rgb(139 92 246)' : 'rgb(var(--fg-muted))'}
          />
          {tab.label}
        </button>
      {/each}
    </nav>

    <div class="border-t border-[rgb(var(--border))] pt-3 space-y-2">
      <button class="btn-primary w-full" disabled={running} onclick={runNow}>
        <Play size="14" />
        {running ? 'Running…' : 'Run now'}
      </button>
      <div class="flex items-center gap-1.5 px-1 text-xs text-[rgb(var(--fg-muted))]">
        <Dot size="18" class={statusColor} strokeWidth="6" />
        {status === 'ok'
          ? 'Last run succeeded'
          : status === 'err'
            ? 'Last run failed'
            : status === 'warn'
              ? 'Warnings'
              : 'No runs yet'}
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
