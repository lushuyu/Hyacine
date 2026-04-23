<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { ipc } from '$lib/ipc';
  import { wizard } from '$lib/stores';
  import { t } from '$lib/i18n';
  import confetti from 'canvas-confetti';
  import { Check } from 'lucide-svelte';
  import Pansy from '$lib/brand/Pansy.svelte';

  let runTime = $state($wizard.schedule.run_time);
  let startup = $state($wizard.schedule.startup);
  let tray = $state($wizard.schedule.tray);

  onMount(() => {
    // Aurora-toned confetti — pink, lavender, sky, mint, gold.
    confetti({
      particleCount: 80,
      spread: 80,
      origin: { y: 0.4 },
      colors: ['#F4B6C9', '#C9B8F0', '#A890E0', '#A8D5F5', '#E8C77A', '#BDE3C8']
    });
  });

  async function launch() {
    wizard.update((w) => ({ ...w, schedule: { run_time: runTime, startup, tray } }));
    await ipc.config.write({ run_time: runTime });
    try {
      await ipc.cmd('ui_set_startup', { enabled: startup });
    } catch {
      /* non-fatal */
    }
    await goto('/app/dashboard/');
  }
</script>

<div class="animate-fade-in space-y-8 text-center">
  <div class="flex flex-col items-center gap-4">
    <div class="relative">
      <Pansy size={72} />
      <div
        class="absolute -bottom-1 -right-1 flex h-8 w-8 items-center justify-center rounded-full bg-white shadow-pansy-sm"
      >
        <Check size="16" class="text-[rgb(var(--accent))]" />
      </div>
    </div>
    <h1 class="serif text-3xl font-semibold text-[rgb(var(--fg))]">
      {$t('doneTitle')}
    </h1>
    <p class="text-sm text-[rgb(var(--fg-muted))]">{$t('doneSubtitle')}</p>
  </div>

  <div class="card space-y-5 p-5 text-left">
    <div class="flex items-center justify-between">
      <div>
        <div class="text-sm font-medium">{$t('doneRunTime')}</div>
        <div class="text-xs text-[rgb(var(--fg-muted))]">
          {$t('doneRunTimeHint')}, {$wizard.delivery.timezone}
        </div>
      </div>
      <input class="input w-32 text-center" type="time" bind:value={runTime} />
    </div>
    <label class="flex cursor-pointer items-center justify-between">
      <div>
        <div class="text-sm font-medium">{$t('doneLaunchAtLogin')}</div>
        <div class="text-xs text-[rgb(var(--fg-muted))]">{$t('doneLaunchAtLoginHint')}</div>
      </div>
      <input
        type="checkbox"
        bind:checked={startup}
        class="h-5 w-5 rounded border-[rgb(var(--border))] accent-brand-500"
      />
    </label>
    <label class="flex cursor-pointer items-center justify-between">
      <div>
        <div class="text-sm font-medium">{$t('doneTray')}</div>
        <div class="text-xs text-[rgb(var(--fg-muted))]">{$t('doneTrayHint')}</div>
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
