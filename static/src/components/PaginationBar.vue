<template>
  <div class="pager">
    <button class="pg-btn" :disabled="page <= 1" @click="go(page - 1)" title="上一页">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 6 9 12 15 18"/></svg>
    </button>
    <span class="pg-info">第 {{ page }} / {{ totalPages }} 页</span>
    <span class="pg-jump">
      跳至
      <input class="pg-input" type="number" min="1" :max="totalPages" v-model.number="jumpTo"
             @keyup.enter="doJump" @blur="doJump" />
      页
    </span>
    <button class="pg-btn" :disabled="page >= totalPages" @click="go(page + 1)" title="下一页">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"/></svg>
    </button>
  </div>
</template>

<script setup>
// D6: 分页器支持直接输入页码跳转
import { ref, watch } from 'vue'

const props = defineProps({
  page: { type: Number, default: 1 },
  totalPages: { type: Number, default: 1 }
})
const emit = defineEmits(['jump'])

const jumpTo = ref(props.page)
watch(() => props.page, (v) => { jumpTo.value = v })

function go(p) {
  if (p >= 1 && p <= props.totalPages && p !== props.page) emit('jump', p)
}
function doJump() {
  const p = parseInt(jumpTo.value, 10)
  if (!Number.isFinite(p)) { jumpTo.value = props.page; return }
  const clamped = Math.min(Math.max(p, 1), props.totalPages)
  jumpTo.value = clamped
  if (clamped !== props.page) emit('jump', clamped)
}
</script>

<style scoped>
.pager {
  display: inline-flex; align-items: center; gap: 12px;
  padding: 8px 14px; border-radius: var(--radius-md);
  background: var(--bg-card); border: 1px solid var(--border-light);
}
.pg-btn {
  display: flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; border-radius: var(--radius-sm);
  border: 1px solid var(--border-light); background: var(--bg-input);
  color: var(--text-secondary); cursor: pointer;
}
.pg-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--text-primary); }
.pg-btn:disabled { opacity: 0.4; cursor: default; }
.pg-info { font-size: var(--text-base); color: var(--text-secondary); }
.pg-jump { display: inline-flex; align-items: center; gap: 6px; font-size: var(--text-base); color: var(--text-muted); }
.pg-input {
  width: 56px; height: 28px; text-align: center;
  border: 1px solid var(--border-light); border-radius: var(--radius-sm);
  background: var(--bg-input); color: var(--text-primary); font-size: var(--text-base);
  -moz-appearance: textfield;
}
.pg-input::-webkit-outer-spin-button, .pg-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.pg-input:focus { outline: none; border-color: var(--accent); }
</style>
