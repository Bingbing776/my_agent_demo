"""入口：仅启动 Harness（按 tech_doc 写实现代码），不涉及 RagOrchestrator。"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),  # 终端输出
        logging.FileHandler("harness.log", encoding="utf-8"),  # 文件输出
    ],
)

from core.harness_controller import HarnessController
from harness.config_loader import load_harness_config
from harness.llm_client import create_harness_llm
from harness.evaluator import HarnessEvaluator
from harness.generator import HarnessGenerator
from harness.planner import HarnessPlanner

_PKG = Path(__file__).resolve().parent


def _preflight_check_llm(harness_llm) -> None:
    """启动前验证 LLM API 是否可用：发一条简单消息，确认能收到回复。"""
    from harness.llm_helpers import chat

    print("[Preflight] 验证 LLM API 连通性...")
    try:
        response = chat(
            harness_llm,
            system="只回复 OK",
            user="ping",
            harness_cfg={},
            agent_key="preflight",
        )
        if not response or not response.strip():
            raise RuntimeError("LLM 返回空响应")
        print(f"[Preflight] LLM API 正常 OK (响应: {response.strip()[:50]})")
    except Exception as e:
        raise RuntimeError(
            f"[Preflight] LLM API 验证失败: {e}\n"
            "请检查 harness.yaml 中 llm 配置（api_key、base_url、model）是否正确。"
        ) from e


def _preflight_check_fc_llm(hcfg: dict) -> None:
    """启动前验证 FC LLM（Function Calling 专用）API 是否可用，包括 tools 支持。"""
    from harness.llm_http import create_harness_custom_http, HarnessLLMHttpError

    print("[Preflight] 验证 FC LLM API 连通性（Function Calling）...")
    try:
        http = create_harness_custom_http(hcfg, agent_key="evaluator")
    except (HarnessLLMHttpError, FileNotFoundError):
        http = None

    if http is None:
        print("[Preflight] FC LLM 未配置或使用 JSON 协议，跳过 OK")
        return

    try:
        data = http.chat_completions(
            [{"role": "user", "content": "ping"}],
            harness_cfg=hcfg,
            agent_key="evaluator",
            tools=[{
                "type": "function",
                "function": {
                    "name": "test_ping",
                    "description": "连通性测试",
                    "parameters": {
                        "type": "object",
                        "properties": {"msg": {"type": "string"}},
                        "required": ["msg"],
                    },
                },
            }],
            tool_choice="auto",
        )
        # 验证响应结构正常
        choices = data.get("choices")
        if not choices:
            raise RuntimeError("FC LLM 返回空 choices")
        msg = choices[0].get("message", {})
        # 有 tool_calls 或有 content 都算正常
        if msg.get("tool_calls") or msg.get("content"):
            has_tools = "yes" if msg.get("tool_calls") else "no(but connected)"
            print(
                f"[Preflight] FC LLM API OK "
                f"(model: {data.get('model', http.model)}, "
                f"tools support: {has_tools})"
            )
        else:
            raise RuntimeError("FC LLM 返回无内容响应")
    except HarnessLLMHttpError as e:
        raise RuntimeError(
            f"[Preflight] FC LLM API 验证失败: {e}\n"
            "请检查 harness.yaml 中 fc_llm 配置（api_key、base_url、model）是否正确。"
        ) from e


def _preflight_check_mcp(hcfg: dict) -> None:
    """启动前验证 MCP server 是否可用：尝试连接并确认进程能启动。"""
    import os

    mcp_cmd = hcfg.get("mcp_server_command") or os.environ.get("MCP_SERVER_COMMAND")
    if not mcp_cmd:
        raise RuntimeError(
            "[Preflight] MCP server 未配置！\n"
            "请在 harness.yaml 中设置 mcp_server_command，"
            "或设置环境变量 MCP_SERVER_COMMAND（如 'python -m src.mcp_server.server'）。\n"
            "Integration/E2E 测试需要真实 MCP server 才能验证调用链路。"
        )

    # MCP server 需要在正确的工作目录下启动（因为它会读 config/settings.yaml）
    mcp_cwd = hcfg.get("mcp_server_cwd") or os.environ.get("MCP_SERVER_CWD")
    if mcp_cwd:
        mcp_cwd = str(Path(mcp_cwd).resolve()) if not Path(mcp_cwd).is_absolute() else mcp_cwd

    print(f"[Preflight] 验证 MCP server 连通性 (command: {mcp_cmd}, cwd: {mcp_cwd or '当前目录'})...")
    try:
        import subprocess

        proc = subprocess.Popen(
            mcp_cmd.split() if isinstance(mcp_cmd, str) else mcp_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=mcp_cwd,
        )
        # 给 3 秒看能不能启动
        try:
            _, stderr = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            # 超时说明进程在运行（没有立即退出），这是好事
            print("[Preflight] MCP server 进程可启动 OK")
            return

        if proc.returncode != 0:
            raise RuntimeError(
                f"MCP server 启动失败 (exit {proc.returncode}):\n{stderr.decode()[:500]}"
            )
        print("[Preflight] MCP server 进程可启动 OK")
    except FileNotFoundError as e:
        raise RuntimeError(
            f"[Preflight] MCP server 命令不存在: {mcp_cmd}\n"
            "请检查 harness.yaml 中 mcp_server_command 或环境变量 MCP_SERVER_COMMAND。"
        ) from e
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"[Preflight] MCP server 验证失败: {e}") from e


def main() -> None:
    parser = argparse.ArgumentParser(description="meta_harness_rag 实现 Harness")
    parser.add_argument("--max-tasks", type=int, default=None, help="最多执行几条子任务")
    parser.add_argument("--skip-tasks", type=int, default=0, help="跳过前 N 条任务（用于断点续跑）")
    parser.add_argument("--dry-plan", action="store_true", help="只打印任务队列")
    parser.add_argument("--skip-preflight", action="store_true", help="跳过启动前检查")
    args = parser.parse_args()

    hcfg = load_harness_config()
    tech_doc = _PKG / hcfg.get("tech_doc_path", "docs/tech_doc.md")

    harness_llm = None
    if hcfg.get("llm_enabled", True):
        try:
            harness_llm = create_harness_llm(hcfg, _PKG)
            print(f"[Harness] LLM 已连接（Planner / Generator / Evaluator 共用）: {harness_llm.provider} / {harness_llm.model}")
        except Exception as e:
            print(f"[Harness] LLM 连接失败: {e}")
            if hcfg.get("llm_required", True):
                raise

    # --- Preflight 检查：在正式运行前验证 LLM 和 MCP 是否可用 ---
    if not args.skip_preflight and not args.dry_plan:
        if harness_llm:
            _preflight_check_llm(harness_llm)
        _preflight_check_fc_llm(hcfg)
        _preflight_check_mcp(hcfg)
        print("[Preflight] 所有检查通过 OK\n")

    planner = HarnessPlanner(
        tech_doc,
        config=hcfg,
        package_root=_PKG,
        harness_cfg=hcfg,
        llm=harness_llm,
    )
    if args.dry_plan:
        from harness.evaluator.runtime import EvaluatorRuntime

        ev_cfg = hcfg.get("evaluator") or {}
        ev_rt = EvaluatorRuntime(ev_cfg, package_root=_PKG, harness_cfg=hcfg)
        for t in planner.plan():
            t = dict(t)
            ev_rt.apply_index_to_task(t)
            print(
                f"{t.get('id')}\t{t.get('symbol')}\t{t.get('target_file')}\t"
                f"{t.get('test_file') or '(INDEX 无匹配)'}"
            )
        return

    gen_cfg = dict(hcfg.get("generator") or {})
    gen_cfg.setdefault("implementation_root", hcfg.get("implementation_root", "../agent_rag/agent_rag"))
    if hcfg.get("read_only_code_roots") is not None:
        gen_cfg["read_only_code_roots"] = hcfg["read_only_code_roots"]
    if hcfg.get("mcp_server_code_path"):
        gen_cfg["mcp_server_code_path"] = hcfg["mcp_server_code_path"]
    generator = HarnessGenerator(
        gen_cfg,
        package_root=_PKG,
        tech_doc_path=tech_doc,
        harness_cfg=hcfg,
        llm=harness_llm,
    )
    evaluator = HarnessEvaluator(
        hcfg.get("evaluator") or {},
        package_root=_PKG,
        harness_cfg=hcfg,
        llm=harness_llm,
        tech_doc_path=tech_doc,
    )
    harness = HarnessController(planner, generator, evaluator)
    results = harness.run(max_tasks=args.max_tasks, skip_tasks=args.skip_tasks)

    print("\n=== Harness 汇总 ===")
    for r in results:
        print(f"  {r['task_id']}: {r['status']}")


if __name__ == "__main__":
    main()
