<!--
  Pansy — the Hyacine accent flower. 5 rounded petals, gold core.
  Palette cycles pink → pinkDeep → lavender → lavenderDeep → sky, matching
  brand.jsx Pansy() from the design bundle.
-->
<script lang="ts">
  interface Props {
    size?: number;
    rotate?: number;
    opacity?: number;
    class?: string;
  }
  let {
    size = 40,
    rotate = 0,
    opacity = 1,
    class: klass = ''
  }: Props = $props();

  const petals: Array<{ deg: number; fill: string }> = [
    { deg: 0, fill: '#F4B6C9' },
    { deg: 72, fill: '#E89BB4' },
    { deg: 144, fill: '#C9B8F0' },
    { deg: 216, fill: '#A890E0' },
    { deg: 288, fill: '#A8D5F5' }
  ];
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 40 40"
  style:transform={rotate ? `rotate(${rotate}deg)` : undefined}
  style:opacity={opacity !== 1 ? String(opacity) : undefined}
  class={klass}
  aria-hidden="true"
>
  {#each petals as p (p.deg)}
    <ellipse
      cx="20"
      cy="11"
      rx="6.5"
      ry="9"
      transform="rotate({p.deg} 20 20)"
      fill={p.fill}
      opacity="0.85"
    />
  {/each}
  <circle cx="20" cy="20" r="2.8" fill="#E8C77A" />
</svg>
