# Agent RAG Project

A modular RAG (Retrieval-Augmented Generation) system built with MCP (Model Context Protocol) and LangGraph agents.

## Project Structure

```
agent_rag_project/
├── mcp_rag/              # MCP RAG server (knowledge retrieval backend)
├── agent_rag/            # RAG agent orchestration layer
└── meta_harness_rag/     # Development harness for automated code generation
```

### 📦 Sub-Projects

| Directory | Description |
|-----------|-------------|
| **mcp_rag** | Modular RAG MCP Server - provides knowledge retrieval tools via MCP protocol |
| **agent_rag** | RAG Agent - orchestrates multi-agent workflows with memory, context, and tool routing |
| **meta_harness_rag** | Meta Harness - automated development tool that generates/maintains agent_rag code |

## Quick Start

### 1. Setup Environment

Each sub-project has its own dependencies:

```bash
# Install mcp_rag dependencies
cd mcp_rag
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Install agent_rag dependencies (if requirements.txt exists)
cd ../agent_rag
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # or manually install dependencies

# Install meta_harness_rag dependencies
cd ../meta_harness_rag
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure API Keys

Update configuration files with your API keys:

- `mcp_rag/config/settings.yaml`
- `agent_rag/config/settings.yaml`
- `meta_harness_rag/config/harness.yaml`

Replace placeholders:
- `YOUR_DEEPSEEK_API_KEY`
- `YOUR_DASHSCOPE_API_KEY`
- `YOUR_IFLYTEK_API_KEY`
- `YOUR_LLM_BASE_URL`
- `YOUR_EMBEDDING_API_URL`

### 3. Prepare Data

Download documents for RAG ingestion:

```bash
cd mcp_rag/data/documents/acl_2023_2026
python download_acl_pdfs.py
```

### 4. Run Ingestion Pipeline

Build the vector database:

```bash
cd mcp_rag
python -c "
from src.ingestion.pipeline import IngestionPipeline
from src.core.settings import load_settings
settings = load_settings('config/settings.yaml')
pipeline = IngestionPipeline(settings)
pipeline.ingest('data/documents/acl_2023_2026/data/demo10', collection='paper')
"
```

### 5. Run Evaluation

Test retrieval quality with hit rate, MRR, and recall metrics:

```bash
cd mcp_rag
python scripts/evaluate.py \
  --test-set "data/YOUR_TEST_SET.jsonl" \
  --collection paper \
  --top-k 10
```

## Architecture Overview

### MCP RAG Server (`mcp_rag/`)

Provides knowledge retrieval capabilities via MCP protocol:

- **Ingestion**: PDF parsing, text splitting, embedding, vector indexing (Chroma + BM25)
- **Retrieval**: Hybrid search combining dense (embeddings) and sparse (BM25) retrieval
- **Evaluation**: CustomEvaluator for IR metrics (hit rate, MRR, recall@k)
- **MCP Tools**: Exposed via stdio for integration with agents

**Key Components:**
- `src/ingestion/` - Document loading and indexing pipeline
- `src/core/query_engine/` - Hybrid search implementation
- `src/libs/evaluator/` - Evaluation metrics
- `scripts/evaluate.py` - Batch evaluation script

### RAG Agent (`agent_rag/`)

Orchestrates multi-agent workflows for RAG tasks:

- **Memory**: Episodic memory for conversation history
- **Context**: Project context management
- **MCP Client**: Calls mcp_rag tools via stdio
- **Agents**: Planner, Executor, Critic agents (LangGraph)
- **Orchestrator**: Coordinates agent interactions

**Key Components:**
- `agent_rag/memory/` - Memory systems (§1)
- `agent_rag/context/` - Context management (§2)
- `agent_rag/mcp/` - MCP client integration (§3)
- `agent_rag/agents/` - Agent implementations (§4-6)
- `agent_rag/orchestrator/` - Orchestration layer (§7)

### Meta Harness (`meta_harness_rag/`)

Development automation tool that reads specifications and generates code:

- **Planner**: Generates implementation plans from tech specs
- **Generator**: Writes code following specifications
- **Evaluator**: Validates generated code against contracts

**Usage:**
```bash
cd meta_harness_rag
python main.py --dry-plan          # Preview plan without execution
python main.py --max-tasks 1       # Generate one task at a time
```

## Evaluation Metrics

The system supports multiple evaluation approaches:

### IR Metrics (CustomEvaluator)
- **Hit Rate**: Percentage of queries with at least one relevant result
- **MRR (Mean Reciprocal Rank)**: Average of reciprocal ranks of first relevant result
- **Recall@K**: Percentage of relevant documents retrieved in top-k

Run evaluation:
```bash
cd mcp_rag
python scripts/evaluate.py --test-set data/test.jsonl --collection paper --top-k 10
```

## Configuration

Each sub-project uses YAML configuration:

- `mcp_rag/config/settings.yaml` - LLM, embedding, vector store settings
- `agent_rag/config/settings.yaml` - Agent configuration, MCP server path
- `meta_harness_rag/config/harness.yaml` - Harness LLM and generation settings

## Development Workflow

1. **Define Requirements**: Update `meta_harness_rag/docs/tech_doc.md`
2. **Generate Code**: Run harness to implement specifications
3. **Test**: Run pytest contracts in `agent_rag/test/contracts/`
4. **Evaluate**: Run retrieval evaluation with test sets
5. **Iterate**: Refine specifications and regenerate

## Tech Stack

- **LLM Providers**: DeepSeek, DashScope (Qwen), iFlytek (Claude proxy)
- **Embeddings**: Text-embedding-v3/v4 (DashScope)
- **Vector Store**: ChromaDB
- **Sparse Retrieval**: BM25
- **Agent Framework**: LangGraph
- **MCP**: Model Context Protocol for tool integration
- **PDF Processing**: MarkItDown, PyMuPDF, pdfplumber

## License

MIT

## Contributing

This is a research project. Contributions welcome via issues and pull requests.
