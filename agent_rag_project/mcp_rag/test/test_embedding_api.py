import httpx, json, sys
# 测试embedding llm调用是否成功 python test/test_embedding_api.py
# 你的配置
API_KEY = "YOUR_DASHSCOPE_API_KEY"
MODEL = "text-embedding-v3"
URL = "YOUR_EMBEDDING_API_URL"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}
payload = {
    "model": MODEL,
    "input": ["hello world"]
}

print(f"🔍 Testing DashScope Embedding API")
print(f"   URL: {URL}")
print(f"   Model: {MODEL}")
print(f"   Key prefix: {API_KEY[:10]}...")
print()

try:
    with httpx.Client(timeout=30) as client:
        resp = client.post(URL, json=payload, headers=headers)
        print(f"📡 HTTP Status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            vec = data["data"][0]["embedding"]
            print(f"✅ SUCCESS! Vector dimension: {len(vec)}")
        else:
            print(f"❌ Error response:")
            try:
                err = resp.json()
                print(json.dumps(err, indent=2, ensure_ascii=False))
            except:
                print(resp.text)
except Exception as e:
    print(f"❌ Exception: {type(e).__name__}: {e}")