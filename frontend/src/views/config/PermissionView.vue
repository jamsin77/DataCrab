<template>
  <div class="permission-container">
    <el-tabs v-model="activeTab">
      <el-tab-pane label="资源授权" name="grants">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>资源授权管理</span>
              <el-button type="primary" size="small" @click="showGrantDialog = true">
                <el-icon><Share /></el-icon> 新增授权
              </el-button>
            </div>
          </template>

          <div class="filter-bar">
            <el-select v-model="filterType" placeholder="资源类型" clearable style="width: 150px" @change="loadResourcePerms">
              <el-option label="数据源" value="datasource" />
              <el-option label="算子" value="operator" />
              <el-option label="技能" value="skill" />
              <el-option label="元数据" value="metadata" />
            </el-select>
            <el-input v-model="filterResourceId" placeholder="资源ID (UUID)" clearable style="width: 320px" @keyup.enter="loadResourcePerms" />
            <el-button @click="loadResourcePerms" :disabled="!filterType || !filterResourceId">查询授权</el-button>
          </div>

          <el-table :data="resourcePerms" v-loading="loadingPerms" style="width: 100%; margin-top: 16px" empty-text="输入资源类型和ID查询授权列表">
            <el-table-column prop="user_name" label="用户" width="120">
              <template #default="{ row }">
                <el-tag v-if="row.user_name" type="primary" size="small">{{ row.user_name }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="role_name" label="角色" width="120">
              <template #default="{ row }">
                <el-tag v-if="row.role_name" type="warning" size="small">{{ row.role_name }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="permission_level" label="权限级别" width="100">
              <template #default="{ row }">
                <el-tag :type="levelColor(row.permission_level)" size="small">{{ levelLabel(row.permission_level) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="授权时间" width="180" />
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button type="danger" size="small" text @click="doRevoke(row)">撤销</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="我的权限" name="mine">
        <el-card>
          <template #header><span>我被授予的权限</span></template>
          <el-table :data="myPerms" v-loading="loadingMine" style="width: 100%" empty-text="暂无被授权的资源">
            <el-table-column prop="resource_type" label="资源类型" width="120">
              <template #default="{ row }">{{ typeLabel(row.resource_type) }}</template>
            </el-table-column>
            <el-table-column prop="resource_id" label="资源ID" width="320" show-overflow-tooltip />
            <el-table-column prop="permission_level" label="权限级别" width="100">
              <template #default="{ row }">
                <el-tag :type="levelColor(row.permission_level)" size="small">{{ levelLabel(row.permission_level) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="granted_via" label="来源" width="100">
              <template #default="{ row }">
                <el-tag :type="row.granted_via === 'role' ? 'warning' : 'primary'" size="small" effect="plain">
                  {{ row.granted_via === 'role' ? '角色' : '直接' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="授权时间" />
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="角色管理" name="roles">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>角色管理</span>
              <el-button type="primary" size="small" @click="showRoleDialog = true" v-if="isSuperuser">
                <el-icon><Plus /></el-icon> 创建角色
              </el-button>
            </div>
          </template>
          <el-table :data="roles" v-loading="loadingRoles" style="width: 100%" empty-text="暂无角色">
            <el-table-column prop="display_name" label="角色名称" width="150" />
            <el-table-column prop="name" label="标识" width="150" />
            <el-table-column prop="description" label="描述" />
            <el-table-column prop="member_count" label="成员数" width="80" />
            <el-table-column label="操作" width="200">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="openRoleMembers(row)">成员管理</el-button>
                <el-button size="small" text type="success" @click="openCopyDialog(row)">复制权限到角色</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="用户列表" name="users">
        <el-card>
          <template #header><span>用户列表</span></template>
          <el-table :data="users" v-loading="loadingUsers" style="width: 100%" empty-text="暂无用户">
            <el-table-column prop="display_name" label="用户名" width="150" />
            <el-table-column prop="username" label="账号" width="150" />
            <el-table-column prop="email" label="邮箱" />
            <el-table-column label="角色" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.is_superuser" type="danger" size="small">管理员</el-tag>
                <el-tag v-else type="info" size="small">普通用户</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200">
              <template #default="{ row }">
                <el-button size="small" text type="success" @click="openCopyDialog(row)">复制权限给此用户</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="showGrantDialog" title="新增授权" width="500px">
      <el-form label-width="100px">
        <el-form-item label="资源类型">
          <el-select v-model="grantForm.resource_type" style="width: 100%">
            <el-option label="数据源" value="datasource" />
            <el-option label="算子" value="operator" />
            <el-option label="技能" value="skill" />
            <el-option label="元数据" value="metadata" />
          </el-select>
        </el-form-item>
        <el-form-item label="资源ID">
          <el-input v-model="grantForm.resource_id" placeholder="资源UUID" />
        </el-form-item>
        <el-form-item label="授权对象">
          <el-radio-group v-model="grantTargetType">
            <el-radio value="user">用户</el-radio>
            <el-radio value="role">角色</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="选择用户" v-if="grantTargetType === 'user'">
          <el-select v-model="grantForm.user_id" filterable placeholder="选择用户" style="width: 100%">
            <el-option v-for="u in users" :key="u.id" :label="u.display_name" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="选择角色" v-if="grantTargetType === 'role'">
          <el-select v-model="grantForm.role_id" filterable placeholder="选择角色" style="width: 100%">
            <el-option v-for="r in roles" :key="r.id" :label="r.display_name" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="权限级别">
          <el-select v-model="grantForm.permission_level" style="width: 100%">
            <el-option label="查看 (view)" value="view" />
            <el-option label="使用 (use)" value="use" />
            <el-option label="管理 (manage)" value="manage" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showGrantDialog = false">取消</el-button>
        <el-button type="primary" @click="doGrant" :loading="granting">授权</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showRoleDialog" title="创建角色" width="450px">
      <el-form label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="roleForm.name" placeholder="英文标识，如 data_analyst" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="roleForm.display_name" placeholder="中文名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="roleForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRoleDialog = false">取消</el-button>
        <el-button type="primary" @click="doCreateRole" :loading="creatingRole">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showMembersDialog" :title="'角色成员: ' + (currentRole?.display_name || '')" width="500px">
      <div style="margin-bottom: 12px; display: flex; gap: 8px;">
        <el-select v-model="newMemberId" filterable placeholder="选择用户" style="flex: 1">
          <el-option v-for="u in users" :key="u.id" :label="u.display_name" :value="u.id" />
        </el-select>
        <el-button type="primary" @click="doAddMember" :disabled="!newMemberId">添加</el-button>
      </div>
      <el-table :data="roleMembers" style="width: 100%" empty-text="暂无成员">
        <el-table-column prop="display_name" label="用户名" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button type="danger" size="small" text @click="doRemoveMember(row)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="showCopyDialog" :title="'复制权限'" width="450px">
      <p style="margin-bottom: 12px; color: #606266;">
        将 <strong>{{ copySource?.display_name || copySource?.name }}</strong> 的所有权限复制给：
      </p>
      <el-radio-group v-model="copyTargetType" style="margin-bottom: 12px;">
        <el-radio value="user">用户</el-radio>
        <el-radio value="role">角色</el-radio>
      </el-radio-group>
      <el-select v-if="copyTargetType === 'user'" v-model="copyTargetId" filterable placeholder="选择目标用户" style="width: 100%">
        <el-option v-for="u in users" :key="u.id" :label="u.display_name" :value="u.id" :disabled="u.id === copySource?.id" />
      </el-select>
      <el-select v-else v-model="copyTargetId" filterable placeholder="选择目标角色" style="width: 100%">
        <el-option v-for="r in roles" :key="r.id" :label="r.display_name" :value="r.id" :disabled="r.id === copySource?.id" />
      </el-select>
      <template #footer>
        <el-button @click="showCopyDialog = false">取消</el-button>
        <el-button type="primary" @click="doCopy" :loading="copying">复制权限</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { Share, Plus } from '@element-plus/icons-vue'
import api from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'

const activeTab = ref('grants')
const isSuperuser = ref(false)

const filterType = ref('')
const filterResourceId = ref('')
const resourcePerms = ref<any[]>([])
const loadingPerms = ref(false)

const myPerms = ref<any[]>([])
const loadingMine = ref(false)

const roles = ref<any[]>([])
const loadingRoles = ref(false)

const users = ref<any[]>([])
const loadingUsers = ref(false)

const showGrantDialog = ref(false)
const granting = ref(false)
const grantTargetType = ref('user')
const grantForm = reactive({
  resource_type: 'datasource',
  resource_id: '',
  user_id: '',
  role_id: '',
  permission_level: 'view',
})

const showRoleDialog = ref(false)
const creatingRole = ref(false)
const roleForm = reactive({ name: '', display_name: '', description: '' })

const showMembersDialog = ref(false)
const currentRole = ref<any>(null)
const roleMembers = ref<any[]>([])
const newMemberId = ref('')

const showCopyDialog = ref(false)
const copySource = ref<any>(null)
const copyTargetType = ref('user')
const copyTargetId = ref('')
const copying = ref(false)

function levelColor(level: string) {
  return { view: 'info', use: 'warning', manage: 'danger' }[level] || 'info'
}
function levelLabel(level: string) {
  return { view: '查看', use: '使用', manage: '管理' }[level] || level
}
function typeLabel(type: string) {
  return { datasource: '数据源', operator: '算子', skill: '技能', metadata: '元数据' }[type] || type
}

async function loadMyPerms() {
  loadingMine.value = true
  try {
    myPerms.value = await api.get('/permissions/my-permissions')
  } catch { myPerms.value = [] }
  finally { loadingMine.value = false }
}

async function loadRoles() {
  loadingRoles.value = true
  try {
    roles.value = await api.get('/permissions/roles')
  } catch { roles.value = [] }
  finally { loadingRoles.value = false }
}

async function loadUsers() {
  loadingUsers.value = true
  try {
    users.value = await api.get('/permissions/users')
    isSuperuser.value = users.value.find((u: any) => u.username === localStorage.getItem('username'))?.is_superuser || false
  } catch { users.value = [] }
  finally { loadingUsers.value = false }
}

async function loadResourcePerms() {
  if (!filterType.value || !filterResourceId.value) return
  loadingPerms.value = true
  try {
    resourcePerms.value = await api.get(`/permissions/resource/${filterType.value}/${filterResourceId.value}`)
  } catch {
    resourcePerms.value = []
    ElMessage.error('查询失败')
  }
  finally { loadingPerms.value = false }
}

async function doGrant() {
  granting.value = true
  try {
    await api.post('/permissions/grant', {
      ...grantForm,
      user_id: grantTargetType.value === 'user' ? grantForm.user_id : null,
      role_id: grantTargetType.value === 'role' ? grantForm.role_id : null,
    })
    ElMessage.success('授权成功')
    showGrantDialog.value = false
    if (filterType.value && filterResourceId.value) loadResourcePerms()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '授权失败')
  } finally { granting.value = false }
}

async function doRevoke(row: any) {
  try {
    await ElMessageBox.confirm(`确定撤销 ${row.user_name || row.role_name} 的权限？`, '确认', { type: 'warning' })
    await api.post('/permissions/revoke', {
      resource_type: row.resource_type,
      resource_id: row.resource_id,
      user_id: row.user_id || null,
      role_id: row.role_id || null,
      permission_level: row.permission_level,
    })
    ElMessage.success('已撤销')
    loadResourcePerms()
  } catch { /* cancelled */ }
}

async function doCreateRole() {
  creatingRole.value = true
  try {
    await api.post('/permissions/roles', roleForm)
    ElMessage.success('角色已创建')
    showRoleDialog.value = false
    roleForm.name = ''; roleForm.display_name = ''; roleForm.description = ''
    loadRoles()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  } finally { creatingRole.value = false }
}

async function openRoleMembers(role: any) {
  currentRole.value = role
  showMembersDialog.value = true
  try {
    roleMembers.value = await api.get(`/permissions/roles/${role.id}/members`)
  } catch { roleMembers.value = [] }
}

async function doAddMember() {
  try {
    await api.post(`/permissions/roles/${currentRole.value.id}/members`, { user_id: newMemberId.value })
    ElMessage.success('已添加成员')
    newMemberId.value = ''
    roleMembers.value = await api.get(`/permissions/roles/${currentRole.value.id}/members`)
    loadRoles()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '添加失败')
  }
}

async function doRemoveMember(row: any) {
  try {
    await api.delete(`/permissions/roles/${currentRole.value.id}/members/${row.id}`)
    ElMessage.success('已移除')
    roleMembers.value = await api.get(`/permissions/roles/${currentRole.value.id}/members`)
    loadRoles()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '移除失败')
  }
}

function openCopyDialog(source: any) {
  copySource.value = source
  copyTargetType.value = 'user'
  copyTargetId.value = ''
  showCopyDialog.value = true
}

async function doCopy() {
  if (!copyTargetId.value) {
    ElMessage.warning('请选择目标')
    return
  }
  const isRole = 'member_count' in copySource.value
  copying.value = true
  try {
    const res = await api.post('/permissions/copy', {
      source_user_id: isRole ? '' : copySource.value.id,
      target_user_id: copyTargetType.value === 'user' ? copyTargetId.value : null,
      target_role_id: copyTargetType.value === 'role' ? copyTargetId.value : null,
    })
    ElMessage.success(res.message || '复制成功')
    showCopyDialog.value = false
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '复制失败')
  } finally { copying.value = false }
}

onMounted(() => {
  loadMyPerms()
  loadRoles()
  loadUsers()
})
</script>

<style lang="scss" scoped>
.permission-container {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.filter-bar {
  display: flex;
  gap: 12px;
  align-items: center;
}
</style>
