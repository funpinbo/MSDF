<script setup>
import { short, time } from '../format.js'

defineProps({ node: { type: Object, required: true }, via: { type: String, default: '' }, depth: { type: Number, default: 0 } })
</script>

<template>
  <div class="ln" :style="{ marginLeft: depth ? '16px' : 0 }">
    <div class="row wrap item">
      <span v-if="via" class="faint">{{ via }} ←</span>
      <b>{{ node.service }}.{{ node.action }}</b><span class="faint">.{{ node.slot }}</span>
      <span class="badge s-queued mono" :title="node.id">{{ short(node.id, 10) }}</span>
      <span class="faint">v {{ node.version }}</span>
      <span class="badge" :class="node.tier === 'hot' ? 's-done' : 's-cancelled'">{{ node.tier }}</span>
      <span v-if="node.deleted" class="badge s-failed">{{ node.deleted.reason === 'lost' ? '유실됨' : '삭제됨' }}</span>
      <span class="faint">{{ time(node.created_at) }}</span>
    </div>
    <div v-if="node.order_params" class="faint params mono">params {{ JSON.stringify(node.order_params) }}</div>
    <LineageTree v-for="p in node.parents" :key="p.id" :node="p" :via="p.slot" :depth="depth + 1" />
  </div>
</template>

<style scoped>
.ln { border-left: 1px dashed var(--line); padding-left: 10px; }
.item { padding: 4px 0; font-size: 13px; }
.params { font-size: 11px; margin: -2px 0 4px; }
</style>
