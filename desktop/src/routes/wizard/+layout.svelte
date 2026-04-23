<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { fly } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import { ArrowLeft } from 'lucide-svelte';
  import Aurora from '$lib/brand/Aurora.svelte';
  import HyacineLogo from '$lib/brand/HyacineLogo.svelte';
  import Pansy from '$lib/brand/Pansy.svelte';

  let { children } = $props();

  const order = [
    '/wizard/splash/',
    '/wizard/welcome/',
    '/wizard/identity/',
    '/wizard/priorities/',
    '/wizard/delivery/',
    '/wizard/provider/',
    '/wizard/graph/',
    '/wizard/connectivity/',
    '/wizard/preview/',
    '/wizard/done/'
  ];

  const currentIndex = $derived(order.indexOf($page.url.pathname));
  const canBack = $derived(currentIndex > 1); // can't go back to splash
  const showHeader = $derived(currentIndex > 0);

  const progressPct = $derived(
    currentIndex <= 0
      ? 4
      : Math.min(100, ((currentIndex + 1) / order.length) * 100)
  );

  async function back() {
    if (canBack) await goto(order[currentIndex - 1]);
  }
</script>

<div class="relative flex h-full flex-col overflow-hidden">
  <Aurora />

  <!-- top bar: logo + progress + counter.
       Mirrors the HyacineAppUI chrome — a slim lavender rule, centred counter, back arrow. -->
  {#if showHeader}
    <div class="flex items-center justify-between px-6 pt-4 pb-3">
      <button
        class="btn-ghost !p-2 !rounded-lg"
        disabled={!canBack}
        onclick={back}
        aria-label="Back"
      >
        <ArrowLeft size="16" />
      </button>
      <HyacineLogo size={22} />
      {#if currentIndex > 0 && currentIndex < order.length - 1}
        <div
          class="min-w-[3.5rem] text-right font-mono text-[12px] tabular-nums text-[rgb(var(--fg-muted))]"
        >
          {currentIndex} / {order.length - 2}
        </div>
      {:else}
        <div class="w-14"></div>
      {/if}
    </div>
    <div class="mx-6 h-[3px] overflow-hidden rounded-full bg-[rgb(var(--accent-soft)/0.25)]">
      <div
        class="h-full rounded-full transition-[width] duration-500 ease-out"
        style:background-image="linear-gradient(90deg, #A890E0 0%, #E89BB4 100%)"
        style:width="{progressPct}%"
      ></div>
    </div>
  {/if}

  <!-- decorative pansies -->
  <Pansy
    size={44}
    rotate={-18}
    class="pointer-events-none absolute left-6 top-20 opacity-60"
  />
  <Pansy
    size={28}
    rotate={22}
    class="pointer-events-none absolute right-8 top-28 opacity-40"
  />

  <!-- page slot -->
  <div class="relative flex-1 overflow-hidden">
    {#key $page.url.pathname}
      <div
        class="absolute inset-0 overflow-y-auto"
        in:fly={{ y: 16, duration: 320, easing: cubicOut, delay: 60 }}
        out:fly={{ y: -12, duration: 180, easing: cubicOut }}
      >
        <div class="mx-auto flex min-h-full max-w-2xl items-center justify-center px-6 pb-16 pt-4">
          <div class="w-full">
            {@render children()}
          </div>
        </div>
      </div>
    {/key}
  </div>
</div>
