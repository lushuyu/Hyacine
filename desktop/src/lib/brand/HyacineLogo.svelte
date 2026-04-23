<!--
  Hyacine wordmark: aurora-gradient square with a serif "H", optional HyacineAI text.
-->
<script lang="ts">
  interface Props {
    size?: number;
    showText?: boolean;
    text?: string;
    color?: string;
    class?: string;
  }
  let {
    size = 32,
    showText = true,
    text = 'HyacineAI',
    color = 'rgb(var(--fg))',
    class: klass = ''
  }: Props = $props();
</script>

<span
  class="inline-flex items-center {klass}"
  style:gap="{size * 0.3}px"
>
  <span
    class="relative inline-flex items-center justify-center shadow-pansy-sm"
    style:width="{size}px"
    style:height="{size}px"
    style:border-radius="{size * 0.28}px"
    style:background-image="linear-gradient(135deg, #F4B6C9 0%, #C9B8F0 50%, #A8D5F5 100%)"
    style:box-shadow="0 2px 8px rgba(201,184,240,0.55), inset 0 1px 0 rgba(255,255,255,0.5)"
  >
    <span
      class="font-serif font-bold text-white"
      style:font-size="{size * 0.55}px"
      style:letter-spacing="-0.02em"
      style:text-shadow="0 1px 2px rgba(0,0,0,.15)"
    >H</span>
  </span>
  {#if showText}
    <span
      class="font-sans font-medium"
      style:font-size="{size * 0.55}px"
      style:color
      style:letter-spacing="0.01em"
    >{text}</span>
  {/if}
</span>
