"""Ingestion Pipeline orchestrator for the Modular RAG MCP Server.

This module implements the main pipeline that orchestrates the complete
document ingestion flow:
    1. File Integrity Check (SHA256 skip check)
    2. Document Loading (PDF → Document)
    3. Chunking (Document → Chunks)
    4. Transform (Refine + Enrich + Caption)
    5. Encoding (Dense + Sparse vectors)
    6. Storage (VectorStore + BM25 Index + ImageStorage)

Design Principles:
- Config-Driven: All components configured via settings.yaml
- Observable: Logs progress and stage completion
- Graceful Degradation: LLM failures don't block pipeline
- Idempotent: SHA256-based skip for unchanged files
"""

from pathlib import Path
from typing import Callable, List, Optional, Dict, Any
import time

from src.core.settings import Settings, load_settings, resolve_path
from src.core.types import Document, Chunk
from src.core.trace.trace_context import TraceContext
from src.observability.logger import get_logger

# Libs layer imports
from src.libs.loader.file_integrity import SQLiteIntegrityChecker
from src.libs.loader.pdf_loader import PdfLoader
from src.libs.embedding.embedding_factory import EmbeddingFactory
from src.libs.vector_store.vector_store_factory import VectorStoreFactory

# Ingestion layer imports
from src.ingestion.chunking.document_chunker import DocumentChunker
from src.ingestion.transform.chunk_refiner import ChunkRefiner
from src.ingestion.transform.metadata_enricher import MetadataEnricher
from src.ingestion.transform.image_captioner import ImageCaptioner
from src.ingestion.embedding.dense_encoder import DenseEncoder
from src.ingestion.embedding.sparse_encoder import SparseEncoder
from src.ingestion.embedding.batch_processor import BatchProcessor
from src.ingestion.storage.bm25_indexer import BM25Indexer
from src.ingestion.storage.vector_upserter import VectorUpserter
from src.ingestion.storage.image_storage import ImageStorage

logger = get_logger(__name__)


