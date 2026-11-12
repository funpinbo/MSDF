<script setup>
import { Handle, Position } from '@vue-flow/core'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: Boolean,
  connected: { type: Array, default: () => [] },
  result: { type: Object, default: null },
  hasError: Boolean,
})
const emit = defineEmits(['result'])
function isResult(slot) {
  return props.result && props.result.node === props.id && props.result.slot === slot
}
</script>

<template>
  <div class="enode" :class="{ bad: hasError, unknown: !data.spec, sel: selected }" :style="{ '--svc': data.color }">
    <div class="head">
      <span class="svc">{{ data.service }}</span>
      <span class="opts">
        <span v-if="data.options.fresh_for" title="fresh_for">⏱ {{ data.options.fresh_for }}</span>
        <span v-if="data.options.retries != null" title="retries">↻ {{ data.options.retries }}</span>
      </span>
    </div>
    <div class="title">
      <b>{{ id }}</b>
      <span v-if="id !== data.action" class="faint">{{ data.action }}</span>
    </div>
    <div v-if="!data.spec" class="warn">코드에 없는 Action입니다</div>
    <div v-if="data.spec?.params.length" class="params">params: {{ data.spec.params.join(', ') }}</div>
    <div class="slots">
      <div class="col">
        <div v-for="slot in data.spec?.inputs || []" :key="'in' + slot" class="slot in" :class="{ missing: !connected.includes(slot) }">
          <Handle :id="`in:${slot}`" type="target" :position="Position.Left" class="handle" />
          {{ slot }}
        </div>
      </div>
      <div class="col right">
        <div v-for="slot in data.spec?.outputs || []" :key="'out' + slot" class="slot out" :class="{ result: isResult(slot) }">
          <button class="star nodrag" :title="isResult(slot) ? '이 DAG의 결과' : '이 출력을 결과로'" @click.stop="emit('result', { node: id, slot })">
            {{ isResult(slot) ? '★' : '☆' }}
          </button>
          {{ slot }}
          <Handle :id="`out:${slot}`" type="source" :position="Position.Right" class="handle" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.enode {
  width: 230px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-top: 4px solid var(--svc);
  border-radius: 10px;
  box-shadow: var(--shadow);
  font-size: 12px;
  padding-bottom: 6px;
}
.enode.sel { border-color: var(--accent); border-top-color: var(--svc); }
.enode.bad { border-color: var(--fail); border-top-color: var(--fail); }
.enode.unknown { border-style: dashed; }
.head { display: flex; justify-content: space-between; padding: 6px 10px 0; }
.svc { color: var(--svc); font-weight: 650; text-transform: uppercase; letter-spacing: 0.04em; font-size: 11px; }
.opts { display: flex; gap: 6px; color: var(--muted); }
.title { padding: 0 10px 4px; display: flex; gap: 6px; align-items: baseline; }
.title b { font-size: 14px; }
.warn { margin: 0 10px 4px; color: var(--fail); }
.params { margin: 0 10px 4px; color: var(--cache); }
.slots { display: flex; justify-content: space-between; gap: 8px; border-top: 1px solid var(--line-2); padding-top: 4px; }
.col { display: grid; gap: 2px; min-width: 0; }
.col.right { justify-items: end; }
.slot { position: relative; padding: 3px 12px; color: var(--muted); display: flex; align-items: center; gap: 4px; white-space: nowrap; }
.slot.in.missing { color: var(--fail); }
.slot.result { color: var(--accent); font-weight: 650; }
.star { border: 0; background: none; padding: 0 2px; color: inherit; font-size: 13px; line-height: 1; }
.star:hover { color: var(--accent); }
.handle { width: 11px; height: 11px; background: var(--panel); border: 2px solid var(--svc); }
.slot.in .handle { left: -6px; }
.slot.out .handle { right: -6px; }
.slot.in.missing .handle { border-color: var(--fail); }
</style>
