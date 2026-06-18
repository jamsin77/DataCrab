# 调度页面问题排查

## ✅ 后端检查结果

### 模型正常
- Schedule模型：21个字段
- TaskExecution模型：18个字段

### 路由正常
- 12个API端点
- 包括CRUD、暂停/恢复、触发、验证等

## 🔍 可能的问题

### 1. 前端TypeScript类型错误

检查浏览器控制台是否有错误：
- 按 F12 打开开发者工具
- 查看 Console 标签页
- 查看是否有红色错误信息

### 2. API调用失败

检查网络请求：
- 按 F12 打开开发者工具
- 切换到 Network 标签页
- 刷新页面
- 查看是否有失败的请求（红色）

### 3. 数据库表不存在

如果后端返回500错误，可能是数据库表未创建。

## 🛠️ 解决方案

### 方案1: 初始化数据库

```bash
cd backend
python scripts/init_db.py
```

### 方案2: 手动创建表

在 backend 目录创建脚本：

```python
import asyncio
from app.core.database import engine, Base
from app.models.schedule import Schedule, TaskExecution

async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created successfully")

asyncio.run(create_tables())
```

### 方案3: 检查前端错误

打开浏览器控制台，查看具体错误信息。

## 📋 检查清单

- [ ] 后端服务正在运行（http://localhost:8001）
- [ ] 数据库表已创建
- [ ] 前端无TypeScript错误
- [ ] API请求正常返回
- [ ] 浏览器控制台无错误

## 🚀 快速测试

访问后端API测试：
```
GET http://localhost:8001/api/v1/schedules
```

如果返回数据，说明后端正常，问题在前端。
如果返回错误，说明后端有问题。

---

**请提供浏览器控制台的错误信息，我可以帮你进一步诊断。**