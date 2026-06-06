"""使用示例 - README

## 三个示例文件

1. **example_usage.py** - 完整示例（带详细日志）
2. **example_quick.py** - 快速开始（最简单）
3. **example_multi_turn.py** - 多轮对话示例

## 使用方法

### 方式 1：直接调用（推荐用于脚本/测试）

```bash
cd agent_rag
python -c "
import asyncio
from agent_rag.orchestrator.rag_orchestrator import RagOrchestrator
from src.libs.llm.llm_factory import LLMFactory
from src.core.settings import load_settings

async def ask(question):
    settings = load_settings('config/settings.yaml')
    llm = LLMFactory.create(settings)
    
    orch = RagOrchestrator(config={})
    orch._planner._llm = llm
    orch._evaluator._llm = llm
    orch._generator._llm = llm
    orch._llm = llm
    
    result = await orch.answer(question)
    print(result['text'])
    return result

asyncio.run(ask('TOPMOST 是什么？'))
"
```

### 方式 2：在 Python 代码中使用

```python
import asyncio
from pathlib import Path
from agent_rag.orchestrator.rag_orchestrator import RagOrchestrator
from src.libs.llm.llm_factory import LLMFactory
from src.core.settings import load_settings

async def main():
    # 1. 加载配置和创建 LLM
    settings = load_settings(Path("config/settings.yaml"))
    llm = LLMFactory.create(settings)
    
    # 2. 创建 Orchestrator
    orchestrator = RagOrchestrator(config={})
    
    # 3. 注入 LLM
    orchestrator._planner._llm = llm
    orchestrator._evaluator._llm = llm
    orchestrator._generator._llm = llm
    orchestrator._llm = llm
    
    # 4. 提问
    result = await orchestrator.answer("你的问题")
    
    # 5. 使用结果
    print("回答:", result["text"])
    print("图片:", len(result.get("images", [])), "张")

if __name__ == "__main__":
    asyncio.run(main())
```

## 核心 API

### RagOrchestrator.answer()

```python
async def answer(
    self,
    query: str,           # 用户问题
    session_id: str = ""  # 可选：会话 ID（用于多轮对话）
) -> dict:
    """
    返回:
    {
        "text": str,       # 最终答案（Markdown 格式）
        "images": [        # 可选：图片列表
            {
                "mime_type": "image/png",
                "data": "base64...",
                "caption": "图片说明",
                "source": "来源",
                "tool_name": "工具名"
            }
        ]
    }
    """
```

## 配置说明

配置文件位置: `config/settings.yaml`

关键配置项:
```yaml
llm:
  provider: dashscope      # LLM 提供商
  model: qwen-max         # 模型名称
  api_key: sk-xxx         # API Key
  base_url: ...           # API 地址

embedding:
  model_name: bge-large-zh # 向量模型
  
vector_store:
  type: chroma            # 向量数据库类型
  path: ./chroma_db       # 存储路径
```

## 工作流程

1. **Planner** - 分析问题，规划子任务
2. **MCP Tools** - 调用外部工具检索信息（文档检索、知识库查询等）
3. **Evaluator** - 评估检索结果是否充分
4. **Generator** - 生成最终答案
5. **Memory** - 保存对话历史到三层记忆
6. **Context** - 更新上下文窗口

## 注意事项

1. 确保 `config/settings.yaml` 中配置了有效的 API Key
2. MCP Server 会自动启动（通过 stdio 子进程）
3. 第一次运行会初始化向量数据库（可能需要几分钟）
4. 建议使用 Python 3.9+

## 故障排除

### 问题：卡住不返回
- 检查 API Key 是否有效
- 检查网络连接
- 查看 `config/settings.yaml` 配置是否正确

### 问题：MCP 连接失败
- 确保 `../mcp_rag` 目录存在
- 确保 Python 环境包含所有依赖

### 问题：内存不足
- 减少 `short_term_capacity` 配置项
- 减少 `top_k_*` 配置项
"""
