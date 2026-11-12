<script setup>
import { onBeforeUnmount, onMounted } from 'vue'
defineProps({ title: { type: String, default: '' } })
const emit = defineEmits(['close'])
function onKey(e) {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="backdrop" @click.self="emit('close')">
    <aside class="drawer" role="dialog" :aria-label="title">
      <div class="row head">
        <h2 class="grow">{{ title }}</h2>
        <slot name="actions" />
        <button class="ghost" aria-label="닫기" @click="emit('close')">✕</button>
      </div>
      <div class="body"><slot /></div>
    </aside>
  </div>
</template>

<style scoped>
.backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.25); z-index: 50; display: flex; justify-content: flex-end; }
.drawer { width: min(620px, 100%); height: 100%; background: var(--panel); border-left: 1px solid var(--line); display: flex; flex-direction: column; box-shadow: var(--shadow); }
.head { padding: 12px 16px; border-bottom: 1px solid var(--line); }
.body { padding: 14px 16px; overflow: auto; display: grid; gap: 12px; align-content: start; }
</style>
