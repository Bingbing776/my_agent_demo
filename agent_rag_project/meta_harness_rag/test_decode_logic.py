#!/usr/bin/env python3
"""测试双重转义解码逻辑"""
import codecs

def decode_escaped_code(test_source: str) -> str:
    """模拟修复后的解码逻辑"""
    max_decode_attempts = 3
    for _ in range(max_decode_attempts):
        if r'\n' in test_source or r'\t' in test_source or r'\u' in test_source:
            try:
                decoded = codecs.decode(test_source, 'unicode_escape')
                if decoded == test_source:
                    break
                test_source = decoded
            except Exception:
                break
        else:
            break
    return test_source


# 测试用例 1：双重转义（文件中的实际情况）
print("=" * 60)
print("Test 1: Double-escaped string (actual file content)")
print("=" * 60)
double_escaped = r'def __init__(\\n        self,\\n        config=None,\\n    ):\\n        # 1. \\u521d\\u59cb\\u5316\\u77ed\\u671f\\u8bb0\\u5fc6\\u5217\\u8868\\n        self.short_term = []'
print("Input (first 100 chars):")
print(repr(double_escaped[:100]))
print()

result = decode_escaped_code(double_escaped)
print("Output (first 100 chars):")
print(repr(result[:100]))
print()
print("Actual output:")
print(result)
print()

# 验证
if '\n' in result and r'\n' not in result:
    print("[PASS] Newlines correctly decoded")
else:
    print("[FAIL] Newlines NOT correctly decoded")

if '初始化' in result:
    print("[PASS] Chinese characters correctly decoded")
else:
    print("[FAIL] Chinese characters NOT correctly decoded")

print()

# 测试用例 2：正常字符串（不需要解码）
print("=" * 60)
print("Test 2: Normal string (no escaping)")
print("=" * 60)
normal = """def __init__(
        self,
        config=None,
    ):
        # 初始化
        self.short_term = []"""
print("Input (first 50 chars):")
print(repr(normal[:50]))
print()

result2 = decode_escaped_code(normal)
print("Output (first 50 chars):")
print(repr(result2[:50]))
print()

if result2 == normal:
    print("[PASS] Normal string unchanged")
else:
    print("[FAIL] Normal string was modified")
