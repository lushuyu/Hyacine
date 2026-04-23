<!-- 8-point gold sparkle — matches brand.jsx Sparkle() -->
<script lang="ts">
  interface Props {
    size?: number;
    color?: string;
    class?: string;
  }
  let { size = 12, color = '#E8C77A', class: klass = '' }: Props = $props();
</script>

<svg width={size} height={size} viewBox="0 0 12 12" class={klass} aria-hidden="true">
  <path d="M6 0 L7 5 L12 6 L7 7 L6 12 L5 7 L0 6 L5 5 Z" fill={color} />
</svg>
