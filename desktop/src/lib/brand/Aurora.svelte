<!--
  Fullbleed aurora backdrop with a slow drift. Sits behind route content.
  Drop <Aurora /> inside a `relative` container; it fills the parent.
-->
<script lang="ts">
  interface Props {
    drift?: boolean;
  }
  let { drift = true }: Props = $props();
</script>

<div
  class="aurora"
  class:animate-aurora-drift={drift}
  aria-hidden="true"
></div>
