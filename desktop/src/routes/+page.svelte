<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { ipc } from '$lib/ipc';

  let loading = $state(true);

  onMount(async () => {
    try {
      const cfg = await ipc.config.read();
      // Ask the sidecar which provider would be selected and whether its
      // slot has a stored secret. CLI providers don't need a key (the
      // `claude` binary handles auth itself), so the check collapses to
      // "provider selected, recipient set, Graph signed in".
      const cur = await ipc.providers.current();
      const slug = cur.current?.secret_slug ?? '';
      const needsKey = cur.current?.api_format !== 'anthropic_cli';
      const hasKey = slug ? await ipc.secrets.has(slug) : false;
      const me = await ipc.graph.me();
      const done =
        cfg.exists &&
        me.signed_in &&
        !!cfg.recipient_email &&
        (!needsKey || hasKey);
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
