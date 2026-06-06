# MCP Agent Tools Patch

Copy these files into:

```text
src/mcp_server/tools/
```

Tools included:

```text
read_chunk.py
get_neighbor_chunks.py
list_documents.py
search_by_metadata.py
get_document_outline.py
get_document_full_text.py
check_evidence.py
```

Register them in `src/mcp_server/protocol_handler.py`, inside your default tool registration function:

```python
from src.mcp_server.tools.read_chunk import register_tool as register_read_chunk_tool
register_read_chunk_tool(protocol_handler)

from src.mcp_server.tools.get_neighbor_chunks import register_tool as register_neighbor_chunks_tool
register_neighbor_chunks_tool(protocol_handler)

from src.mcp_server.tools.list_documents import register_tool as register_documents_tool
register_documents_tool(protocol_handler)

from src.mcp_server.tools.search_by_metadata import register_tool as register_filtered_search_tool
register_filtered_search_tool(protocol_handler)

from src.mcp_server.tools.get_document_outline import register_tool as register_document_outline_tool
register_document_outline_tool(protocol_handler)

from src.mcp_server.tools.check_evidence import register_tool as register_check_evidence_tool
register_check_evidence_tool(protocol_handler)

from src.mcp_server.tools.get_document_full_text import register_tool as register_document_full_text_tool
register_document_full_text_tool(protocol_handler)
```

Recommended Agent/Harness usage:

```text
Document analysis:
list_documents -> get_document_outline -> read_chunk -> get_neighbor_chunks

General QA:
query_knowledge_hub -> read_chunk -> check_evidence

Table QA:
search_by_metadata(has_table=true) -> read_chunk -> get_neighbor_chunks -> check_evidence

Figure/Image QA:
search_by_metadata(has_image=true) -> read_chunk -> get_neighbor_chunks -> check_evidence
```

`check_evidence` is a lightweight rules-first harness gate. It does not replace RAGAS. Use it as a cheap runtime validation layer, and use RAGAS for offline evaluation.


最后重启 MCP server。

## 用法示例

### read_chunk

```json
{
  "chunk_id": "doc_xxx_0014_ed4717d8",
  "collection": "knowledge_hub"
}
```

### get_neighbor_chunks

```json
{
  "chunk_id": "doc_xxx_0014_ed4717d8",
  "window": 1,
  "collection": "knowledge_hub"
}
```

### list_documents

```json
{
  "collection": "knowledge_hub",
  "limit": 50
}
```

### search_by_metadata

```json
{
  "query": "experimental results",
  "top_k": 5,
  "collection": "knowledge_hub",
  "filters": {
    "has_table": true,
    "exclude_references": true
  }
}
```


###check_evdience

```json
{
  "query": "这篇论文的实验结果说明了什么？",
  "answer": "这篇论文在 CovidQA 和 PolicyQA 上有提升，但 TechQA 上效果不明显。",
  "evidence_chunk_ids": [
    "doc_xxx_0014_ed4717d8",
    "doc_xxx_0015_2eeaf116"
  ],
  "collection": "knowledge_hub",
  "require_citations": false,
  "min_evidence_count": 1
}