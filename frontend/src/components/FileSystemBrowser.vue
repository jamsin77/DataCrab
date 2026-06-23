<template>
  <el-dialog v-model="visible" :title="mode === 'folder' ? '选择文件夹' : '选择文件'" width="600px" @close="emit('cancel')">
    <div class="fs-browser">
      <div class="fs-path-bar">
        <el-input v-model="currentPath" size="default" @keydown.enter="navigateTo(currentPath)">
          <template #prepend>路径</template>
          <template #append>
            <el-button @click="navigateTo(currentPath)" :icon="Right" />
          </template>
        </el-input>
      </div>
      <div class="fs-list" v-loading="loading">
        <div class="fs-item fs-parent" @click="navigateTo(parentPath)" v-if="currentPath !== parentPath">
          <el-icon><Back /></el-icon>
          <span>..</span>
        </div>
        <div
          v-for="d in directories"
          :key="d.path"
          class="fs-item fs-dir"
          :class="{ selected: selectedPath === d.path }"
          @click="onSelectDir(d)"
          @dblclick="navigateTo(d.path)"
        >
          <el-icon><Folder /></el-icon>
          <span>{{ d.name }}</span>
        </div>
        <div
          v-for="f in files"
          :key="f.path"
          class="fs-item fs-file"
          :class="{ selected: selectedPath === f.path }"
          @click="onSelectFile(f)"
        >
          <el-icon><Document /></el-icon>
          <span>{{ f.name }}</span>
        </div>
        <el-empty v-if="!loading && directories.length === 0 && files.length === 0" description="空目录" :image-size="50" />
      </div>
      <div class="fs-selected" v-if="selectedPath">
        <span style="color:#909399">已选择：</span>{{ selectedPath }}
      </div>
    </div>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="confirm" :disabled="!selectedPath">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Back, Folder, Document, Right } from '@element-plus/icons-vue'
import api from '@/api/index'

const props = defineProps<{
  modelValue: boolean
  mode: 'file' | 'folder'
  ext?: string
  defaultPath?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'select', path: string): void
  (e: 'cancel'): void
}>()

const visible = ref(false)
const currentPath = ref('D:/')
const parentPath = ref('D:/')
const directories = ref<{ name: string; path: string }[]>([])
const files = ref<{ name: string; path: string }[]>([])
const selectedPath = ref('')
const loading = ref(false)

watch(() => props.modelValue, (v) => { visible.value = v })
watch(visible, (v) => { emit('update:modelValue', v) })

watch(() => props.modelValue, (v) => {
  if (v) {
    const start = props.defaultPath || 'D:/'
    navigateTo(start)
    selectedPath.value = ''
  }
})

async function navigateTo(path: string) {
  loading.value = true
  try {
    const res = await api.get('/filesystem/browse', {
      params: { path, mode: props.mode, ext: props.ext || '' },
    })
    currentPath.value = res.current
    parentPath.value = res.parent
    directories.value = res.directories || []
    files.value = res.files || []
  } catch {
    directories.value = []
    files.value = []
  } finally {
    loading.value = false
  }
}

function onSelectDir(d: { name: string; path: string }) {
  if (props.mode === 'folder') {
    selectedPath.value = d.path
  }
}

function onSelectFile(f: { name: string; path: string }) {
  if (props.mode === 'file') {
    selectedPath.value = f.path
  }
}

function confirm() {
  if (selectedPath.value) {
    emit('select', selectedPath.value)
    visible.value = false
  }
}
</script>

<style lang="scss" scoped>
.fs-browser {
  .fs-path-bar {
    margin-bottom: 10px;
  }
  .fs-list {
    border: 1px solid #e6e6e6;
    border-radius: 6px;
    max-height: 360px;
    overflow-y: auto;
  }
  .fs-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 14px;
    cursor: pointer;
    font-size: 13px;
    border-bottom: 1px solid #f5f5f5;
    transition: background 0.15s;
    &:hover {
      background: #f5f7fa;
    }
    &.selected {
      background: #ecf5ff;
      color: #409eff;
    }
  }
  .fs-parent {
    color: #909399;
  }
  .fs-selected {
    margin-top: 10px;
    font-size: 13px;
    color: #303133;
    word-break: break-all;
  }
}
</style>
