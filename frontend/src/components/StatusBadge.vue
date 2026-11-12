<script setup>
import { STATUS } from '../format.js'
defineProps({ status: { type: String, required: true }, label: { type: String, default: '' } })
</script>

<template>
  <span class="badge" :class="`s-${status}`">{{ label || STATUS[status] || status }}</span>
</template>
