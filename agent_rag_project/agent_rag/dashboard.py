"""Agent RAG Dashboard - 实时展示思考过程（SSE 流式输出）"""
import asyncio
import json
import os
import sys
import queue
import threading
import time
from pathlib import Path

# 添加 MODULAR 项目到 Python 路径
modular_root = Path(__file__).resolve().parent.parent / "mcp_rag"
if str(modular_root) not in sys.path:
    sys.path.insert(0, str(modular_root))

from flask import Flask, render_template_string, request, Response, jsonify
from agent_rag.orchestrator.rag_orchestrator import RagOrchestrator

app = Flask(__name__)
orchestrator = None

# 用于在 async 和 sync 之间传递进度消息
progress_queues: dict[str, queue.Queue] = {}

# SSE / 后台任务最长等待（复杂问题 + 全局 replan 可能超过 5 分钟）
_STREAM_TIMEOUT_SEC = int(os.environ.get("AGENT_RAG_STREAM_TIMEOUT", "900"))
_HEARTBEAT_SEC = 20
_async_loop: asyncio.AbstractEventLoop | None = None
_async_loop_thread: threading.Thread | None = None
_async_loop_lock = threading.Lock()


def _get_async_loop() -> asyncio.AbstractEventLoop:
    """启动并返回进程内唯一的后台 asyncio loop。"""
    global _async_loop, _async_loop_thread
    with _async_loop_lock:
        if _async_loop is not None and _async_loop.is_running():
            return _async_loop

        loop = asyncio.new_event_loop()

        def _run_forever() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        thread = threading.Thread(target=_run_forever, name="agent-rag-async", daemon=True)
        thread.start()
        _async_loop = loop
        _async_loop_thread = thread
        return loop


