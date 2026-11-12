<script setup>
defineProps({ data: { type: Object, required: true } })
</script>

<template>
  <div class="group" :style="{ '--svc': data.color, width: data.width + 'px', height: data.height + 'px' }">
    <div class="title">
      <span class="dot" />{{ data.name }}
      <span class="faint">· 인스턴스 {{ data.instances }}</span>
    </div>
  </div>
</template>

<style scoped>
.group {
  border: 1px dashed color-mix(in srgb, var(--svc) 55%, transparent);
  background: color-mix(in srgb, var(--svc) 6%, transparent);
  border-radius: 14px;
  pointer-events: none;
}
.title { padding: 6px 12px; font-size: 12px; font-weight: 650; display: flex; align-items: center; gap: 6px; color: var(--text); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--svc); }
</style>
