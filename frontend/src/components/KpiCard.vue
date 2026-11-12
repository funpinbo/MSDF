<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], required: true },
  sub: { type: String, default: '' },
  tone: { type: String, default: '' },
})
</script>

<template>
  <div class="kpi card" :class="tone && `tone-${tone}`">
    <div class="label">{{ label }}</div>
    <div class="value">{{ value }}</div>
    <div v-if="sub" class="sub">{{ sub }}</div>
  </div>
</template>

<style scoped>
.kpi { padding: 12px 14px; min-width: 0; }
.label { font-size: 12px; color: var(--muted); font-weight: 550; }
.value { font-size: 24px; font-weight: 700; font-variant-numeric: tabular-nums; margin-top: 2px; }
.sub { font-size: 12px; color: var(--faint); margin-top: 2px; }
.tone-ok .value { color: var(--ok); }
.tone-fail .value { color: var(--fail); }
.tone-run .value { color: var(--run); }
.tone-cache .value { color: var(--cache); }
</style>