class PipelineResult:
    """Result of pipeline execution with detailed statistics.
    
    Attributes:
        success: Whether pipeline completed successfully
        file_path: Path to the processed file
        doc_id: Document ID (SHA256 hash)
        chunk_count: Number of chunks generated
        image_count: Number of images processed
        vector_ids: List of vector IDs stored
        error: Error message if pipeline failed
        stages: Dict of stage names to their individual results包含阶段名称及其各自结果的字典
    """
    
    def __init__(
        self,
        success: bool,
        file_path: str,
        doc_id: Optional[str] = None,
        chunk_count: int = 0,
        image_count: int = 0,
        vector_ids: Optional[List[str]] = None,
        error: Optional[str] = None,
        stages: Optional[Dict[str, Any]] = None
    ):
        """初始化结果对象。它接收处理是否成功、文件路径、生成的块数量、错误信息等参数，并将它们存储起来。"""
        self.success = success
        self.file_path = file_path
        self.doc_id = doc_id
        self.chunk_count = chunk_count
        self.image_count = image_count
        self.vector_ids = vector_ids or []
        self.error = error
        self.stages = stages or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.
        将当前的结果对象转换成 Python 字典。这通常是为了方便将结果保存为 JSON 格式，用于日志记录或前端展示。"""
        return {
            "success": self.success,
            "file_path": self.file_path,
            "doc_id": self.doc_id,
            "chunk_count": self.chunk_count,
            "image_count": self.image_count,
            "vector_ids_count": len(self.vector_ids),
            "error": self.error,
            "stages": self.stages
        }


class IngestionPipeline:
    """Main pipeline orchestrator for document ingestion.
    这是代码的主体，它像一个“工厂经理”，负责协调所有步骤。
    This class coordinates all stages of the ingestion process:
    - File integrity checking for incremental processing
    - Document loading (PDF with image extraction)
    - Text chunking with configurable splitter
    - Chunk refinement (rule-based + LLM)
    - Metadata enrichment (rule-based + LLM)
    - Image captioning (Vision LLM)
    - Dense embedding (Azure text-embedding-ada-002)
    - Sparse encoding (BM25 term statistics)
    - Vector storage (ChromaDB)
    - BM25 index building
    
    Example:
        >>> from src.core.settings import load_settings
        >>> settings = load_settings("config/settings.yaml")
        >>> pipeline = IngestionPipeline(settings)
        >>> result = pipeline.run("documents/report.pdf", collection="contracts")
        >>> print(f"Processed {result.chunk_count} chunks")
    """
    
    def __init__(
        self,
        settings: Settings,
        collection: str = "default",
        force: bool = False
    ):
        """Initialize pipeline with all components.
        组装流水线。它读取配置文件，然后逐个初始化所有需要用到的组件（如文件检查器、PDF加载器、分块器、向量数据库连接等）。它确保所有“工人”都到位。
        Args:
            settings: Application settings from settings.yaml来自settings.yaml的应用程序设置
            collection: Collection name for organizing documents用于组织文档的集合名称
            force: If True, re-process even if file was previously processed如果为True，即使文件之前已处理过，也会重新处理
        """
        self.settings = settings
        self.collection = collection
        self.force = force
        
        # Initialize all components
        logger.info("Initializing Ingestion Pipeline components...")
        
        # Stage 1: File Integrity
        # 计算文件的 SHA256 哈希值。如果这个文件之前处理过（哈希值已存在），就直接跳过，避免重复劳动（除非强制重跑）。这是为了保证幂等性。
        self.integrity_checker = SQLiteIntegrityChecker(db_path=str(resolve_path("data/db/ingestion_history.db")))
        logger.info("  ✓ FileIntegrityChecker initialized")
        
        # Stage 2: Loader
        # 读取文件内容。专门处理 PDF 文件，提取纯文本内容，并把 PDF 里的图片保存到磁盘（data/images/ 目录下）。
        self.loader = PdfLoader(
            extract_images=True,
            image_storage_dir=str(resolve_path(f"data/images/{collection}"))
        )
        logger.info("  ✓ PdfLoader initialized")
        
        # Stage 3: Chunker
        # 切分文本。将长篇文档切成小块（Chunks）。这是 RAG 的关键步骤，因为大模型一次只能处理有限长度的文本。
        self.chunker = DocumentChunker(settings)
        logger.info("  ✓ DocumentChunker initialized")
        
        # Stage 4: Transforms 这是一个复合阶段，包含三个子步骤：
        # (精炼)：清理文本块，可能使用规则或 LLM（大语言模型）来优化文本格式。
        self.chunk_refiner = ChunkRefiner(settings)
        logger.info(f"  ✓ ChunkRefiner initialized (use_llm={self.chunk_refiner.use_llm})")
        # (元数据丰富)：给文本块添加额外信息，比如标签、摘要或来源，可能也用到 LLM。
        self.metadata_enricher = MetadataEnricher(settings)
        logger.info(f"  ✓ MetadataEnricher initialized (use_llm={self.metadata_enricher.use_llm})")
        # (图片描述)：如果文档中有图片，调用视觉模型（Vision LLM）给图片生成文字描述（Caption）
        self.image_captioner = ImageCaptioner(settings)
        has_vision = self.image_captioner.llm is not None
        logger.info(f"  ✓ ImageCaptioner initialized (vision_enabled={has_vision})")
        
        # Stage 5: Encoders 编码
        # 将文本转化为计算机能搜索的数字（向量）
        embedding = EmbeddingFactory.create(settings)  # 根据配置创建embedding实例
        batch_size = settings.ingestion.batch_size if settings.ingestion else 10
        self.dense_encoder = DenseEncoder(embedding, batch_size=batch_size)
        logger.info(f"  ✓ DenseEncoder initialized (provider={settings.embedding.provider})")
        
        self.sparse_encoder = SparseEncoder()
        logger.info("  ✓ SparseEncoder initialized")
        
        self.batch_processor = BatchProcessor(
            dense_encoder=self.dense_encoder,
            sparse_encoder=self.sparse_encoder,
            batch_size=batch_size
        )
        logger.info(f"  ✓ BatchProcessor initialized (batch_size={batch_size})")
        
        # Stage 6: Storage
        # 把处理好的数据存起来供后续检索。
        # 把稠密向量存入向量数据库（ChromaDB）
        self.vector_upserter = VectorUpserter(settings, collection_name=collection)
        logger.info(f"  ✓ VectorUpserter initialized (provider={settings.vector_store.provider}, collection={collection})")
        # 把稀疏向量信息存入 BM25 索引。
        self.bm25_indexer = BM25Indexer(index_dir=str(resolve_path(f"data/db/bm25/{collection}")))
        logger.info("  ✓ BM25Indexer initialized")
        # 记录图片的存储位置和关联信息。
        self.image_storage = ImageStorage(
            db_path=str(resolve_path("data/db/image_index.db")),
            images_root=str(resolve_path("data/images"))
        )
        logger.info("  ✓ ImageStorage initialized")
        
        logger.info("Pipeline initialization complete!")
    
    def run(
        self,
        file_path: str,
        trace: Optional[TraceContext] = None,
        on_progress: Optional[Callable[[str, int, int], None]] = None,
    ) -> PipelineResult:
        """Execute the full ingestion pipeline on a file.
        
        Args:
            file_path: Path to the file to process (e.g., PDF)
            trace: Optional trace context for observability
            on_progress: Optional callback ``(stage_name, current, total)``
                invoked when each pipeline stage completes.  *current* is
                the 1-based index of the completed stage; *total* is the
                number of stages (currently 6).
        
        Returns:
            PipelineResult with success status and statistics
        """
        file_path = Path(file_path)
        stages: Dict[str, Any] = {}
        _total_stages = 6

        # 这是一个内部（私有）函数，用于在每个阶段完成后，向外部发送进度通知（比如告诉前端“现在完成了第3步”）
        def _notify(stage_name: str, step: int) -> None:
            if on_progress is not None:
                on_progress(stage_name, step, _total_stages)
        
        logger.info(f"=" * 60)
        logger.info(f"Starting Ingestion Pipeline for: {file_path}")
        logger.info(f"Collection: {self.collection}")
        logger.info(f"=" * 60)
        
        try:
            # ─────────────────────────────────────────────────────────────
            # Stage 1: File Integrity Check文件完整性检查 
            # ─────────────────────────────────────────────────────────────
            logger.info("\n📋 Stage 1: File Integrity Check")
            _notify("integrity", 1)
            
            file_hash = self.integrity_checker.compute_sha256(str(file_path))
            logger.info(f"  File hash: {file_hash[:16]}...")
            
            if not self.force and self.integrity_checker.should_skip(file_hash):
                logger.info(f"  ⏭️  File already processed, skipping (use force=True to reprocess)")
                return PipelineResult(
                    success=True,
                    file_path=str(file_path),
                    doc_id=file_hash,
                    stages={"integrity": {"skipped": True, "reason": "already_processed"}}
                )
            
            stages["integrity"] = {"file_hash": file_hash, "skipped": False}
            logger.info("  ✓ File needs processing")
            
            # ─────────────────────────────────────────────────────────────
            # Stage 2: Document Loading 读取文件内容。
            # ─────────────────────────────────────────────────────────────
            logger.info("\n📄 Stage 2: Document Loading")
            _notify("load", 2)
            
            _t0 = time.monotonic()
            document = self.loader.load(str(file_path))
            _elapsed = (time.monotonic() - _t0) * 1000.0
            
            text_preview = document.text[:200].replace('\n', ' ') + "..." if len(document.text) > 200 else document.text
            image_count = len(document.metadata.get("images", []))
            
            logger.info(f"  Document ID: {document.id}")
            logger.info(f"  Text length: {len(document.text)} chars")
            logger.info(f"  Images extracted: {image_count}")
            logger.info(f"  Preview: {text_preview[:100]}...")
            
            stages["loading"] = {
                "success": True,
                "doc_id": document.id,
                "text_length": len(document.text),
                "image_count": image_count
            }
            # 这行代码调用了 trace 对象（追踪器）的 record_stage 方法，用来保存“加载文档”这一阶段的详细性能指标和数据快照。
            if trace is not None:
                trace.record_stage("load", {
                    "method": "markitdown", # 记录使用了什么工具。这里说明是用 markitdown 这个库来解析文件的
                    "doc_id": document.id, # 记录处理的是哪个文件。通过 ID 可以唯一锁定当前文档。
                    "text_length": len(document.text), # 记录提取了多少字。这是为了检查文件是否被正确读取（如果长度为 0，说明出错了）
                    "image_count": image_count,#  记录提取了多少张图片。
                    "text_preview": document.text, # 记录文本预览。这里直接把提取出来的文本内容存了进去，方便后续调试查看提取的内容是否正确。
                }, elapsed_ms=_elapsed) # _elapsed 变量里存的是这一阶段运行了多少毫秒。
            
            # ─────────────────────────────────────────────────────────────
            # Stage 3: Chunking
            # ─────────────────────────────────────────────────────────────
            logger.info("\n✂️  Stage 3: Document Chunking")
            _notify("split", 3)
            
            _t0 = time.monotonic()
            chunks = self.chunker.split_document(document)
            _elapsed = (time.monotonic() - _t0) * 1000.0
            
            logger.info(f"  Chunks generated: {len(chunks)}")
            if chunks:
                logger.info(f"  First chunk ID: {chunks[0].id}")
                logger.info(f"  First chunk preview: {chunks[0].text[:100]}...")
            
            stages["chunking"] = {
                "chunk_count": len(chunks),
                "avg_chunk_size": sum(len(c.text) for c in chunks) // len(chunks) if chunks else 0
            }
            if trace is not None:
                trace.record_stage("split", {
                    "method": "recursive",
                    "chunk_count": len(chunks),
                    "avg_chunk_size": sum(len(c.text) for c in chunks) // len(chunks) if chunks else 0,
                    "chunks": [
                        {
                            "chunk_id": c.id,
                            "text": c.text,
                            "char_len": len(c.text),
                            "chunk_index": c.metadata.get("chunk_index", i),
                        }
                        for i, c in enumerate(chunks)
                    ],
                }, elapsed_ms=_elapsed)
            
            # ─────────────────────────────────────────────────────────────
            # Stage 4: Transform Pipeline 转换与增强
            # ─────────────────────────────────────────────────────────────
            logger.info("\n🔄 Stage 4: Transform Pipeline")
            _notify("transform", 4)
            
            # 4a: Chunk Refinement 原始切分出来的文本块可能是不完整的（比如一句话被切断了），或者充满了无用的符号。这个步骤会利用规则（比如补全标点）或者LLM（大语言模型）来重写或修复这些文本块，使其语义完整。
            logger.info("  4a. Chunk Refinement...")
            _t0_transform = time.monotonic()
            # snapshot before refinement
            _pre_refine_texts = {c.id: c.text for c in chunks}
            chunks = self.chunk_refiner.transform(chunks, trace)
            refined_by_llm = sum(1 for c in chunks if c.metadata.get("refined_by") == "llm")  # 统计有多少块是 AI 修的
            refined_by_rule = sum(1 for c in chunks if c.metadata.get("refined_by") == "rule")  # 有多少是规则修的
            logger.info(f"      LLM refined: {refined_by_llm}, Rule refined: {refined_by_rule}")
            
            # 4b: Metadata Enrichment
            # 光有正文是不够的，系统还需要知道这个段落的标题是什么、属于哪个章节、有哪些关键词。这个步骤会自动提取这些信息，并塞进文本块的 metadata 里。
            logger.info("  4b. Metadata Enrichment...")
            chunks = self.metadata_enricher.transform(chunks, trace)
            enriched_by_llm = sum(1 for c in chunks if c.metadata.get("enriched_by") == "llm")  # 统计有多少个文本块是由 LLM 处理的
            enriched_by_rule = sum(1 for c in chunks if c.metadata.get("enriched_by") == "rule")  # 统计有多少个文本块是由预设规则处理的。
            logger.info(f"      LLM enriched: {enriched_by_llm}, Rule enriched: {enriched_by_rule}")
            
            # 4c: Image Captioning
            logger.info("  4c. Image Captioning...")
            chunks = self.image_captioner.transform(chunks, trace)
            captioned = sum(1 for c in chunks if c.metadata.get("image_captions")) # 统计成功生成描述的图片数量
            logger.info(f"      Chunks with captions: {captioned}")
            
            stages["transform"] = {
                "chunk_refiner": {"llm": refined_by_llm, "rule": refined_by_rule},
                "metadata_enricher": {"llm": enriched_by_llm, "rule": enriched_by_rule},
                "image_captioner": {"captioned_chunks": captioned}
            }
            _elapsed_transform = (time.monotonic() - _t0_transform) * 1000.0
            if trace is not None:
                trace.record_stage("transform", {
                    "method": "refine+enrich+caption",
                    "refined_by_llm": refined_by_llm,
                    "refined_by_rule": refined_by_rule,
                    "enriched_by_llm": enriched_by_llm,
                    "enriched_by_rule": enriched_by_rule,
                    "captioned_chunks": captioned,
                    "chunks": [
                        {
                            "chunk_id": c.id,
                            "text_before": _pre_refine_texts.get(c.id, ""),
                            "text_after": c.text,
                            "char_len": len(c.text),
                            "refined_by": c.metadata.get("refined_by", ""),
                            "enriched_by": c.metadata.get("enriched_by", ""),
                            "title": c.metadata.get("title", ""),
                            "tags": c.metadata.get("tags", []),
                            "summary": c.metadata.get("summary", ""),
                        }
                        for c in chunks
                    ],
                }, elapsed_ms=_elapsed_transform)
            
            # ─────────────────────────────────────────────────────────────
            # Stage 5: Encoding
            # ─────────────────────────────────────────────────────────────
            logger.info("\n🔢 Stage 5: Encoding")
            _notify("embed", 5)
            
            # Process through BatchProcessor
            _t0 = time.monotonic()
            batch_result = self.batch_processor.process(chunks, trace)
            _elapsed = (time.monotonic() - _t0) * 1000.0
            
            dense_vectors = batch_result.dense_vectors
            sparse_stats = batch_result.sparse_stats
            
            logger.info(f"  Dense vectors: {len(dense_vectors)} (dim={len(dense_vectors[0]) if dense_vectors else 0})")
            logger.info(f"  Sparse stats: {len(sparse_stats)} documents")
            
            stages["encoding"] = {
                "dense_vector_count": len(dense_vectors),
                "dense_dimension": len(dense_vectors[0]) if dense_vectors else 0,
                "sparse_doc_count": len(sparse_stats)
            }
            if trace is not None:
                # Build per-chunk encoding details (both dense & sparse)
                chunk_details = []
                for idx, c in enumerate(chunks):
                    detail: dict = {
                        "chunk_id": c.id,
                        "char_len": len(c.text), # 检查文本是否被截断，或者是否为空
                    }
                    # Dense: vector dimension (same for all, but confirm per-chunk)
                    if idx < len(dense_vectors):
                        detail["dense_dim"] = len(dense_vectors[idx]) # 记录稠密向量的维度(每一个的维度)
                    # Sparse: BM25 term stats
                    if idx < len(sparse_stats):
                        ss = sparse_stats[idx]
                        detail["doc_length"] = ss.get("doc_length", 0) # 文本块包含多少个词（Token）
                        detail["unique_terms"] = ss.get("unique_terms", 0)  # 有多少个不重复的词
                        # Top-10 terms by frequency for inspection
                        tf = ss.get("term_frequencies", {})
                        top_terms = sorted(tf.items(), key=lambda x: x[1], reverse=True)[:10]
                        detail["top_terms"] = [{"term": t, "freq": f} for t, f in top_terms]  # 提取前 10 个出现频率最高的词
                    chunk_details.append(detail)

                trace.record_stage("embed", {
                    "method": "batch_processor", # 记录使用了什么方法。这里是用“批处理”模式来生成向量的（一次性处理多个，效率更高）
                    "dense_vector_count": len(dense_vectors),  # 一共生成了多少个稠密向量
                    "dense_dimension": len(dense_vectors[0]) if dense_vectors else 0, # 向量的维度大小，像是装箱单上的规格说明
                    "sparse_doc_count": len(sparse_stats),  # 生成了多少组关键词统计数据
                    "chunks": chunk_details,
                }, elapsed_ms=_elapsed)
            
            # ─────────────────────────────────────────────────────────────
            # Stage 6: Storage
            # ─────────────────────────────────────────────────────────────
            logger.info("\n💾 Stage 6: Storage")
            _notify("upsert", 6)
            
            # 6a: Vector Upsert
            logger.info("  6a. Vector Storage (ChromaDB)...")
            _t0_storage = time.monotonic()
            vector_ids = self.vector_upserter.upsert(chunks, dense_vectors, trace)
            logger.info(f"      Stored {len(vector_ids)} vectors")

            # Align BM25 chunk_ids with Chroma vector IDs so the SparseRetriever
            # can look up BM25 hits in the vector store after retrieval.
            for stat, vid in zip(sparse_stats, vector_ids):
                stat["chunk_id"] = vid # 这个是切片在数据库中的id

            # 6b: BM25 Index
            logger.info("  6b. BM25 Index...")
            self.bm25_indexer.add_documents(
                sparse_stats,
                collection=self.collection,
                doc_id=document.id,  # 这个是文档的id
                trace=trace,
            )
            logger.info(f"      Index built for {len(sparse_stats)} documents")
            
            # 6c: Register images in image storage index
            # Note: Images are already saved by PdfLoader, we just need to index them
            logger.info("  6c. Image Storage Index...")
            images = document.metadata.get("images", [])  # 一个照片的metadata存一条
            for img in images:
                img_path = Path(img["path"])
                if img_path.exists():
                    # 图片文件其实在第 2 阶段（加载）就已经保存到硬盘了。这里只是把图片的元数据（ID、路径、页码）记录到一个 JSON 索引文件里，方便以后通过页码或文档哈希值快速反查图片。
                    self.image_storage.register_image(
                        image_id=img["id"],
                        file_path=img_path,
                        collection=self.collection,
                        doc_hash=file_hash,
                        page_num=img.get("page", 0)
                    )
            logger.info(f"      Indexed {len(images)} images")
            
            stages["storage"] = {
                "vector_count": len(vector_ids),
                "bm25_docs": len(sparse_stats),
                "images_indexed": len(images)
            }
            _elapsed_storage = (time.monotonic() - _t0_storage) * 1000.0
            if trace is not None:
                # Per-chunk storage mapping: chunk_id → vector_id
                chunk_storage = [
                    {
                        "chunk_id": c.id,
                        "vector_id": vector_ids[i] if i < len(vector_ids) else "—",
                        "collection": self.collection,
                        "store": "ChromaDB",
                    }
                    for i, c in enumerate(chunks)
                ]
                # Image storage details
                image_storage_details = [
                    {
                        "image_id": img["id"],
                        "file_path": str(img["path"]),
                        "page": img.get("page", 0),
                        "doc_hash": file_hash,
                    }
                    for img in images
                ]
                trace.record_stage("upsert", {
                    "dense_store": {
                        "backend": "ChromaDB",
                        "collection": self.collection,
                        "count": len(vector_ids),
                        "path": "data/db/chroma/",
                    },
                    "sparse_store": {
                        "backend": "BM25",
                        "collection": self.collection,
                        "count": len(sparse_stats),
                        "path": f"data/db/bm25/{self.collection}/",
                    },
                    "image_store": {
                        "backend": "ImageStorage (JSON index)",
                        "count": len(images),
                        "images": image_storage_details,
                    },
                    "chunk_mapping": chunk_storage,
                }, elapsed_ms=_elapsed_storage)
            
            # ─────────────────────────────────────────────────────────────
            # Mark Success
            # ─────────────────────────────────────────────────────────────
            self.integrity_checker.mark_success(file_hash, str(file_path), self.collection)
            
            logger.info("\n" + "=" * 60)
            logger.info("✅ Pipeline completed successfully!")
            logger.info(f"   Chunks: {len(chunks)}")
            logger.info(f"   Vectors: {len(vector_ids)}")
            logger.info(f"   Images: {len(images)}")
            logger.info("=" * 60)
            
            return PipelineResult(
                success=True,
                file_path=str(file_path),
                doc_id=file_hash,
                chunk_count=len(chunks),
                image_count=len(images),
                vector_ids=vector_ids,
                stages=stages
            )
            
        except Exception as e:
            logger.error(f"❌ Pipeline failed: {e}", exc_info=True)

            if "loading" not in stages:
                stages["loading"] = {
                    "success": False,
                    "error": str(e),
                }

            self.integrity_checker.mark_failed(file_hash, str(file_path), str(e))
            
            return PipelineResult(
                success=False,
                file_path=str(file_path),
                doc_id=file_hash if 'file_hash' in locals() else None,
                error=str(e),
                stages=stages
            )
    # 收尾工作。在处理完文件后，调用这个方法来关闭数据库连接（如图片存储索引），防止资源泄露。
    def close(self) -> None:
        """Clean up resources."""
        self.image_storage.close()


def run_pipeline(
    file_path: str,
    settings_path: Optional[str] = None,
    collection: str = "default",
    force: bool = False
) -> PipelineResult:
    """Convenience function to run the pipeline.
    这个函数位于类的外面，它的作用是简化调用。
    作用：提供一个简单的接口。你只需要传入文件路径和配置路径，它就会自动完成“加载配置 -> 创建流水线 -> 运行流水线 -> 关闭资源”的全过程，非常适合在脚本或 API 中直接调用。
    
    Args:
        file_path: Path to file to process
        settings_path: Path to settings.yaml (default: <repo>/config/settings.yaml)
        collection: Collection name
        force: Force reprocessing
    
    Returns:
        PipelineResult with execution details
    """
    settings = load_settings(settings_path)
    pipeline = IngestionPipeline(settings, collection=collection, force=force)
    
    try:
        return pipeline.run(file_path)
    finally:
        pipeline.close()
