import sys, json, httpx, time, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
#测试batch_processor对于千问embedding模型具体能接受多少batch python test/test_batch_size.py
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

# ============ 真实文本块（从你的日志中提取的样例） ============
SAMPLE_CHUNKS = [
    "Homophone2Vec: Embedding Space Analysis for Empirical Evaluation of Phonological and Semantic Similarity",
    "This paper introduces a novel method for empirically evaluating the relationship between the phonological and semantic similarity of linguistic units using embedding spaces.",
    "Chinese character homophones are used as a proof-of-concept. We employ cosine similarity as a proxy for semantic similarity between characters.",
    "We show there is a strongly statistically significant positive semantic relationship among different Chinese characters at varying levels of sound-sharing.",
    "Homophones–linguistic units with the same sound but different meanings–evidently produce semantic ambiguity within language.",
    "Fieldwork in these languages have also shown that homophones with different syntactic contexts and semantic meanings are easier for children to memorize.",
    "Word embeddings transform linguistic units into numerical vectors within a continuous vector space.",
    "In Chinese natural language processing, these spaces have been trained successfully to evaluate semantic hierarchies and word similarity.",
    "We use a pre-trained model that produces competitive results on the task of Chinese word segmentation by combining radical information within a dual LSTM network.",
    "To extract groupings of homophones from the characters present in our embeddings, we used the pypinyin package which converts characters to pinyin."
]

def call_api(texts: list, label: str) -> dict:
    """发送请求并返回结果统计"""
    payload = {
        "model": MODEL,
        "input": texts,
        "dimensions": DIMENSIONS
    }
    
    start = time.time()
    try:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            resp = client.post(BASE_URL, json=payload, headers=HEADERS)
            elapsed = time.time() - start
            
            result = {
                "label": label,
                "batch_size": len(texts),
                "total_chars": sum(len(t) for t in texts),
                "status": resp.status_code,
                "elapsed": elapsed,
                "error": None,
                "vectors": 0,
                "dim": 0
            }
            
            if resp.status_code == 200:
                data = resp.json()
                result["vectors"] = len(data.get("data", []))
                if result["vectors"] > 0:
                    result["dim"] = len(data["data"][0].get("embedding", []))
            else:
                try:
                    err = resp.json()
                    result["error"] = err.get("error", {}).get("message", str(err))
                except:
                    result["error"] = resp.text[:200]
            
            return result
            
    except Exception as e:
        return {
            "label": label,
            "batch_size": len(texts),
            "status": "ERROR",
            "elapsed": time.time() - start,
            "error": f"{type(e).__name__}: {str(e)[:200]}",
            "vectors": 0,
            "dim": 0
        }

# ============ 执行测试 ============
print("🔍 Batch Size 压力测试 - DashScope Embedding API")
print(f"配置: model={MODEL}, dimensions={DIMENSIONS}")
print(f"样本: {len(SAMPLE_CHUNKS)} 个文本块，平均长度: {sum(len(c) for c in SAMPLE_CHUNKS)//len(SAMPLE_CHUNKS)} 字符")
print()

batch_sizes = [1, 5, 10, 20, 50, 100]
results = []

for bs in batch_sizes:
    # 构造测试输入：重复采样直到达到目标 batch size
    texts = []
    while len(texts) < bs:
        texts.extend(SAMPLE_CHUNKS)
    texts = texts[:bs]
    
    label = f"batch_size={bs}"
    print(f"🧪 测试 {label} ...", end=" ", flush=True)
    
    result = call_api(texts, label)
    results.append(result)
    
    # 打印简要结果
    if result["status"] == 200:
        status_emoji = "✅"
        status_text = f"OK ({result['vectors']} vectors, dim={result['dim']})"
    else:
        status_emoji = "❌"
        status_text = f"{result['status']} - {result['error'][:80]}"
    
    print(f"{status_emoji} {result['elapsed']:.2f}s | {result['total_chars']} chars | {status_text}")

# ============ 结果分析 ============
print(f"\n\n{'='*70}")
print("📊 测试结果分析")
print(f"{'='*70}")

# 找出最大成功的 batch size
successful = [r for r in results if r["status"] == 200 and r["vectors"] == r["batch_size"]]
failed = [r for r in results if r not in successful]

if successful:
    max_safe = max(successful, key=lambda x: x["batch_size"])
    print(f"✅ 最大安全 batch size: {max_safe['batch_size']}")
    print(f"   • 响应时间: {max_safe['elapsed']:.2f}s")
    print(f"   • 总字符数: {max_safe['total_chars']}")
else:
    print(f"❌ 所有测试都失败，可能配置有误")

if failed:
    print(f"\n⚠️  失败的测试:")
    for r in failed:
        print(f"   • batch_size={r['batch_size']}: {r['error'][:100]}")

# ============ 修复建议 ============
print(f"\n\n🔧 修复建议 (src/ingestion/embedding/batch_processor.py 或 dense_encoder.py):")

if successful:
    recommended = max(1, max_safe["batch_size"] // 2)  # 留 50% 余量
    print(f"""
# 当前可能:
BATCH_SIZE = 100

# 建议改为 (基于测试结果):
BATCH_SIZE = {recommended}  # 留余量避免边界问题

# 或者动态调整:
def get_optimal_batch_size(texts):
    # 估算总字符数，控制在安全范围内
    MAX_CHARS_PER_REQUEST = {max_safe['total_chars'] * 0.8:.0f}
    # ... 实现动态分批逻辑
""")
else:
    print("""
# 所有批处理都失败，先确认单条能成功:
# 1. 检查 settings.yaml: dimensions 是否在 [64,128,256,512,768,1024]
# 2. 确认模型名: text-embedding-v2 (更稳定) 或 text-embedding-v3
# 3. 临时测试单条:
BATCH_SIZE = 1
""")