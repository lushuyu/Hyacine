<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { ipc } from '$lib/ipc';
  import { t } from '$lib/i18n';

  let loading = $state(true);

  onMount(async () => {
    try {
      const cfg = await ipc.config.read();
      // Ask the sidecar which provider would be selected and whether its
      // slot has a stored secret. CLI providers (`claude` binary handles
      // auth itself) and local providers (Ollama / LM Studio / localhost
      // base URL — no auth) are considered satisfied without a keychain
      // entry, matching the backend's actual requirements.
      const cur = await ipc.providers.current();
      const prov = cur.current;
      const slug = prov?.secret_slug ?? '';
      const isLocal =
        !!prov?.base_url &&
        (prov.base_url.startsWith('http://localhost') ||
          prov.base_url.startsWith('http://127.0.0.1'));
      const needsKey = prov?.api_format !== 'anthropic_cli' && !isLocal;
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
    <div class="text-sm text-[rgb(var(--fg-muted))]">{$t('loading')}</div>
  {/if}
</div>
