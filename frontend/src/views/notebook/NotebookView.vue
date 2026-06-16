<template>
  <div class="notebook-container">
    <div class="notebook-toolbar">
      <el-select v-model="currentKernel" style="width: 150px">
        <el-option label="Python 3" value="python3" />
        <el-option label="SQL" value="sql" />
      </el-select>
      <el-button-group>
        <el-button @click="addCell('code')"><el-icon><Plus /></el-icon> 代码</el-button>
        <el-button @click="addCell('markdown')"><el-icon><Document /></el-icon> Markdown</el-button>
        <el-button @click="runAllCells"><el-icon><VideoPlay /></el-icon> 全部运行</el-button>
        <el-button @click="restartKernel"><el-icon><RefreshRight /></el-icon> 重启内核</el-button>
      </el-button-group>
      <el-button @click="saveNotebook"><el-icon><FolderOpened /></el-icon> 保存</el-button>
    </div>

    <div class="notebook-cells">
      <div v-for="(cell, index) in cells" :key="cell.id" class="cell-item">
        <div class="cell-header">
          <span class="cell-index">[{{ index + 1 }}]</span>
          <el-tag :type="cell.type === 'code' ? 'primary' : 'success'" size="small">
            {{ cell.type }}
          </el-tag>
          <div class="cell-actions">
            <el-button size="small" text @click="runCell(index)">
              <el-icon><VideoPlay /></el-icon>
            </el-button>
            <el-button size="small" text @click="moveCell(index, -1)">
              <el-icon><Top /></el-icon>
            </el-button>
            <el-button size="small" text @click="moveCell(index, 1)">
              <el-icon><Bottom /></el-icon>
            </el-button>
            <el-button size="small" text type="danger" @click="deleteCell(index)">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>
        <div class="cell-editor">
          <el-input
            v-model="cell.content"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 20 }"
            :placeholder="cell.type === 'code' ? '输入代码...' : '输入Markdown...'"
          />
        </div>
        <div v-if="cell.output" class="cell-output">
          <pre v-if="cell.output.type === 'text'">{{ cell.output.content }}</pre>
          <div v-else-if="cell.output.type === 'error'" class="error-output">{{ cell.output.content }}</div>
        </div>
      </div>
    </div>

    <!-- 变量监视器 -->
    <div class="variable-watcher">
      <h3>变量</h3>
      <el-table :data="variables" size="small" empty-text="暂无变量">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="type" label="类型" />
        <el-table-column prop="value" label="值" />
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

interface CellOutput {
  type: string
  content: string
}

interface NotebookCell {
  id: string
  type: 'code' | 'markdown'
  content: string
  output: CellOutput | null
}

const currentKernel = ref('python3')
const cells = ref<NotebookCell[]>([])
const variables = ref<any[]>([])

function addCell(type: 'code' | 'markdown') {
  cells.value.push({
    id: `cell-${Date.now()}`,
    type,
    content: '',
    output: null,
  })
}

function deleteCell(index: number) {
  cells.value.splice(index, 1)
}

function moveCell(index: number, direction: number) {
  const newIndex = index + direction
  if (newIndex < 0 || newIndex >= cells.value.length) return
  const temp = cells.value[index]
  cells.value[index] = cells.value[newIndex]
  cells.value[newIndex] = temp
}

function runCell(index: number) {
  // TODO: 调用后端执行API
  cells.value[index].output = { type: 'text', content: '执行结果示例' }
}

function runAllCells() {
  cells.value.forEach((_, i) => runCell(i))
}

function restartKernel() {
  variables.value = []
  cells.value.forEach((cell) => { cell.output = null })
}

function saveNotebook() {
  // TODO: 调用后端保存API
}
</script>

<style lang="scss" scoped>
.notebook-container {
  display: flex;
  height: 100%;
  gap: 16px;
}

.notebook-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 12px;
  background: #fff;
  border-radius: 8px;
  margin-bottom: 12px;
}

.notebook-cells {
  flex: 1;
  overflow-y: auto;

  .cell-item {
    background: #fff;
    border: 1px solid #e6e6e6;
    border-radius: 8px;
    margin-bottom: 12px;

    .cell-header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-bottom: 1px solid #f0f0f0;

      .cell-index { color: #999; font-size: 12px; }
      .cell-actions { margin-left: auto; }
    }

    .cell-editor { padding: 12px; }

    .cell-output {
      padding: 12px;
      border-top: 1px solid #f0f0f0;
      background: #f8f8f8;

      pre { margin: 0; white-space: pre-wrap; }
      .error-output { color: #f56c6c; }
    }
  }
}

.variable-watcher {
  width: 280px;
  background: #fff;
  border-radius: 8px;
  padding: 12px;
  overflow-y: auto;

  h3 { margin: 0 0 12px; }
}
</style>
