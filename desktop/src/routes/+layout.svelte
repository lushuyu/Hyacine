<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { ipc } from '$lib/ipc';
  import { sidecarError, toast, setTheme } from '$lib/stores';
  import { providerName } from '$lib/i18n';
  import { formatError } from '$lib/provider-presets';
  import { fly } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';

  let { children } = $props();

  // Map the provider's full preset name ("Claude (Claude Code OAuth)",
  // "DeepSeek (Anthropic-compatible)", …) to something short enough to drop
  // into UI strings that were originally hardcoded to "Claude". We strip
  // anything in parentheses and trim.
  function shortName(full: string): string {
    const trimmed = full.replace(/\s*\(.*?\)\s*/g, ' ').trim();
    return trimmed || 'LLM';
  }

  onMount(async () => {
    const pref = (localStorage.getItem('hyacine.theme') || 'auto') as
      | 'light'
      | 'dark'
      | 'auto';
    setTheme(pref);
    try {
      await ipc.startSidecar();
    } catch (e) {
      // Store the full error so downstream routes can show it instead of
      // letting every feature fall through with "not started" from the
      // pending map. Also keep the console.warn for devs tailing logs.
      sidecarError.set(formatError(e));
      console.warn('sidecar failed to start', e);
      return;
    }
    try {
      const cur = await ipc.providers.current();
      if (cur?.current?.name) {
        providerName.set(shortName(cur.current.name));
      }
    } catch (e) {
      console.warn('providers.current failed; falling back to default label', e);
    }
  });
</script>

<main class="h-full w-full">
  {@render children()}
</main>

<!-- Global toast stack -->
<div class="pointer-events-none fixed top-4 right-4 z-50 flex flex-col gap-2">
  {#each $toast as tst (tst.id)}
    <div
      in:fly={{ x: 24, duration: 220, easing: cubicOut }}
      out:fly={{ x: 24, duration: 200 }}
      class="pointer-events-auto card px-4 py-3 text-sm shadow-md max-w-sm"
      class:border-red-500={tst.kind === 'error'}
      class:border-green-500={tst.kind === 'success'}
    >
      {tst.msg}
    </div>
  {/each}
</div>
