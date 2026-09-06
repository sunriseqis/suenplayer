<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-panel">
      <div class="modal-head">
        <h3>合并重复条目</h3>
        <button class="close-btn" @click="$emit('close')" title="关闭">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/></svg>
        </button>
      </div>
      <p class="modal-sub">选择要保留的条目；其余条目合并为指向保留条目的重定向，并写入合并规则——后续导入自动应用，重复条目不会再出现。</p>

      <div class="keeper-list">
        <div v-for="v in videos" :key="v.bangou"
             class="keeper-row" :class="{ chosen: keeper === v.bangou }"
             @click="keeper = v.bangou">
          <div class="keep-thumb">
            <img :src="$imgUrl(v.cover)" @error="$imgFallback" v-if="v.cover" />
            <div class="thumb-ph" v-else>{{ v.site || '' }}</div>
          </div>
          <div class="keep-info">
            <div class="keep-title">{{ v.title }}</div>
            <div class="keep-meta">{{ v.bangou }} · {{ v.region || '' }}{{ v.group ? ' / ' + v.group : '' }}</div>
          </div>
          <span class="keep-badge" v-if="keeper === v.bangou">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 12.5 10 18.5 20 6.5"/></svg>
            保留
          </span>
        </div>
      </div>

      <div class="field-section" v-if="keeper">
        <div class="field-label">字段取值（勾选表示采用该来源条目的值）</div>
        <div class="field-grid">
          <div v-for="f in FIELDS" :key="f.key" class="field-card">
            <div class="field-name">{{ f.label }}</div>
            <div class="field-choices">
              <button v-for="v in videos" :key="v.bangou"
                      class="choice" :class="{ active: fields[f.key] === v.bangou }"
                      :disabled="v.bangou === keeper"
                      @click="pick(f.key, v.bangou)"
                      :title="`${f.label} 来自 ${v.bangou}`">
                {{ v.bangou === keeper ? '保留' : v.bangou }}
                <span v-if="hasConflict(f.key)" class="conflict-dot" title="各条目该字段值不同"></span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="modal-actions">
        <button class="btn ghost" @click="$emit('close')">取消</button>
        <button class="btn primary" :disabled="!keeper || busy" @click="confirm">
          {{ busy ? '合并中…' : `合并 ${videos.length - 1} 条到 ${keeper || '…'}` }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
// V2 交互（管理操作交互重设计）：保留卡 + 字段 chip 取值 + 冲突标记；操作后写入规则自动应用
import { ref, computed } from 'vue'

const props = defineProps({
  videos: { type: Array, default: () => [] },
  projectId: { type: Number, default: 1 }
})
const emit = defineEmits(['close', 'confirm'])

const FIELDS = [
  { key: 'title', label: '标题' },
  { key: 'cover', label: '封面' },
  { key: 'url', label: '链接' },
  { key: 'region', label: '一级分类' },
  { key: 'group_name', label: '二级分类' },
  { key: 'tags', label: '标签' }
]

const keeper = ref(props.videos[0]?.bangou || '')
const fields = ref({})
const busy = ref(false)

const others = computed(() => props.videos.filter(v => v.bangou !== keeper.value))

function fieldVal(v, key) {
  if (key === 'group_name') return v.group || v.group_name || ''
  return v[key] || ''
}

function hasConflict(key) {
  const vals = new Set(props.videos.map(v => JSON.stringify(fieldVal(v, key))))
  return vals.size > 1
}

function pick(key, bangou) {
  if (fields.value[key] === bangou) delete fields.value[key]
  else fields.value[key] = bangou
}

async function confirm() {
  if (!keeper.value) return
  busy.value = true
  // fields: { 字段名: 来源bangou }，后端按来源条目取值
  const payload = { bangous: props.videos.map(v => v.bangou), keeper: keeper.value, fields: { ...fields.value } }
  emit('confirm', payload)
}
</script>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0; z-index: 3000;
  background: var(--surface-overlay);
  display: flex; align-items: center; justify-content: center; padding: 20px;
}
.modal-panel {
  width: min(640px, 100%); max-height: 86vh; overflow-y: auto;
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
.modal-sub { margin: 8px 0 14px; font-size: 12.5px; line-height: 1.6; color: var(--text-secondary); }

.keeper-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.keeper-row {
  display: flex; align-items: center; gap: 12px; padding: 8px;
  border: 1px solid var(--border-light); border-radius: var(--radius-md);
  cursor: pointer; transition: border-color .15s, background .15s;
}
.keeper-row:hover { border-color: var(--accent); }
.keeper-row.chosen { border-color: var(--accent); background: var(--bg-input); }
.keep-thumb { width: 84px; aspect-ratio: 16/9; border-radius: var(--radius-sm); overflow: hidden; flex: none; }
.keep-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb-ph { width: 100%; height: 100%; background: linear-gradient(135deg, var(--recessed), var(--deep-shadow)); display: flex; align-items: center; justify-content: center; font-size: 10px; color: var(--text-muted); }
.keep-info { flex: 1; min-width: 0; }
.keep-title { font-size: 13.5px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.keep-meta { font-size: 11.5px; color: var(--text-muted); font-family: var(--font-mono); margin-top: 2px; }
.keep-badge {
  display: inline-flex; align-items: center; gap: 4px; flex: none;
  padding: 3px 10px; border-radius: 99px; background: var(--success); color: #fff; font-size: 11.5px; font-weight: 600;
}

.field-section { margin-bottom: 6px; }
.field-label { font-size: 12px; color: var(--text-secondary); margin-bottom: 8px; }
.field-grid { display: flex; flex-direction: column; gap: 8px; }
.field-card { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.field-name { width: 70px; flex: none; font-size: 12px; color: var(--text-primary); }
.field-choices { display: flex; gap: 6px; flex-wrap: wrap; }
.choice {
  position: relative; padding: 3px 10px; border-radius: 99px;
  border: 1px solid var(--border-light); background: var(--bg-input);
  color: var(--text-secondary); font-size: 11.5px; cursor: pointer; font-family: var(--font-mono);
}
.choice:hover:not(:disabled) { border-color: var(--accent); color: var(--text-primary); }
.choice.active { background: var(--accent); color: var(--text-inverse); border-color: var(--accent); }
.choice:disabled { opacity: 0.55; cursor: default; }
.conflict-dot {
  position: absolute; top: -2px; right: -2px; width: 7px; height: 7px; border-radius: 50%;
  background: var(--warning, var(--accent));
}

.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
.btn { height: 36px; padding: 0 18px; border-radius: var(--radius-sm); border: none; cursor: pointer; font-size: 13px; }
.btn.ghost { background: var(--bg-input); color: var(--text-secondary); }
.btn.primary { background: var(--accent); color: #fff; }
.btn.primary:disabled { opacity: 0.55; cursor: default; }
</style>
