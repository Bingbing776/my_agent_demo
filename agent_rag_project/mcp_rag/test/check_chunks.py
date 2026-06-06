# 查看 ingestion pipeline 中的实际 load的结果 python test/check_chunks.py
import sys
from pathlib import Path
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _PROJECT_ROOT)
from src.libs.loader.pdf_loader import PdfLoader
from src.ingestion.pipeline import IngestionPipeline
from src.core.settings import load_settings

# 加载 PDF
loader = PdfLoader(extract_images=True)
doc = loader.load(str(Path(_PROJECT_ROOT) / "data/documents/acl_2023_2026/data/pdfs/2024.acl-demos.4.pdf"))

print("完整文本长度:", len(doc.text))

lines = doc.text.split('\n')
print(f"\n总行数: {len(lines)}")
print("前X行:")
for i, line in enumerate(lines[:300],1):
    print(f"{i:3d}. {line}")


