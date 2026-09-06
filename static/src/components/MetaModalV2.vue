<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-panel">
      <div class="modal-head">
        <h3>元数据编辑</h3>
        <button class="close-btn" @click="$emit('close')" title="关闭">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/></svg>
        </button>
      </div>
      <p class="modal-sub">
        条目：<strong>{{ video?.bangou }}</strong>（{{ video?.title }}）。
        修改以覆盖方式持久化，重新导入后仍保持。
      </p>

      <div class="form">
        <label class="field"><span>标题</span><input v-model.trim="form.title" /></label>
        <label class="field"><span>封面地址</span><input v-model.trim="form.cover" placeholder="图片 URL" /></label>
        <label class="field"><span>链接</span><input v-model.trim="form.url" placeholder="条目主链接" /></label>
        <div class="field-row">
          <label class="field"><span>一级分类</span>
            <select v-model="form.region">
              <option value="">（保持不变）</option>
              <option v-for="r in regions" :key="r.id" :value="r.name">{{ r.name }}</option>
              <option value="__new__">新建…</option>
            </select>
          </label>
          <label class="field" v-if="form.region && form.region !== '__new__'"><span>二级分类</span>
            <select v-model="form.group_name">
              <option value="">（保持不变）</option>
              <option v-for="g in regionChildren" :key="g.id" :value="g.name">{{ g.name }}</option>
            </select>
          </label>
          <label class="field" v-if="form.region === '__new__'"><span>新一级分类名</span><input v-model.trim="newRegionName" /></label>
        </div>
        <label class="field"><span>标签（逗号分隔）</span><input v-model.trim="tagsInput" placeholder="标签1, 标签2" /></label>
      </div>

      <div class="modal-actions">
        <button class="btn ghost" @click="$emit('close')">取消</button>
        <button class="btn btn-primary" :disabled="busy || !hasChange" @click="confirm">
          {{ busy ? '保存中…' : '保存覆盖' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
// V2 交互：全字段编辑 + 分类下拉；保存为覆盖（overrides），导入后仍生效
import { ref, computed, reactive } from 'vue'

const props = defineProps({
  video: { type: Object, default: null },
  categories: { type: Array, default: () => [] },
  projectId: { type: Number, default: 1 }
})
const emit = defineEmits(['close', 'confirm'])

const form = reactive({
  title: props.video?.title || '',
  cover: props.video?.cover || '',
  url: props.video?.url || '',
  region: '',
  group_name: ''
})
const tagsInput = ref(props.video?.tags || '')
const newRegionName = ref('')
const busy = ref(false)

const regions = computed(() => props.categories)
const regionChildren = computed(() => {
  const r = props.categories.find(x => x.name === form.region)
  return r?.children || []
})

const hasChange = computed(() => {
  if (form.title && form.title !== props.video?.title) return true
  if (form.cover && form.cover !== props.video?.cover) return true
  if (form.url && form.url !== props.video?.url) return true
  if (form.region === '__new__' && newRegionName.value) return true
  if (form.region && form.region !== '__new__') return true
  if (form.group_name) return true
  if (tagsInput.value && tagsInput.value !== (props.video?.tags || '')) return true
  return false
})

function confirm() {
  const fields = {}
  if (form.title && form.title !== props.video?.title) fields.title = form.title
  if (form.cover && form.cover !== props.video?.cover) fields.cover = form.cover
  if (form.url && form.url !== props.video?.url) fields.url = form.url
  if (form.region === '__new__' && newRegionName.value) fields.region = newRegionName.value
  else if (form.region) fields.region = form.region
  if (form.group_name) fields.group_name = form.group_name
  if (tagsInput.value && tagsInput.value !== (props.video?.tags || '')) {
    fields.tags = tagsInput.value.split(/[,，]/).map(t => t.trim()).filter(Boolean)
  }
  emit('confirm', { bangou: props.video.bangou, fields })
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

.form { display: flex; flex-direction: column; gap: 12px; }
.field { display: flex; flex-direction: column; gap: 5px; flex: 1; }
.field span { font-size: 12.5px; font-weight: 500; color: var(--text-secondary); }
.field input, .field select {
  height: 38px; padding: 0 12px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-input); color: var(--text-primary); font-size: 14px;
  transition: border-color var(--duration-fast), box-shadow var(--duration-fast);
}
.field input:focus, .field select:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(255, 71, 87, 0.18);
}
.field input::placeholder {
  color: var(--text-muted);
  font-size: 13px;
  opacity: 0.85;
}
.field-row { display: flex; gap: 10px; }

.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
.btn { height: 36px; padding: 0 18px; border-radius: var(--radius-sm); border: none; cursor: pointer; font-size: 13px; }
.btn.ghost { background: var(--bg-input); color: var(--text-secondary); }
.btn.primary { background: var(--accent); color: #fff; }
.btn.primary:disabled { opacity: 0.55; cursor: default; }
</style>
