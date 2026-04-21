<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { ipc } from '$lib/ipc';
  import { wizard } from '$lib/stores';
  import { t } from '$lib/i18n';
  import confetti from 'canvas-confetti';
  import { Check } from 'lucide-svelte';

  let runTime = $state($wizard.schedule.run_time);
  let startup = $state($wizard.schedule.startup);
  let tray = $state($wizard.schedule.tray);

  onMount(() => {
    // Subtle confetti — a single burst.
    confetti({
      particleCount: 60,
      spread: 72,
      origin: { y: 0.4 },
      colors: ['#a78bfa', '#8b5cf6', '#c4b5fd', '#ede9fe']
    });
  });

  async function launch() {
    wizard.update((w) => ({ ...w, schedule: { run_time: runTime, startup, tray } }));
    await ipc.config.write({ run_time: runTime });
    try {
      await ipc.rpc('ui_set_startup', { enabled: startup });
    } catch {
      /* non-fatal */
    }
    await goto('/app/dashboard/');
  }
</script>

<div class="space-y-8 animate-fade-in text-center">
  <div class="flex flex-col items-center gap-3">
    <div
      class="flex h-16 w-16 items-center justify-center rounded-full bg-green-500/20 text-green-500"
    >
      <Check size="32" />
    </div>
    <h1 class="text-3xl font-semibold">{$t('doneTitle')}</h1>
    <p class="text-sm text-[rgb(var(--fg-muted))]">
      Hyacine will send you a briefing every weekday morning.
    </p>
  </div>

  <div class="card p-5 space-y-5 text-left">
    <div class="flex items-center justify-between">
      <div>
        <div class="text-sm font-medium">Daily run time</div>
        <div class="text-xs text-[rgb(var(--fg-muted))]">Local time, {$wizard.delivery.timezone}</div>
      </div>
      <input class="input w-32 text-center" type="time" bind:value={runTime} />
    </div>
    <label class="flex items-center justify-between cursor-pointer">
      <div>
        <div class="text-sm font-medium">Launch at login</div>
        <div class="text-xs text-[rgb(var(--fg-muted))]">Recommended so scheduling works</div>
      </div>
      <input
        type="checkbox"
        bind:checked={startup}
        class="h-5 w-5 rounded border-[rgb(var(--border))] accent-brand-500"
      />
    </label>
    <label class="flex items-center justify-between cursor-pointer">
      <div>
        <div class="text-sm font-medium">Show in system tray</div>
        <div class="text-xs text-[rgb(var(--fg-muted))]">Quick access to run now & logs</div>
      </div>
      <input
        type="checkbox"
        bind:checked={tray}
        class="h-5 w-5 rounded border-[rgb(var(--border))] accent-brand-500"
      />
    </label>
  </div>

  <button class="btn-primary w-full" onclick={launch}>{$t('launch')}</button>
</div>
