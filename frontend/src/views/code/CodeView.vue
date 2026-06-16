<template>
  <div class="code-container">
    <div class="toolbar">
      <el-button type="primary" @click="showGenerateDialog = true"><el-icon><MagicStick /></el-icon> 从自然语言生成</el-button>
      <el-button @click="showCreateDialog = true"><el-icon><Plus /></el-icon> 手动创建</el-button>
    </div>
    <el-table :data="codes" stripe>
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="nl_description" label="描述" show-overflow-tooltip />
      <el-table-column prop="category" label="分类" width="120" />
      <el-table-column prop="version" label="版本" width="80" />
      <el-table-column prop="execution_count" label="执行次数" width="100" />
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click="executeCode(row.id)">执行</el-button>
          <el-button size="small" @click="viewCode(row.id)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="showGenerateDialog" title="从自然语言生成流程" width="600px">
      <el-input v-model="nlDescription" type="textarea" :rows="4" placeholder="描述你想要的数据处理流程..." />
      <template #footer>
        <el-button @click="showGenerateDialog = false">取消</el-button>
        <el-button type="primary" @click="generateCode">生成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/api/index'
import { ElMessage } from 'element-plus'

const codes = ref<any[]>([])
const showGenerateDialog = ref(false)
const showCreateDialog = ref(false)
const nlDescription = ref('')

onMounted(async () => { codes.value = await api.get('/codes') })

async function generateCode() {
  try {
    await api.post('/codes/generate', { nl_description: nlDescription.value })
    ElMessage.success('流程生成成功')
    showGenerateDialog.value = false
    codes.value = await api.get('/codes')
  } catch (e: any) { ElMessage.error(e.response?.data?.detail || '生成失败') }
}

async function executeCode(id: string) {
  try {
    const res = await api.post(`/codes/${id}/execute`, {})
    ElMessage.success('执行完成')
  } catch (e: any) { ElMessage.error(e.response?.data?.detail || '执行失败') }
}

function viewCode(id: string) { /* TODO */ }
</script>

<style lang="scss" scoped>
.code-container { padding: 20px; background: #fff; border-radius: 8px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; }
</style>