def _run_coro_sync(coro, *, timeout: float = 300):
    loop = _get_async_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Agent RAG Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #eee; padding: 20px; }
        .container { max-width: 1100px; margin: 0 auto; }
        h1 { text-align: center; color: #4a90d9; margin-bottom: 24px; }
        .input-area { display: flex; gap: 10px; margin-bottom: 20px; }
        #query { flex: 1; padding: 14px 18px; font-size: 16px; border: 2px solid #333; border-radius: 8px; background: #16213e; color: #eee; outline: none; }
        #query:focus { border-color: #4a90d9; }
        #ask-btn { padding: 14px 28px; font-size: 16px; background: #4a90d9; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: bold; }
        #ask-btn:hover { background: #357abd; }
        #ask-btn:disabled { background: #555; cursor: not-allowed; }
        .section { background: #16213e; border-radius: 8px; padding: 16px; margin-bottom: 16px; border: 1px solid #333; }
        .section h2 { color: #4a90d9; font-size: 13px; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 1px; }
        #thinking-log { max-height: 400px; overflow-y: auto; font-family: monospace; font-size: 13px; line-height: 1.6; }
        .log-entry { padding: 4px 8px; margin: 2px 0; border-radius: 4px; animation: fadeIn 0.3s; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-5px); } to { opacity: 1; transform: translateY(0); } }
        .log-plan { background: #1b2838; color: #64b5f6; border-left: 3px solid #64b5f6; }
        .log-tool-call { background: #1b3828; color: #81c784; border-left: 3px solid #81c784; }
        .log-tool-result { background: #0a1628; color: #adb5bd; border-left: 3px solid #546e7a; font-size: 12px; }
        .log-eval { background: #382b1b; color: #ffb74d; border-left: 3px solid #ffb74d; }
        .log-error { background: #3d1b1b; color: #ef5350; border-left: 3px solid #ef5350; }
        .log-info { background: #16213e; color: #90a4ae; border-left: 3px solid #546e7a; }
        .log-answer { background: #1b3828; color: #a5d6a7; border-left: 3px solid #66bb6a; font-weight: bold; }
        #answer { white-space: pre-wrap; line-height: 1.8; color: #ddd; font-size: 15px; }
        .hidden { display: none; }
        #time { color: #666; font-size: 13px; margin-top: 10px; }
        .pulse { display: inline-block; width: 8px; height: 8px; background: #4a90d9; border-radius: 50%; animation: pulse 1s infinite; margin-right: 8px; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
    </style>
</head>
<body>
    <div class="container">
        <h1>Agent RAG Dashboard</h1>
        <div class="input-area">
            <input type="text" id="query" placeholder="输入你的问题..." value="TOPMOST 主要解决什么问题？" />
            <button id="ask-btn" onclick="ask()">提问</button>
        </div>

        <div id="thinking-section" class="section hidden">
            <h2><span class="pulse" id="pulse"></span>Agent 思考过程</h2>
            <div id="thinking-log"></div>
        </div>

        <div id="answer-section" class="section hidden">
            <h2>最终回答</h2>
            <div id="answer"></div>
            <div id="time"></div>
        </div>

        <div id="memory-section" class="section hidden">
            <h2>记忆系统状态</h2>
            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px;">
                <div>
                    <h3 style="color:#81c784; font-size:12px; margin-bottom:8px;">短期记忆 (Short-term)</h3>
                    <div id="mem-short" style="font-size:12px; max-height:200px; overflow-y:auto;"></div>
                </div>
                <div>
                    <h3 style="color:#64b5f6; font-size:12px; margin-bottom:8px;">长期记忆 (Long-term / ChromaDB)</h3>
                    <div id="mem-long" style="font-size:12px; max-height:200px; overflow-y:auto;"></div>
                </div>
                <div>
                    <h3 style="color:#ffb74d; font-size:12px; margin-bottom:8px;">情景记忆 (Episodic / SQLite+Qdrant)</h3>
                    <div id="mem-episodic" style="font-size:12px; max-height:200px; overflow-y:auto;"></div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let eventSource = null;

        function addLog(type, text) {
            const log = document.getElementById('thinking-log');
            const entry = document.createElement('div');
            entry.className = 'log-entry log-' + type;
            entry.textContent = text;
            log.appendChild(entry);
            log.scrollTop = log.scrollHeight;
        }

        async function ask() {
            const query = document.getElementById('query').value.trim();
            if (!query) return;

            const btn = document.getElementById('ask-btn');
            btn.disabled = true;

            // 清空之前的内容
            document.getElementById('thinking-log').innerHTML = '';
            document.getElementById('thinking-section').classList.remove('hidden');
            document.getElementById('answer-section').classList.add('hidden');
            document.getElementById('pulse').style.display = 'inline-block';

            addLog('info', '开始处理问题: ' + query);

            // 使用 SSE 接收流式进度
            // 同页多轮：固定 conversationId（写入 sessionStorage）
            if (!window.conversationId) {
                window.conversationId = sessionStorage.getItem('agentRagConversationId');
                if (!window.conversationId) {
                    window.conversationId = 'conv-' + Date.now();
                    sessionStorage.setItem('agentRagConversationId', window.conversationId);
                }
            }
            const sessionId = window.conversationId;
            eventSource = new EventSource('/stream?query=' + encodeURIComponent(query) + '&session=' + encodeURIComponent(sessionId));

            eventSource.onmessage = function(event) {
                const data = JSON.parse(event.data);

                if (data.type === 'plan') {
                    addLog('plan', '📋 规划: ' + data.text);
                } else if (data.type === 'tool_call') {
                    addLog('tool-call', '🔧 调用工具: ' + data.text);
                } else if (data.type === 'tool_result') {
                    addLog('tool-result', '   ↳ 返回: ' + data.text);
                } else if (data.type === 'eval') {
                    addLog('eval', '📊 评估: ' + data.text);
                } else if (data.type === 'error') {
                    addLog('error', '❌ ' + data.text);
                } else if (data.type === 'answer') {
                    // 最终答案
                    document.getElementById('answer').textContent = data.text;
                    document.getElementById('time').textContent = '耗时: ' + data.elapsed + 's';
                    document.getElementById('answer-section').classList.remove('hidden');
                    document.getElementById('pulse').style.display = 'none';
                    addLog('answer', '✅ 回答生成完成');
                    eventSource.close();
                    btn.disabled = false;
                    // 加载记忆状态
                    loadMemory();
                } else if (data.type === 'heartbeat') {
                    // 保持 SSE 连接，不刷屏
                } else if (data.type === 'info') {
                    addLog('info', data.text);
                }
            };

            eventSource.onerror = function() {
                // 仅在后端未正常结束时提示；若已收到 answer 则忽略
                if (document.getElementById('answer-section').classList.contains('hidden')) {
                    eventSource.close();
                    document.getElementById('pulse').style.display = 'none';
                    btn.disabled = false;
                    addLog('error', '连接中断（可能仍在后台处理，请看终端；或刷新后重试）');
                }
            };
        }

        document.getElementById('query').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') ask();
        });

        async function loadMemory() {
            try {
                const resp = await fetch('/memory');
                const mem = await resp.json();

                // 短期记忆
                let shortHtml = `<div style="color:#aaa; margin-bottom:4px;">共 ${mem.short_term.length} 条</div>`;
                for (const item of mem.short_term.slice(-5)) {
                    shortHtml += `<div style="padding:4px; margin:3px 0; background:#0a1628; border-radius:3px;">
                        <div style="color:#81c784;">Q: ${item.query}</div>
                        <div style="color:#888; font-size:11px;">${item.text}</div>
                    </div>`;
                }
                document.getElementById('mem-short').innerHTML = shortHtml || '<span style="color:#666;">空</span>';

                // 长期记忆
                let longHtml = `<div style="color:#aaa; margin-bottom:4px;">共 ${mem.long_term_count} 条</div>`;
                for (const item of mem.long_term.slice(-5)) {
                    longHtml += `<div style="padding:4px; margin:3px 0; background:#0a1628; border-radius:3px;">
                        <div style="color:#64b5f6;">${item.query || item.id}</div>
                        <div style="color:#888; font-size:11px;">${item.text}</div>
                    </div>`;
                }
                document.getElementById('mem-long').innerHTML = longHtml || '<span style="color:#666;">空</span>';

                // 情景记忆
                let epiHtml = `<div style="color:#aaa; margin-bottom:4px;">共 ${mem.episodic_count} 条</div>`;
                for (const item of mem.episodic.slice(-5)) {
                    epiHtml += `<div style="padding:4px; margin:3px 0; background:#0a1628; border-radius:3px;">
                        <div style="color:#ffb74d;">${item.event_text || item.id}</div>
                        <div style="color:#888; font-size:11px;">session: ${item.session_id || '?'} | ${item.timestamp || ''}</div>
                    </div>`;
                }
                document.getElementById('mem-episodic').innerHTML = epiHtml || '<span style="color:#666;">空</span>';

                document.getElementById('memory-section').classList.remove('hidden');
            } catch(e) {
                console.error('Memory load failed:', e);
            }
        }
    </script>
</body>
</html>
"""


def get_orchestrator():
    global orchestrator
    if orchestrator is None:
        from agent_rag.config_loader import load_config
        # fast overlay：更短 replan/步数，Dashboard 不易 SSE 超时
        config = load_config(fast=True)
        rag = config.setdefault("rag_agent", {})
        mcp = rag.setdefault("mcp", {})
        mcp["persistent_stdio"] = True
        orchestrator = RagOrchestrator(config=config)
    return orchestrator


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/memory')
def get_memory():
    """返回三层记忆系统的当前状态"""
    orch = get_orchestrator()
    mem = orch._memory

    # 短期记忆
    short_term = []
    if hasattr(mem, '_short_term_memory'):
        for item in mem._short_term_memory[-10:]:  # 最近 10 条
            short_term.append({
                "query": str(item.get("query", ""))[:100],
                "text": str(item.get("result", {}).get("text", "") if isinstance(item.get("result"), dict) else "")[:150],
                "score": item.get("score", 0),
                "timestamp": str(item.get("timestamp", "")),
            })

    # 长期记忆（从 ChromaDB 读取）
    long_term = []
    long_term_count = 0
    try:
        ltc = mem._long_term_collection
        if ltc is not None:
            long_term_count = ltc.count()
            if long_term_count > 0:
                results = ltc.peek(limit=5)  # 最近 5 条
                ids = results.get("ids", [])
                docs = results.get("documents", [])
                metas = results.get("metadatas", [])
                for i, doc_id in enumerate(ids):
                    long_term.append({
                        "id": doc_id,
                        "query": str((metas[i] or {}).get("original_query", ""))[:100] if i < len(metas) else "",
                        "text": str(docs[i])[:150] if i < len(docs) and docs[i] else "",
                    })
    except Exception:
        pass

    # 情景记忆（从 SQLite 读取）
    episodic = []
    episodic_count = 0
    try:
        sql_conn = mem.sqlite_conn
        if sql_conn is not None:
            cursor = sql_conn.execute("SELECT COUNT(*) FROM episodic_events")
            episodic_count = cursor.fetchone()[0]
            cursor = sql_conn.execute(
                "SELECT event_id, event_text, session_id, timestamp FROM episodic_events ORDER BY timestamp DESC LIMIT 5"
            )
            for row in cursor.fetchall():
                episodic.append({
                    "id": row[0],
                    "event_text": str(row[1])[:150] if row[1] else "",
                    "session_id": row[2] or "",
                    "timestamp": row[3] or "",
                })
    except Exception:
        pass

    return jsonify({
        "short_term": short_term,
        "long_term": long_term,
        "long_term_count": long_term_count,
        "episodic": episodic,
        "episodic_count": episodic_count,
    })


@app.route('/stream')
def stream():
    query = request.args.get('query', '').strip()
    session_id = request.args.get('session', str(time.time()))

    if not query:
        def empty():
            yield f"data: {json.dumps({'type': 'error', 'text': '请输入问题'})}\n\n"
        return Response(empty(), mimetype='text/event-stream')

    # 创建进度队列
    q = queue.Queue()
    progress_queues[session_id] = q

    def run_in_thread():
        """在共享 asyncio loop 上运行 Agent RAG（支持持久 MCP 多轮）。"""
        try:
            _run_coro_sync(_run_with_progress(query, session_id, q), timeout=_STREAM_TIMEOUT_SEC)
        except Exception as e:
            q.put({"type": "error", "text": f"{type(e).__name__}: {e}"})
        finally:
            q.put(None)  # 结束信号

    # 启动后台线程
    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

    def generate():
        """SSE 生成器：从队列中读取消息并发送"""
        deadline = time.time() + _STREAM_TIMEOUT_SEC
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                yield f"data: {json.dumps({'type': 'error', 'text': '处理超时（超过 %ds）' % _STREAM_TIMEOUT_SEC})}\n\n"
                break
            try:
                msg = q.get(timeout=min(_HEARTBEAT_SEC + 5, remaining))
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat', 'text': 'waiting'})}\n\n"
                continue
            if msg is None:
                break
            yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
        progress_queues.pop(session_id, None)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


async def _run_with_progress(query: str, session_id: str, q: queue.Queue):
    """运行 Agent RAG 并把进度发到队列"""
    orch = get_orchestrator()
    t0 = time.perf_counter()

    # Monkey-patch Generator 来捕获思考过程
    gen = orch._generator

    # 1. 拦截 Planner
    original_plan = orch._planner.plan
    def patched_plan(*args, **kwargs):
        result = original_plan(*args, **kwargs)
        if result:
            subtasks = [f"{t.get('id')}: {t.get('description', '')[:60]}" for t in result[:5]]
            q.put({"type": "plan", "text": f"生成 {len(result)} 个子任务"})
            for s in subtasks:
                q.put({"type": "plan", "text": f"  → {s}"})
        return result
    orch._planner.plan = patched_plan

    original_replan = orch._planner.replan
    def patched_replan(*args, **kwargs):
        q.put({"type": "info", "text": "全局/子任务 replan 中..."})
        result = original_replan(*args, **kwargs)
        if result:
            q.put({"type": "plan", "text": f"replan 追加 {len(result)} 个子任务"})
        return result
    orch._planner.replan = patched_replan

    # 2. 拦截 Executor
    original_run_subtask = gen.run_subtask
    async def patched_run_subtask(global_query, task, executor, get_schema, evaluator, **kwargs):
        task_id = task.get("id", "?")
        task_desc = task.get("description", "")[:80]
        q.put({"type": "info", "text": f"执行子任务 [{task_id}]: {task_desc}"})

        # 拦截 executor.execute_task
        original_execute = executor.execute_task
        async def patched_execute(t, get_input_schema):
            tool_name = t.get("tool_name") or t.get("suggested_tool") or "unknown"
            q.put({"type": "tool_call", "text": f"{tool_name}"})
            result = await original_execute(t, get_input_schema)
            # 提取返回摘要
            if isinstance(result, dict):
                content = result.get("content", [])
                for block in content[:1]:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")[:200]
                        q.put({"type": "tool_result", "text": text})
            return result
        executor.execute_task = patched_execute

        result = await original_run_subtask(global_query, task, executor, get_schema, evaluator, **kwargs)

        # 恢复
        executor.execute_task = original_execute

        status = result.get("status", "?") if isinstance(result, dict) else "?"
        q.put({"type": "eval", "text": f"子任务 [{task_id}] 状态: {status}"})
        return result

    gen.run_subtask = patched_run_subtask

    # 3. 拦截记忆检索
    mem = orch._memory
    ctx = orch._context

    original_retrieve_context = mem.retrieve_context
    def patched_retrieve_context(*args, **kwargs):
        q.put({"type": "info", "text": "🧠 检索记忆系统..."})
        result = original_retrieve_context(*args, **kwargs)
        if result and str(result).strip():
            q.put({"type": "tool_result", "text": f"记忆检索结果: {str(result)[:200]}"})
        else:
            q.put({"type": "info", "text": "🧠 记忆系统: 无相关历史记忆"})
        return result
    mem.retrieve_context = patched_retrieve_context

    original_get_relevant_context = ctx.get_relevant_context
    def patched_get_relevant_context(*args, **kwargs):
        result = original_get_relevant_context(*args, **kwargs)
        if result and str(result).strip():
            q.put({"type": "tool_result", "text": f"上下文窗口: {str(result)[:200]}"})
        else:
            q.put({"type": "info", "text": "🧠 上下文窗口: 无历史对话"})
        return result
    ctx.get_relevant_context = patched_get_relevant_context

    # 拦截 promote_to_long_term 和 add_event
    original_promote = mem.promote_to_long_term
    def patched_promote(*args, **kwargs):
        result = original_promote(*args, **kwargs)
        # 检查是否有新的长期记忆
        try:
            ltc = mem._long_term_collection
            if ltc and ltc.count() > 0:
                q.put({"type": "info", "text": f"💾 长期记忆: 已有 {ltc.count()} 条"})
        except Exception:
            pass
        return result
    mem.promote_to_long_term = patched_promote

    original_add_event = mem.add_event
    def patched_add_event(*args, **kwargs):
        q.put({"type": "info", "text": "📝 写入情景记忆..."})
        result = original_add_event(*args, **kwargs)
        q.put({"type": "info", "text": "📝 情景记忆写入完成"})
        return result
    mem.add_event = patched_add_event

    done = asyncio.Event()

    async def _heartbeat() -> None:
        while not done.is_set():
            await asyncio.sleep(_HEARTBEAT_SEC)
            if not done.is_set():
                q.put({"type": "info", "text": "仍在处理（LLM 评估 / 全局门禁 / 终稿合成）..."})

    hb = asyncio.create_task(_heartbeat())

    # 3. 运行
    try:
        q.put({"type": "info", "text": "正在调用 Planner 规划子任务..."})
        result = await orch.answer(query, session_id=session_id)
        elapsed = round(time.perf_counter() - t0, 1)

        answer_text = result.get("text", "")
        q.put({"type": "answer", "text": answer_text, "elapsed": str(elapsed)})

    except Exception as e:
        elapsed = round(time.perf_counter() - t0, 1)
        q.put({"type": "error", "text": f"失败 ({elapsed}s): {type(e).__name__}: {e}"})

    finally:
        done.set()
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass
        # 恢复
        gen.run_subtask = original_run_subtask
        orch._planner.plan = original_plan
        orch._planner.replan = original_replan
        mem.retrieve_context = original_retrieve_context
        ctx.get_relevant_context = original_get_relevant_context
        mem.promote_to_long_term = original_promote
        mem.add_event = original_add_event


if __name__ == '__main__':
    import atexit

    def _shutdown_mcp():
        global orchestrator
        if orchestrator is None:
            return
        try:
            _run_coro_sync(orchestrator.close_mcp(), timeout=30)
        except Exception:
            pass

    atexit.register(_shutdown_mcp)
    print("=" * 50)
    print("  Agent RAG Dashboard (实时思考过程)")
    print("=" * 50)
    print("\n启动中...")
    get_orchestrator()
    print("✓ 初始化完成")
    print(f"\n打开浏览器访问: http://127.0.0.1:5000")
    print("按 Ctrl+C 停止\n")
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
