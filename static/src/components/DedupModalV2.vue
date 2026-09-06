<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-panel">
      <div class="modal-head">
        <h3>去重标记</h3>
        <button class="close-btn" @click="$emit('close')" title="关闭">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/></svg>
        </button>
      </div>
      <p class="modal-sub">
        保留条目：<strong>{{ keeper?.bangou }}</strong>（{{ keeper?.title }}）。
        勾选同项目内视为重复的条目并标记移除；标记会持久化，重新导入的重复条目也会被自动移除（不生成规则）。
      </p>

      <div class="dup-list" v-if="candidates.length">
        <label v-for="c in candidates" :key="c.bangou" class="dup-row" :class="{ checked: checked.includes(c.bangou) }">
          <input type="checkbox" :value="c.bangou" v-model="checked" />
          <span class="dup-title">{{ c.title }}</span>
          <span class="dup-meta">{{ c.bangou }} · {{ c.region || '' }}{{ c.group ? ' / ' + c.group : '' }}</span>
        </label>
      </div>
      <div class="empty-inline" v-else>当前页没有可作为重复项的条目；重复条目可在导入后于其它分类中标记。</div>

      <div class="copy-section" v-if="checked.length">
        <div class="field-label">从重复条目复制字段（可选，取第一个勾选条目的值）</div>
        <div class="copy-chips">
          <button v-for="f in COPY_FIELDS" :key="f.key"
                  class="chip" :class="{ active: copyFields.includes(f.key) }"
                  @click="toggleField(f.key)">{{ f.label }}</button>
        </div>
        <p class="copy-hint">仅支持标题 / 封面 / 链接三类字段。</p>
      </div>

      <div class="modal-actions">
        <button class="btn ghost" @click="$emit('close')">取消</button>
        <button class="btn danger" :disabled="!checked.length || busy" @click="confirm">
          {{ busy ? '标记中…' : `标记 ${checked.length} 条为重复` }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
// V2 交互：勾选重复条目 + 可选字段复制；标记持久化、导入时自动移除
import { ref } from 'vue'

const props = defineProps({
  keeper: { type: Object, default: null },
  candidates: { type: Array, default: () => [] },
  projectId: { type: Number, default: 1 }
})
const emit = defineEmits(['close', 'confirm'])

const COPY_FIELDS = [
  { key: 'title', label: '标题' },
  { key: 'cover', label: '封面' },
  { key: 'url', label: '链接' }
]

const checked = ref([])
const copyFields = ref([])
const busy = ref(false)

function toggleField(key) {
  const i = copyFields.value.indexOf(key)
  if (i >= 0) copyFields.value.splice(i, 1)
  else copyFields.value.push(key)
}

function confirm() {
  if (!checked.value.length) return
  // fields 语义（与后端一致）：{ 字段: 来源 bangou }
  const src = checked.value[0]
  const fields = {}
  for (const key of copyFields.value) fields[key] = src
  emit('confirm', {
    keeper: props.keeper.bangou,
    removed: [...checked.value],
    fields
  })
}
</script>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0; z-index: 3000;
  background: var(--surface-overlay);
  display: flex; align-items: center; justify-content: center; padding: 20px;
}
.modal-panel {
  width: min(560px, 100%); max-height: 86vh; overflow-y: auto;
  background: var(--panel); border: 1px solid var(--border);
  border-radius: var(--radius-lg); box-shadow: var(--shadow-floating);
  padding: 20px 22px;
}
.modal-head { display: flex; align-items: center; justify-content: space-between; }
.modal-head h3 { margin: 0; font-size: 16px; color: var(--text-primary); }
.close-btn {
  width: 28px; height: 28px; border: none; border-radius: var(--radius-sm);
  background: none; color: var(--text-secondary); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}
.close-btn:hover { background: var(--bg-input); color: var(--text-primary); }
.modal-sub { margin: 8px 0 14px; font-size: 12.5px; line-height: 1.7; color: var(--text-secondary); }

.dup-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; max-height: 280px; overflow-y: auto; }
.dup-row {
  display: flex; align-items: center; gap: 10px; padding: 8px 10px;
  border: 1px solid var(--border-light); border-radius: var(--radius-md); cursor: pointer;
}
.dup-row.checked { border-color: var(--error); background: var(--bg-input); }
.dup-row input { flex: none; }
.dup-title { flex: 1; min-width: 0; font-size: 13px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dup-meta { flex: none; font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); }
.empty-inline { padding: 20px; text-align: center; color: var(--text-muted); font-size: 12.5px; border: 1px dashed var(--border-light); border-radius: var(--radius-md); margin-bottom: 14px; }

.copy-section { margin-bottom: 6px; }
.field-label { font-size: 12px; color: var(--text-secondary); margin-bottom: 8px; }
.copy-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  padding: 4px 12px; border-radius: 99px; border: 1px solid var(--border-light);
  background: var(--bg-input); color: var(--text-secondary); font-size: 12px; cursor: pointer;
}
.chip.active { background: var(--accent); color: var(--text-inverse); border-color: var(--accent); }
.copy-hint { margin: 8px 0 0; font-size: 11.5px; color: var(--text-muted); }

.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
.btn { height: 36px; padding: 0 18px; border-radius: var(--radius-sm); border: none; cursor: pointer; font-size: 13px; }
.btn.ghost { background: var(--bg-input); color: var(--text-secondary); }
.btn.danger { background: var(--error); color: #fff; }
.btn.danger:disabled { opacity: 0.55; cursor: default; }
</style>
