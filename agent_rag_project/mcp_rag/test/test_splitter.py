# 测试chunk分块结果 python test/test_splitter.py
from pathlib import Path

def test_splitter_output(
    pdf_path: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    max_chunks: int = 30,
):
    """
    简单测试 RecursiveSplitter 的切分效果。
    """
    import sys
    import re
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))

    from src.libs.loader.pdf_loader import PdfLoader
    from src.libs.splitter.recursive_splitter import RecursiveSplitter
    from src.core.settings import load_settings

    # 1. 加载 PDF
    loader = PdfLoader(extract_images=True)
    doc = loader.load(pdf_path)

    print(f"\nPDF: {Path(pdf_path).name}")
    print(f"全文长度: {len(doc.text)} 字符")
    print(f"图片数量: {len(doc.metadata.get('images', []))}")
    print(f"IMAGE token 数量: {doc.text.count('[IMAGE:')}")
    print(f"omitted marker 数量: {doc.text.count('intentionally omitted')}")

    # 2. 初始化 splitter
    settings = load_settings()
    splitter = RecursiveSplitter( #这里的优先级更高，但是在正式跑的时候是直接导入setting里的配置的
        settings=settings,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        include_references=False,
        include_appendix=False
    )

    # 3. 切分
    chunks = splitter.split_text(doc.text)

    print(f"\nchunk_size={chunk_size}, overlap={chunk_overlap}")
    print(f"共切出 {len(chunks)} 个 chunks\n")

    # 4. 打印 chunk
    formula_pattern = re.compile(r"\[FORMULA|Type:\s*raw_formula")

    for i, chunk in enumerate(chunks[:max_chunks], start=1):
        tags = []

        if chunk.strip().startswith("#"):
            tags.append("标题")
        if "[IMAGE:" in chunk:
            tags.append("图片")
        if formula_pattern.search(chunk):
            tags.append("公式")
        if "Table " in chunk or "[TABLE" in chunk:
            tags.append("表格")

        tag_text = f" | {' / '.join(tags)}" if tags else ""

        print("=" * 80)
        print(f"[{i}] {len(chunk)} 字符{tag_text}")
        print("-" * 80)
        print(chunk.strip())

    if len(chunks) > max_chunks:
        print("=" * 80)
        print(f"还有 {len(chunks) - max_chunks} 个 chunks 未显示")

    return chunks

if __name__ == "__main__":
    chunks = test_splitter_output(
        pdf_path=str(Path(__file__).resolve().parent.parent / "data/documents/acl_2023_2026/data/pdfs/2024.acl-demos.4.pdf"),
        chunk_size=1000,
        chunk_overlap=200,
        max_chunks=60,
    )