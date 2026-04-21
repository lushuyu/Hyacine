<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { ipc, type DeviceFlowEvent } from '$lib/ipc';
  import { wizard, pushToast } from '$lib/stores';
  import { t } from '$lib/i18n';
  import { open } from '@tauri-apps/plugin-opener';
  import { Check, Copy, Loader2, ExternalLink, X } from 'lucide-svelte';
  import type { UnlistenFn } from '@tauri-apps/api/event';

  type State = 'idle' | 'awaiting_user' | 'approved' | 'failed' | 'cancelled';
  let state = $state<State>('idle');
  let code = $state('');
  let uri = $state('');
  let user = $state('');
  let detail = $state('');
  let copied = $state(false);
  let unsub: UnlistenFn | null = null;

  onMount(async () => {
    // Maybe we already have a token.
    const me = await ipc.graph.me();
    if (me.signed_in) {
      state = 'approved';
      user = me.display_name ?? me.mail ?? me.user_principal_name ?? '';
      wizard.update((w) => ({
        ...w,
        graph: { signed_in: true, display_name: user, upn: me.user_principal_name ?? '' }
      }));
      return;
    }

    unsub = await ipc.onEvent<DeviceFlowEvent>('rpc:graph.device_flow', (e) => {
      state = e.state;
      if (e.user_code) code = e.user_code;
      if (e.verification_uri) uri = e.verification_uri;
      if (e.username) user = e.username;
      if (e.detail) detail = e.detail;
      if (e.state === 'approved') {
        wizard.update((w) => ({
          ...w,
          graph: { signed_in: true, display_name: user, upn: user }
        }));
      }
    });

    try {
      await ipc.graph.startDeviceFlow();
    } catch (err) {
      state = 'failed';
      detail = String(err);
    }
  });

  onDestroy(() => {
    unsub?.();
    if (state === 'awaiting_user') ipc.graph.cancelDeviceFlow().catch(() => {});
  });

  async function copy() {
    await navigator.clipboard.writeText(code);
    copied = true;
    setTimeout(() => (copied = false), 1500);
  }

  async function openBrowser() {
    if (!uri) return;
    await open(uri);
  }

  async function cancel() {
    await ipc.graph.cancelDeviceFlow();
    await goto('/wizard/claude/');
  }

  async function next() {
    await goto('/wizard/connectivity/');
  }
</script>

<div class="space-y-8 animate-fade-in">
  <header class="space-y-2">
    <h1 class="text-2xl font-semibold">{$t('graphTitle')}</h1>
    <p class="text-sm text-[rgb(var(--fg-muted))]">
      Hyacine uses Microsoft Graph device-code sign-in — no password leaves your machine.
    </p>
  </header>

  {#if state === 'idle' || state === 'awaiting_user'}
    <div class="card p-6 space-y-5">
      <div class="flex flex-col items-center gap-3">
        <div class="relative">
          <div
            class="absolute inset-0 rounded-full bg-brand-500/30 blur-xl animate-pulse-ring"
          ></div>
          <div
            class="relative flex h-14 w-14 items-center justify-center rounded-full
                   bg-brand-500 text-white shadow-lg"
          >
            <Loader2 size="22" class="animate-spin" />
          </div>
        </div>
        <p class="text-sm text-[rgb(var(--fg-muted))]">
          Enter this code on the Microsoft sign-in page:
        </p>
        <div class="flex items-center gap-2">
          <code
            class="rounded-lg bg-[rgb(var(--border)/0.35)] px-5 py-3 font-mono text-2xl tracking-[0.3em]"
          >
            {code || '————————'}
          </code>
          <button
            class="btn-ghost !p-2"
            disabled={!code}
            onclick={copy}
            aria-label="copy code"
          >
            {#if copied}<Check size="16" class="text-green-500" />{:else}<Copy size="16" />{/if}
          </button>
        </div>
      </div>
      <div class="flex justify-center gap-3 pt-2">
        <button class="btn-primary" disabled={!uri} onclick={openBrowser}>
          <ExternalLink size="14" />
          {$t('graphStart')}
        </button>
        <button class="btn-ghost" onclick={cancel}>
          <X size="14" />
          {$t('graphCancel')}
        </button>
      </div>
    </div>
  {:else if state === 'approved'}
    <div class="card p-6 space-y-4">
      <div class="flex items-center gap-3">
        <div class="flex h-10 w-10 items-center justify-center rounded-full bg-green-500/20 text-green-500">
          <Check size="18" />
        </div>
        <div>
          <div class="text-sm font-semibold">Signed in</div>
          <div class="text-xs text-[rgb(var(--fg-muted))]">{user}</div>
        </div>
      </div>
    </div>
  {:else if state === 'failed' || state === 'cancelled'}
    <div class="card p-6 space-y-3 border-red-500/40">
      <div class="text-sm font-medium text-red-500">
        {state === 'cancelled' ? 'Cancelled' : 'Sign-in failed'}
      </div>
      {#if detail}
        <div class="text-xs font-mono text-[rgb(var(--fg-muted))]">{detail}</div>
      {/if}
      <button
        class="btn-secondary"
        onclick={async () => {
          state = 'idle';
          await ipc.graph.startDeviceFlow();
        }}>Try again</button
      >
    </div>
  {/if}

  <div class="flex justify-end">
    <button class="btn-primary" disabled={state !== 'approved'} onclick={next}>
      {$t('continue')}
    </button>
  </div>
</div>
