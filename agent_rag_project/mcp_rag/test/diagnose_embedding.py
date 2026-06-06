import sys, json, httpx, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# 测试embedding部分出现了什么问题 python test/diagnose_embedding.py
from src.core.settings import load_settings

# ============ 配置 ============
settings = load_settings("config/settings.yaml")
cfg = settings.embedding

API_KEY = cfg.api_key
MODEL = cfg.model
DIMENSIONS = cfg.dimensions
BASE_URL = "YOUR_EMBEDDING_API_URL"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def test_call(payload: dict, label: str):
    """发送请求并打印详细结果"""
    print(f"\n{'='*60}")
    print(f"🧪 测试: {label}")
    print(f"{'='*60}")
    print(f"Payload: {json.dumps(payload, ensure_ascii=False, indent=2)[:500]}...")
    
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.post(BASE_URL, json=payload, headers=HEADERS)
            
            print(f"\n📡 HTTP {resp.status_code} {resp.reason_phrase}")
            print(f"🔗 URL: {resp.url}")
            print(f"⏱️ 耗时: {resp.elapsed.total_seconds():.2f}s")
            
            # 打印关键响应头
            for k in ['content-type', 'x-request-id', 'x-dashscope-call-gateway']:
                if k in resp.headers:
                    print(f"📦 {k}: {resp.headers[k]}")
            
            # 解析响应体
            try:
                data = resp.json()
                if resp.status_code == 200:
                    vec = data["data"][0]["embedding"]
                    print(f"\n✅ SUCCESS!")
                    print(f"   • Vector dim: {len(vec)}")
                    print(f"   • First 5 values: {vec[:5]}")
                    return True
                else:
                    print(f"\n❌ API Error:")
                    print(json.dumps(data, ensure_ascii=False, indent=2))
                    return False
            except json.JSONDecodeError:
                print(f"\n❌ Non-JSON response:")
                print(resp.text[:500])
                return False
                
    except httpx.RequestError as e:
        print(f"\n❌ Network Error: {type(e).__name__}")
        print(f"   {e}")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected Error: {type(e).__name__}: {e}")
        return False

# ============ 执行测试矩阵 ============
print("🔍 DashScope Embedding API 诊断")
print(f"配置: model={MODEL}, dimensions={DIMENSIONS}")
print(f"API Key: {API_KEY[:10]}...")

results = {}

# 测试 1: 最小输入 + 完整参数（复现项目行为）
results["T1: minimal + dims"] = test_call({
    "model": MODEL,
    "input": ["test"],
    "dimensions": DIMENSIONS
}, "最小输入 + dimensions 参数")

# 测试 2: 最小输入 + 不带 dimensions
results["T2: minimal no-dims"] = test_call({
    "model": MODEL,
    "input": ["test"]
}, "最小输入 + 无 dimensions")

# 测试 3: 不带 encoding_format（如果项目代码加了的话）
results["T3: no encoding_format"] = test_call({
    "model": MODEL,
    "input": ["test"],
    "dimensions": DIMENSIONS
    # 故意不加 encoding_format
}, "不带 encoding_format 参数")

# 测试 4: 模拟项目实际输入（单个短文本，非 58 个）
results["T4: single chunk"] = test_call({
    "model": MODEL,
    "input": ["Homophone2Vec: Embedding Space Analysis for Empirical Evaluation"],
    "dimensions": DIMENSIONS
}, "单个短文本块（模拟项目输入）")

# ============ 结果汇总 ============
print(f"\n\n{'='*60}")
print("📊 诊断结果汇总")
print(f"{'='*60}")

success_count = sum(1 for v in results.values() if v)
print(f"成功: {success_count}/{len(results)}")

if success_count == len(results):
    print("\n🎉 所有测试通过！问题可能在项目代码的其他地方")
    print("👉 建议: 检查 batch_processor.py 的批处理逻辑")
    
elif "T1: minimal + dims" not in results or not results["T1: minimal + dims"]:
    print("\n❌ 测试 1 失败（最小输入 + dimensions）→ 核心参数问题")
    print("👉 可能原因:")
    print("   • dimensions 值不在允许范围 [64,128,256,512,768,1024]")
    print("   • 模型名在兼容模式下不支持")
    print("👉 修复: 改用 text-embedding-v2 或确认 dimensions=1024")
    
elif "T2: minimal no-dims" in results and results["T2: minimal no-dims"]:
    print("\n⚠️  不带 dimensions 成功，带 dimensions 失败 → 参数传递问题")
    print("👉 可能: DashScope 兼容模式对 dimensions 参数支持不完善")
    print("👉 修复: 在 openai_embedding.py 中，对 v3 模型不传 dimensions 参数")
    
elif "T4: single chunk" not in results or not results["T4: single chunk"]:
    print("\n❌ 单个文本块也失败 → 可能是模型/密钥/网络问题")
    print("👉 检查: API Key 是否有效，模型是否已开通")