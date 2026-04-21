<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { fly } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import { progress, wizard } from '$lib/stores';
  import { ArrowLeft } from 'lucide-svelte';

  let { children } = $props();

  const order = [
    '/wizard/splash/',
    '/wizard/welcome/',
    '/wizard/identity/',
    '/wizard/priorities/',
    '/wizard/delivery/',
    '/wizard/claude/',
    '/wizard/graph/',
    '/wizard/connectivity/',
    '/wizard/preview/',
    '/wizard/done/'
  ];

  const currentIndex = $derived(order.indexOf($page.url.pathname));
  const canBack = $derived(currentIndex > 1); // can't go back to splash
  async function back() {
    if (canBack) await goto(order[currentIndex - 1]);
  }
</script>

<div class="flex h-full flex-col bg-[rgb(var(--bg))]">
  <!-- progress bar -->
  <div class="h-1 w-full bg-[rgb(var(--border))]/40">
    <div
      class="h-full bg-[rgb(var(--accent))] transition-[width] duration-500 ease-out"
      style:width="{Math.min(100, Math.max(4, $progress * 100))}%"
    ></div>
  </div>

  <!-- top nav: back + step counter -->
  <div class="flex items-center justify-between px-6 py-4">
    <button
      class="btn-ghost !py-1.5 !px-2"
      disabled={!canBack}
      onclick={back}
      aria-label="Back"
    >
      <ArrowLeft size="16" />
    </button>
    {#if currentIndex > 0 && currentIndex < order.length - 1}
      <div class="text-xs font-medium text-[rgb(var(--fg-muted))]">
        {currentIndex} / {order.length - 2}
      </div>
    {:else}
      <div></div>
    {/if}
    <div class="w-10"></div>
  </div>

  <!-- page slot with animated transitions -->
  <div class="relative flex-1 overflow-hidden">
    {#key $page.url.pathname}
      <div
        class="absolute inset-0 overflow-y-auto"
        in:fly={{ y: 16, duration: 320, easing: cubicOut, delay: 60 }}
        out:fly={{ y: -12, duration: 180, easing: cubicOut }}
      >
        <div class="mx-auto flex min-h-full max-w-2xl items-center justify-center px-6 pb-16">
          <div class="w-full">
            {@render children()}
          </div>
        </div>
      </div>
    {/key}
  </div>
</div>
