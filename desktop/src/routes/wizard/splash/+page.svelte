<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { fade, scale } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import { t } from '$lib/i18n';

  let mounted = $state(false);
  onMount(() => {
    mounted = true;
    const tid = setTimeout(() => goto('/wizard/welcome/'), 1400);
    return () => clearTimeout(tid);
  });
</script>

<div class="flex flex-col items-center justify-center gap-6 py-20">
  {#if mounted}
    <div
      in:scale={{ start: 0.6, duration: 600, easing: cubicOut }}
      class="relative"
    >
      <div
        class="absolute inset-0 rounded-3xl bg-brand-500/30 blur-3xl animate-pulse-ring"
      ></div>
      <svg
        width="96"
        height="96"
        viewBox="0 0 64 64"
        class="relative drop-shadow-[0_8px_32px_rgba(124,58,237,0.45)]"
      >
        <defs>
          <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#a78bfa" />
            <stop offset="1" stop-color="#6d28d9" />
          </linearGradient>
        </defs>
        <rect width="64" height="64" rx="14" fill="url(#lg)" />
        <path d="M18 44 V20 H26 V30 H38 V20 H46 V44 H38 V34 H26 V44 Z" fill="#fff" />
      </svg>
    </div>
    <div in:fade={{ duration: 500, delay: 400 }} class="text-center">
      <h1 class="text-3xl font-semibold tracking-tight">{$t('appName')}</h1>
      <p class="mt-2 text-sm text-[rgb(var(--fg-muted))]">{$t('tagline')}</p>
    </div>
  {/if}
</div>
