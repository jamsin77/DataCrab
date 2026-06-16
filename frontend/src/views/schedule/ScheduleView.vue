<template>
  <div class="schedule-container">
    <div class="toolbar">
      <el-button type="primary" @click="showCreateDialog = true"><el-icon><Plus /></el-icon> 新建调度</el-button>
    </div>
    <el-table :data="schedules" stripe>
      <el-table-column prop="schedule_type" label="类型" width="100">
        <template #default="{ row }"><el-tag>{{ row.schedule_type }}</el-tag></template>
      </el-table-column>
      <el-table-column prop="cron_expression" label="Cron表达式" width="150" />
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : row.status === 'paused' ? 'warning' : 'info'">
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="next_run_at" label="下次执行" width="180" />
      <el-table-column label="操作" width="250">
        <template #default="{ row }">
          <el-button v-if="row.status === 'active'" size="small" @click="pauseSchedule(row.id)">暂停</el-button>
          <el-button v-if="row.status === 'paused'" size="small" type="primary" @click="resumeSchedule(row.id)">恢复</el-button>
          <el-button size="small" @click="viewExecutions(row.id)">执行历史</el-button>
          <el-button size="small" type="danger" @click="deleteSchedule(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="showCreateDialog" title="新建调度" width="500px">
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="流程ID"><el-input v-model="createForm.code_id" /></el-form-item>
        <el-form-item label="调度类型">
          <el-select v-model="createForm.schedule_type">
            <el-option label="Cron" value="cron" />
            <el-option label="事件" value="event" />
            <el-option label="手动" value="manual" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="createForm.schedule_type === 'cron'" label="Cron表达式">
          <el-input v-model="createForm.cron_expression" placeholder="0 0 * * *" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createSchedule">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/api/index'
import { ElMessage } from 'element-plus'

const schedules = ref<any[]>([])
const showCreateDialog = ref(false)
const createForm = ref({ code_id: '', schedule_type: 'cron', cron_expression: '' })

onMounted(async () => { schedules.value = await api.get('/schedules') })

async function createSchedule() {
  try {
    await api.post('/schedules', createForm.value)
    ElMessage.success('创建成功')
    showCreateDialog.value = false
    schedules.value = await api.get('/schedules')
  } catch (e: any) { ElMessage.error(e.response?.data?.detail || '创建失败') }
}

async function pauseSchedule(id: string) {
  await api.post(`/schedules/${id}/pause`)
  schedules.value = await api.get('/schedules')
}

async function resumeSchedule(id: string) {
  await api.post(`/schedules/${id}/resume`)
  schedules.value = await api.get('/schedules')
}

async function deleteSchedule(id: string) {
  await api.delete(`/schedules/${id}`)
  ElMessage.success('删除成功')
  schedules.value = await api.get('/schedules')
}

function viewExecutions(id: string) { /* TODO */ }
</script>

<style lang="scss" scoped>
.schedule-container { padding: 20px; background: #fff; border-radius: 8px; }
.toolbar { margin-bottom: 16px; }
</style>
