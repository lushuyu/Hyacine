<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { ipc } from '$lib/ipc';

  let loading = $state(true);

  onMount(async () => {
    try {
      const cfg = await ipc.config.read();
      const hasClaude = await ipc.secrets.has('claude');
      const me = await ipc.graph.me();
      const done = cfg.exists && hasClaude && me.signed_in && !!cfg.recipient_email;
      await goto(done ? '/app/dashboard/' : '/wizard/splash/', { replaceState: true });
    } catch {
      await goto('/wizard/splash/', { replaceState: true });
    } finally {
      loading = false;
    }
  });
</script>

<div class="flex h-full w-full items-center justify-center">
  {#if loading}
    <div class="text-sm text-[rgb(var(--fg-muted))]">Starting Hyacine…</div>
  {/if}
</div>
