#!/usr/bin/env python3
"""直接打印 MCP 工具的完整输出"""
# python test/test_mcp_raw.py
#!/usr/bin/env python3
"""最简单可靠的测试：直接打印 MCP 输出"""

import asyncio
import json
import sys
import os
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)  # 确保工作目录正确

async def main():
    # 延迟导入，确保路径已设置
    from src.core.response.response_builder import ResponseBuilder
    from src.core.types import RetrievalResult
    
    print("🔧 构建模拟响应...\n")
    
    # 1. 创建 builder（-1 = 不截断，测试全文）
    builder = ResponseBuilder(snippet_max_length=-1)
    
    # 2. 模拟检索结果
    mock_results = [
        RetrievalResult(
            chunk_id="doc_001_chunk_003",
            score=0.95,
            text="Azure OpenAI 配置步骤：1. 登录 Azure 门户 2. 创建 OpenAI 资源 3. 获取 API 密钥和 endpoint 4. 在代码中配置使用",
            metadata={"source_path": "docs/azure-guide.pdf", "title": "配置指南", "page": 3}
        )
    ]
    
    # 3. 构建响应
    response = builder.build(results=mock_results, query="Azure 配置", collection="test")
    
    # 4. 模拟 handler 返回逻辑
    content_blocks = response.to_mcp_content()
    structured_data = response.to_dict()["structuredContent"]  # ← 你要的字段！
    
    # 5. 打印完整 MCP 输出
    output = {
        "content": [
            {"type": b.type, "text": b.text} if hasattr(b, "text")
            else {"type": b.type}
            for b in content_blocks
        ],
        "structuredContent": structured_data,  # ← 直接包含
        "isError": False
    }
    
    print("=== 📦 完整 MCP 输出 ===\n")
    print(json.dumps(output, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
