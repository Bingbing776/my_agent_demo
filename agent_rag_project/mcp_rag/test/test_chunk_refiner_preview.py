# 查看 ChunkRefiner 去噪后的结果：
# 只看 rule-based：在 settings.yaml 里设置 ingestion.chunk_refiner.use_llm: false
# 看 LLM refine：在 settings.yaml 里设置 ingestion.chunk_refiner.use_llm: true
#
# 运行示例：
# python test/test_chunk_refiner_preview.py --pdf "data/documents/acl_2023_2026\data\pdfs\2024.acl-demos.4.pdf" --all

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.settings import load_settings
from src.libs.loader.pdf_loader import PdfLoader
from src.ingestion.chunking.document_chunker import DocumentChunker
from src.ingestion.transform.chunk_refiner import ChunkRefiner


def section(title: str, content: str) -> str:
    return f"\n\n{'=' * 80}\n{title}\n{'=' * 80}\n{content}\n"


def build_chunk_report(
    refiner: ChunkRefiner,
    chunk,
    chunk_index: int,
    use_llm: bool,
) -> tuple[str, str, str]:
    """Build before/after preview for one chunk.

    Returns:
        report: Markdown report text
        refined_by: "rule" or "llm"
        final_text: final text used after refinement
    """

    original_text = chunk.text

    # 1. rule-based refine
    rule_text = refiner._rule_based_refine(original_text)

    # 2. optional LLM refine
    llm_text = None

    if use_llm:
        print(f"Calling LLM refinement for chunk {chunk_index}...")
        llm_text = refiner._llm_refine(rule_text)

    final_text = llm_text if llm_text else rule_text
    refined_by = "llm" if llm_text else "rule"

    report = ""
    report += f"\n\n# Chunk {chunk_index}\n\n"
    report += f"- Chunk ID: `{chunk.id}`\n"
    report += f"- refined_by: `{refined_by}`\n"
    report += f"- original length: `{len(original_text)}`\n"
    report += f"- rule length: `{len(rule_text)}`\n"
    report += f"- final length: `{len(final_text)}`\n"

    report += section("ORIGINAL CHUNK", original_text)
    report += section("RULE-BASED REFINED CHUNK", rule_text)

    if llm_text:
        report += section("LLM REFINED CHUNK", llm_text)
    else:
        report += section("LLM REFINED CHUNK", "LLM 未启用，或 LLM 没有返回结果。")

    report += section("FINAL CHUNK USED", final_text)

    return report, refined_by, final_text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, help="PDF path")
    parser.add_argument("--chunk", type=int, default=0, help="Chunk index, starts from 0")
    parser.add_argument("--all", action="store_true", help="Preview all chunks")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--out", default="data/debug/chunk_refiner_preview.md")
    args = parser.parse_args()

    settings = load_settings(args.config)

    print("settings path =", args.config)
    print("settings.ingestion =", settings.ingestion)
    print("has include_references =", hasattr(settings.ingestion, "include_references"))
    print("has include_appendix =", hasattr(settings.ingestion, "include_appendix"))
    print("settings include_references =", getattr(settings.ingestion, "include_references", "MISSING"))
    print("settings include_appendix =", getattr(settings.ingestion, "include_appendix", "MISSING"))

    # 1. load PDF
    loader = PdfLoader(extract_images=True)
    doc = loader.load(args.pdf)

    # 2. split into chunks
    chunker = DocumentChunker(settings)
    chunks = chunker.split_document(doc)
    # print(chunks)
    if not chunks:
        print("No chunks generated.")
        return

    # 3. init refiner
    refiner = ChunkRefiner(settings)

    # 完全尊重 settings.yaml 里的 ingestion.chunk_refiner.use_llm
    use_llm = bool(refiner.use_llm and refiner.llm)

    print(f"PDF: {Path(args.pdf).name}")
    print(f"Total chunks: {len(chunks)}")
    print(f"settings use_llm: {refiner.use_llm}")
    print(f"actual_llm_available: {use_llm}")

    # 4. choose chunks
    if args.all:
        target_chunks = list(enumerate(chunks))
    else:
        if args.chunk < 0 or args.chunk >= len(chunks):
            raise ValueError(
                f"chunk index out of range: {args.chunk}, total chunks: {len(chunks)}"
            )
        target_chunks = [(args.chunk, chunks[args.chunk])]

    # 5. build report
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    report = ""
    report += "# Chunk Refiner Preview\n\n"
    report += f"- PDF: `{args.pdf}`\n"
    report += f"- Total chunks: `{len(chunks)}`\n"
    report += f"- Preview mode: `{'all' if args.all else 'single'}`\n"
    report += f"- settings use_llm: `{refiner.use_llm}`\n"
    report += f"- actual_llm_available: `{use_llm}`\n"

    refined_by_counts = {
        "rule": 0,
        "llm": 0,
    }

    last_final_text = ""

    for idx, chunk in target_chunks:
        chunk_report, refined_by, final_text = build_chunk_report(
            refiner=refiner,
            chunk=chunk,
            chunk_index=idx,
            use_llm=use_llm,
        )

        report += chunk_report
        refined_by_counts[refined_by] = refined_by_counts.get(refined_by, 0) + 1
        last_final_text = final_text

    report += "\n\n# Summary\n\n"
    report += f"- Exported chunks: `{len(target_chunks)}`\n"
    report += f"- Rule refined: `{refined_by_counts.get('rule', 0)}`\n"
    report += f"- LLM refined: `{refined_by_counts.get('llm', 0)}`\n"

    out_path.write_text(report, encoding="utf-8")

    print(f"\nPreview saved to: {out_path.resolve()}")

    if args.all:
        print(f"Exported all {len(chunks)} chunks.")
        print(f"Rule refined: {refined_by_counts.get('rule', 0)}")
        print(f"LLM refined: {refined_by_counts.get('llm', 0)}")
    else:
        print(f"Exported chunk {args.chunk}.")
        print("\nFinal refined preview:")
        print("-" * 80)
        print(last_final_text[:1000])


if __name__ == "__main__":
    main()