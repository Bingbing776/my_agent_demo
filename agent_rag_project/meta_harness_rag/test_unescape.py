#!/usr/bin/env python3
"""测试转义字符串的解码"""
import codecs

# 模拟 LLM 返回的转义字符串
escaped_code = r'def __init__(\\n        self,\\n        long_term_collection=None,\\n        sqlite_conn=None,\\n        qdrant_collection=None,\\n        config: dict = None,\\n    ):\\n        # 1. \\u521d\\u59cb\\u5316\\u77ed\\u671f\\u8bb0\\u5fc6\\u5217\\u8868\\n        self.short_term: List[dict] = []\\n\\n        # 2. \\u63a5\\u6536\\u5916\\u90e8\\u4f20\\u5165\\u7684\\u5b58\\u50a8\\u5b9e\\u4f8b\\n        self.long_term_collection = long_term_collection'

print("=" * 60)
print("原始转义字符串（前 200 字符）:")
print("=" * 60)
print(escaped_code[:200])
print()

print("=" * 60)
print("解码后的代码:")
print("=" * 60)
try:
    decoded = codecs.decode(escaped_code, 'unicode_escape')
    print(decoded)
    print()
    print("[SUCCESS] Decoding successful!")

    # 验证换行符是否正确
    if "\n" in decoded and "\\n" not in decoded:
        print("[PASS] Newlines are correctly decoded")
    else:
        print("[FAIL] Newlines are NOT correctly decoded")

except Exception as e:
    print(f"[ERROR] Decoding failed: {e}")
