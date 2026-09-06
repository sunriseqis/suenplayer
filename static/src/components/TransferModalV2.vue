<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-panel">
      <div class="modal-head">
        <h3>批量转移分类</h3>
        <button class="close-btn" @click="$emit('close')" title="关闭">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/></svg>
        </button>
      </div>
      <p class="modal-sub">为 {{ videos.length }} 个条目选择目标分类，并写入转移规则——后续导入自动归入该分类。</p>

      <input class="search-input" v-model.trim="keyword" placeholder="搜索分类…" />

      <div class="cat-tree">
        <div v-for="r in filteredRegions" :key="r.id" class="region-block">
          <button class="region-row" :class="{ active: region === r.name }" @click="chooseRegion(r)">
            <span class="region-name">{{ r.name }}</span>
            <span class="region-count">一级分类</span>
          </button>
          <div class="group-rows" v-if="r.children?.length">
            <button v-for="g in r.children" :key="g.id"
                    class="group-row" :class="{ active: region === r.name && group === g.name }"
                    @click="chooseGroup(r, g)">
              {{ g.name }}
            </button>
          </div>
        </div>
        <div class="empty-tree" v-if="!filteredRegions.length">没有匹配的分类</div>
      </div>

      <div class="new-cat">
        <div class="new-cat-label">或创建新分类（一级 / 二级）</div>
        <div class="new-cat-row">
          <input v-model.trim="newRegion" placeholder="新一级分类名" />
          <input v-model.trim="newGroup" placeholder="新二级分类名（可选）" />
        </div>
      </div>

      <div class="target-line" v-if="targetText">目标：{{ targetText }}</div>

      <div class="modal-actions">
        <button class="btn ghost" @click="$emit('close')">取消</button>
        <button class="btn btn-primary" :disabled="!ready || busy" @click="confirm">
          {{ busy ? '转移中…' : `转移 ${videos.length} 个条目` }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
// V2 交互：分类树 + 计数标注 + 搜索 + 新建分类；确认后写入转移规则自动应用
import { ref, computed } from 'vue'

const props = defineProps({
  videos: { type: Array, default: () => [] },
  categories: { type: Array, default: () => [] },
  projectId: { type: Number, default: 1 }
})
const emit = defineEmits(['close', 'confirm'])

const keyword = ref('')
const region = ref('')
const group = ref('')
const newRegion = ref('')
const newGroup = ref('')
const busy = ref(false)

const filteredRegions = computed(() => {
  if (!keyword.value) return props.categories
  const k = keyword.value.toLowerCase()
  return props.categories
    .map(r => {
      const hitSelf = r.name.toLowerCase().includes(k)
      const kids = (r.children || []).filter(g => g.name.toLowerCase().includes(k))
      if (hitSelf || kids.length) return { ...r, children: hitSelf ? (r.children || []) : kids }
      return null
    })
    .filter(Boolean)
})

const ready = computed(() => {
  if (newRegion.value) return true
  return !!(region.value && group.value)
})

const targetText = computed(() => {
  if (newRegion.value) return `${newRegion.value}${newGroup.value ? ' / ' + newGroup.value : ''}（新建）`
  if (region.value && group.value) return `${region.value} / ${group.value}`
  return ''
})

function chooseRegion(r) {
  region.value = r.name
  group.value = ''
  newRegion.value = ''
  newGroup.value = ''
}
function chooseGroup(r, g) {
  region.value = r.name
  group.value = g.name
  newRegion.value = ''
  newGroup.value = ''
}

function confirm() {
  if (!ready.value) return
  emit('confirm', {
    bangous: props.videos.map(v => v.bangou),
    region: newRegion.value || region.value,
    group: newGroup.value || group.value
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
  width: min(520px, 100%); max-height: 86vh; overflow-y: auto;
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
.modal-sub { margin: 8px 0 12px; font-size: 12.5px; line-height: 1.6; color: var(--text-secondary); }

.search-input {
  width: 100%; height: 36px; padding: 0 12px; margin-bottom: 10px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-input); color: var(--text-primary); font-size: 13.5px;
  box-sizing: border-box;
  transition: border-color var(--duration-fast), box-shadow var(--duration-fast);
}
.search-input:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(255, 71, 87, 0.18);
}
.search-input::placeholder {
  color: var(--text-muted);
  opacity: 0.85;
}

.cat-tree { max-height: 300px; overflow-y: auto; border: 1px solid var(--border-light); border-radius: var(--radius-md); }
.region-block { border-bottom: 1px solid var(--border-light); }
.region-block:last-child { border-bottom: none; }
.region-row {
  width: 100%; display: flex; justify-content: space-between; align-items: center;
  padding: 9px 12px; border: none; background: none; cursor: pointer;
  color: var(--text-primary); font-size: 13.5px; text-align: left;
}
.region-row:hover { background: var(--bg-input); }
.region-row.active { background: var(--bg-input); color: var(--accent); font-weight: 600; }
.region-count { font-size: 11px; color: var(--text-muted); }
.group-rows { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 12px 10px 20px; }
.group-row {
  padding: 3px 10px; border-radius: 99px; border: 1px solid var(--border-light);
  background: var(--bg-input); color: var(--text-secondary); font-size: 12px; cursor: pointer;
}
.group-row:hover { border-color: var(--accent); color: var(--text-primary); }
.group-row.active { background: var(--accent); color: var(--text-inverse); border-color: var(--accent); }
.empty-tree { padding: 24px; text-align: center; color: var(--text-muted); font-size: 12.5px; }

.new-cat { margin-top: 12px; }
.new-cat-label { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.new-cat-row { display: flex; gap: 8px; }
.new-cat-row input {
  flex: 1; height: 36px; padding: 0 12px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-input); color: var(--text-primary); font-size: 13.5px;
  transition: border-color var(--duration-fast), box-shadow var(--duration-fast);
}
.new-cat-row input:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(255, 71, 87, 0.18);
}
.new-cat-row input::placeholder {
  color: var(--text-muted);
  opacity: 0.85;
}

.target-line { margin-top: 12px; font-size: 12.5px; color: var(--accent); }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
.btn { height: 36px; padding: 0 18px; border-radius: var(--radius-sm); border: none; cursor: pointer; font-size: 13px; }
.btn.ghost { background: var(--bg-input); color: var(--text-secondary); }
.btn.primary { background: var(--accent); color: #fff; }
.btn.primary:disabled { opacity: 0.55; cursor: default; }
</style>
