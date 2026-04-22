<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { fade, scale } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import { t } from '$lib/i18n';
  import Pansy from '$lib/brand/Pansy.svelte';
  import Sparkle from '$lib/brand/Sparkle.svelte';

  let mounted = $state(false);
  onMount(() => {
    mounted = true;
    const tid = setTimeout(() => goto('/wizard/welcome/'), 1400);
    return () => clearTimeout(tid);
  });
</script>

<div class="relative flex flex-col items-center justify-center gap-7 py-24">
  {#if mounted}
    <div
      in:scale={{ start: 0.6, duration: 600, easing: cubicOut }}
      class="relative flex items-center justify-center"
    >
      <div
        class="absolute inset-0 rounded-full bg-hy-lavender/60 blur-3xl animate-pulse-ring"
      ></div>
      <div
        class="relative flex h-28 w-28 items-center justify-center rounded-[28px] shadow-aurora"
        style:background-image="linear-gradient(135deg, #F4B6C9 0%, #C9B8F0 50%, #A8D5F5 100%)"
      >
        <span
          class="serif text-[68px] font-bold text-white"
          style:text-shadow="0 2px 6px rgba(61,42,90,0.25)"
          style:letter-spacing="-0.02em">H</span>
      </div>
      <Sparkle size={18} class="absolute -top-2 -right-3" />
      <Sparkle size={12} class="absolute -bottom-1 -left-2" />
    </div>

    <div in:fade={{ duration: 500, delay: 400 }} class="space-y-2 text-center">
      <h1 class="serif text-3xl font-semibold tracking-tight text-[rgb(var(--fg))]">
        {$t('appName')}
      </h1>
      <p class="text-sm text-[rgb(var(--fg-muted))]">{$t('tagline')}</p>
    </div>

    <div in:fade={{ duration: 600, delay: 700 }} class="mt-2 flex items-center gap-2">
      <Pansy size={18} />
      <span
        class="font-mono text-[11px] uppercase tracking-[0.25em] text-[rgb(var(--fg-muted))]"
        >good morning</span
      >
      <Pansy size={18} rotate={180} />
    </div>
  {/if}
</div>
