import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# 测试llm支持的输出维度 python test/check_dims.py
from src.core.settings import load_settings
import httpx

# 加载配置
settings = load_settings("config/settings.yaml")
cfg = settings.embedding

print("🔍 Embedding 维度校验")
print("=" * 50)
print(f"配置模型: {cfg.model}")
print(f"配置维度: {cfg.dimensions}")
print(f"API 端点: {cfg.base_url if hasattr(cfg, 'base_url') else 'dashscope'}")
print()

# 构造请求
url = "YOUR_EMBEDDING_API_URL"
headers = {
    "Authorization": f"Bearer {cfg.api_key}",
    "Content-Type": "application/json"
}
payload = {
    "model": cfg.model,
    "input": ["test"]
}
# 如果配置了 dimensions 且模型支持，带上这个参数
if cfg.dimensions and "text-embedding" in cfg.model:
    payload["dimensions"] = cfg.dimensions

print(f"📡 发送请求...")
try:
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, json=payload, headers=headers)
        
        if resp.status_code != 200:
            print(f"❌ HTTP {resp.status_code}: {resp.text}")
            sys.exit(1)
        
        data = resp.json()
        actual_vec = data["data"][0]["embedding"]
        actual_dim = len(actual_vec)
        
        print(f"✅ API 返回维度: {actual_dim}")
        print()
        
        # 对比分析
        if cfg.dimensions == actual_dim:
            print("🎉 维度匹配！配置正确 ✓")
        elif cfg.dimensions is None:
            print(f"⚠️  配置未指定 dimensions，API 返回 {actual_dim}")
            print(f"   建议: 在 settings.yaml 中添加 `dimensions: {actual_dim}`")
        else:
            print(f"❌ 维度不匹配！")
            print(f"   配置: {cfg.dimensions} | 实际: {actual_dim}")
            print()
            print("🔧 修复建议（二选一）:")
            print(f"   A. 改配置: dimensions: {actual_dim}  ← 推荐")
            print(f"   B. 改模型: 用支持 {cfg.dimensions} 维的模型")
            
            # 检查是否因为 model 名导致 dimensions 参数被忽略
            if "dimensions" in payload and not cfg.model.startswith("text-embedding-3"):
                print()
                print("⚠️  注意: 代码中可能因模型名不匹配，未发送 dimensions 参数")
                print("   检查 src/libs/embedding/openai_embedding.py 第 ~120 行:")
                print("   if model.startswith('text-embedding-3'):  ← 你的模型是 '{}'".format(cfg.model))
                
except Exception as e:
    print(f"❌ 异常: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()