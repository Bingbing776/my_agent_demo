import sys
from pathlib import Path
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _PROJECT_ROOT)
from src.libs.loader.pdf_loader import PdfLoader

pdf_path = str(Path(_PROJECT_ROOT) / "data/documents/acl_2023_2026/data/pdfs/2024.acl-srw.34.pdf")

loader = PdfLoader(extract_images=False)
doc = loader.load(pdf_path)

print("=" * 80)
print("PDF 提取的文本（前 2000 字符）:")
print("=" * 80)
print(doc.text[:2000])
print("\n" + "=" * 80)
print("检查双栏布局:")
print("- 如果看到左右栏文字交替 → 说明双栏未被正确处理 ❌")
print("- 如果看到连续段落 → 说明处理得不错 ✅")
print("=" * 80)
