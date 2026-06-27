# GLM 5.2 模型配置指南

## 配置方式

### 方式1: 环境变量配置（推荐）

在 `backend/.env` 文件中添加：

```bash
# LLM提供商设置为glm
LLM_PROVIDER=glm

# GLM API密钥（从智谱AI开放平台获取）
OPENAI_API_KEY=your_glm_api_key_here

# GLM模型名称
OPENAI_MODEL=glm-4-plus

# 可选：嵌入模型
OPENAI_EMBEDDING_MODEL=embedding-2
```

---

### 方式2: 代码中配置

修改 `backend/app/core/config.py`：

```python
# LLM配置
LLM_PROVIDER: str = "glm"
OPENAI_API_KEY: str = "your_glm_api_key_here"
OPENAI_MODEL: str = "glm-4-plus"
OPENAI_EMBEDDING_MODEL: str = "embedding-2"
```

---

### 方式3: 运行时动态配置

通过API动态配置：

```python
from app.services.llm import llm_manager

await llm_manager.reinitialize(
    provider="glm",
    api_key="your_glm_api_key",
    model="glm-4-plus"
)
```

---

## GLM模型列表

### GLM-4系列

| 模型名称 | 说明 | 上下文长度 |
|---------|------|-----------|
| glm-4-plus | GLM-4增强版（推荐） | 128K |
| glm-4-0520 | GLM-4标准版 | 128K |
| glm-4-air | GLM-4轻量版 | 128K |
| glm-4-airx | GLM-4极速版 | 8K |
| glm-4-long | GLM-4长文本版 | 1M |

### GLM-3系列

| 模型名称 | 说明 |
|---------|------|
| glm-3-turbo | GLM-3快速版 |

### 嵌入模型

| 模型名称 | 说明 |
|---------|------|
| embedding-2 | 嵌入模型v2 |
| embedding-3 | 嵌入模型v3 |

---

## 获取API密钥

1. 访问 [智谱AI开放平台](https://open.bigmodel.cn/)
2. 注册/登录账号
3. 进入控制台
4. 创建API Key
5. 复制API Key到配置文件

---

## 完整配置示例

### backend/.env

```bash
# 应用配置
APP_NAME=DataCrab
APP_VERSION=1.0.0
DEBUG=True

# 数据库配置
DATABASE_URL=sqlite+aiosqlite:///./datacrab.db

# LLM配置 - GLM 5.2
LLM_PROVIDER=glm
OPENAI_API_KEY=your_glm_api_key_here
OPENAI_MODEL=glm-4-plus
OPENAI_EMBEDDING_MODEL=embedding-2

# 其他配置...
JWT_SECRET_KEY=your-secret-key
```

---

## 验证配置

### 测试脚本

```python
import asyncio
from app.services.llm import llm_manager

async def test_glm():
    # 初始化
    await llm_manager.initialize()
    
    # 测试对话
    response = await llm_manager.chat(
        prompt="你好，请介绍一下自己",
        temperature=0.7,
        max_tokens=100
    )
    
    print(f"Response: {response}")

asyncio.run(test_glm())
```

### 测试流式输出

```python
async def test_glm_stream():
    await llm_manager.initialize()
    
    async for chunk in llm_manager.chat_stream(
        prompt="讲一个故事",
        temperature=0.7,
        max_tokens=500
    ):
        print(chunk, end="", flush=True)

asyncio.run(test_glm_stream())
```

---

## API端点配置

GLM的API地址已内置：

```python
PROVIDER_BASE_URLS = {
    "glm": "https://open.bigmodel.cn/api/paas/v4",
}
```

无需手动配置 `OPENAI_API_BASE`。

---

## 常见问题

### 1. API密钥无效

**错误**: `AuthenticationError: Invalid API key`

**解决**:
- 检查API密钥是否正确
- 确认API密钥是否已激活
- 检查账户余额是否充足

### 2. 模型不可用

**错误**: `Model not found`

**解决**:
- 确认模型名称正确（如 `glm-4-plus`）
- 检查账户是否有权限使用该模型

### 3. 超时错误

**错误**: `Timeout error`

**解决**:
- 检查网络连接
- 增加 `timeout` 参数（默认180秒）

---

## 费用说明

### GLM-4-Plus 资费

- 输入：0.05元/千tokens
- 输出：0.05元/千tokens

### GLM-4-Air 资费

- 输入：0.001元/千tokens
- 输出：0.001元/千tokens

---

## 性能优化建议

1. **选择合适的模型**
   - 简单任务：`glm-4-air`（快速、便宜）
   - 复杂任务：`glm-4-plus`（效果更好）
   - 长文本：`glm-4-long`（支持1M上下文）

2. **调整参数**
   ```python
   # 精确任务
   temperature=0.3
   
   # 创意任务
   temperature=0.8
   
   # 控制长度
   max_tokens=500
   ```

3. **使用流式输出**
   - 提升用户体验
   - 减少等待时间

---

## 对比其他模型

| 特性 | GLM-4-Plus | GPT-4 | Qwen |
|------|-----------|-------|------|
| 中文能力 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 英文能力 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| 价格 | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ |
| 速度 | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |

---

## 快速开始

1. 获取API密钥
2. 配置环境变量
3. 重启后端服务
4. 开始使用！

```bash
# 重启后端
cd backend
python -m uvicorn app.main:app --reload --port 8001
```

---

## 技术支持

- 智谱AI文档: https://open.bigmodel.cn/dev/api
- DataCrab文档: 查看项目 README.md