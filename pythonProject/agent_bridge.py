"""
Agent Bridge - 集成接口
主力B - Day2/Day3

职责：
  为主力A的 Agent 核心提供统一的"安全执行"接口，
  主力A 只需调用 execute(cmd) 或 execute_batch(cmds)，
  无需关心风控和前端展示细节。

接口形式：
  - 直接调用（同进程）
  - HTTP API（FastAPI，跨进程）
  - WebSocket（流式输出）
"""

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from executor import CommandExecutor, ExecutionResult, SSHExecutor
from risk_engine import RiskEngine, RiskLevel, RiskResult, check

logger = logging.getLogger("agent_bridge")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ─────────────────────────────────────────────
#  统一结果格式
# ─────────────────────────────────────────────
def format_result(result: ExecutionResult) -> Dict[str, Any]:
    """统一的结果字典，供 Agent 组装自然语言回复"""
    return {
        "command":    result.command,
        "success":    result.success,
        "stdout":     result.stdout,
        "stderr":     result.stderr,
        "returncode": result.returncode,
        "elapsed":    round(result.elapsed, 3),
        "risk_level": result.risk.level.value,
        "blocked":    result.blocked,
        "block_reason": result.error if result.blocked else "",
    }


# ─────────────────────────────────────────────
#  直接调用版本（主力A同进程使用）
# ─────────────────────────────────────────────
class AgentBridge:
    """
    主力A 调用此类来安全执行命令。

    用法（主力A 视角）:
        bridge = AgentBridge()
        result = await bridge.execute("df -h")
        print(result["stdout"])
    """

    def __init__(
        self,
        confirm_callback: Optional[Callable[[RiskResult], bool]] = None,
        ssh_host: str = None,
        ssh_user: str = None,
        ssh_key: str = None,
    ):
        if ssh_host:
            self.executor = SSHExecutor(
                host=ssh_host,
                username=ssh_user,
                key_path=ssh_key,
            )
        else:
            self.executor = CommandExecutor(timeout=30)

        # confirm_callback: 前端提供，用于 DANGER 命令的确认弹窗
        # 如果没有提供，DANGER 命令将自动被拒绝
        self.confirm_callback = confirm_callback
        self.risk_engine = RiskEngine()

    async def execute(self, command: str) -> Dict[str, Any]:
        """执行单条命令，返回结果字典"""
        result = await self.executor.run(command, confirm_callback=self.confirm_callback)
        logger.info(
            f"[execute] cmd={command!r} risk={result.risk.level.value} "
            f"rc={result.returncode} blocked={result.blocked}"
        )
        return format_result(result)

    async def execute_batch(self, commands: List[str], stop_on_error: bool = True) -> List[Dict[str, Any]]:
        """
        顺序执行多条命令（连续任务）
        stop_on_error=True 时，任一命令失败/被拦截则停止
        """
        results = []
        for cmd in commands:
            res = await self.execute(cmd)
            results.append(res)
            if stop_on_error and (not res["success"] or res["blocked"]):
                logger.warning(f"[batch] 停止：{cmd!r} 失败或被拦截")
                break
        return results

    def check_risk(self, command: str) -> Dict[str, Any]:
        """仅做风险检查，不执行"""
        risk = check(command)
        return {
            "level":    risk.level.value,
            "reason":   risk.reason,
            "suggestion": risk.suggestion,
            "blocked":  risk.is_blocked,
            "requires_confirmation": risk.requires_confirmation,
        }

    async def close(self):
        if hasattr(self.executor, "disconnect"):
            await self.executor.disconnect()


# ─────────────────────────────────────────────
#  HTTP API 版本（跨进程，FastAPI）
# ─────────────────────────────────────────────
def create_http_app():
    """
    创建 FastAPI 应用，供主力A通过 HTTP 调用执行命令。
    运行：uvicorn agent_bridge:app --host 0.0.0.0 --port 8765
    依赖：pip install fastapi uvicorn
    """
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel
    except ImportError:
        raise RuntimeError("请安装：pip install fastapi uvicorn")

    app = FastAPI(title="OS Agent Bridge", version="1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    bridge = AgentBridge()

    class ExecRequest(BaseModel):
        command: str
        allow_danger: bool = False  # 是否允许 DANGER 级别命令（前端已确认时设为 True）

    class BatchRequest(BaseModel):
        commands: List[str]
        stop_on_error: bool = True
        allow_danger: bool = False

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/execute")
    async def execute(req: ExecRequest):
        """执行单条命令"""
        risk_info = bridge.check_risk(req.command)

        if risk_info["blocked"]:
            return {
                "success": False,
                "blocked": True,
                "risk_level": risk_info["level"],
                "block_reason": risk_info["reason"],
                "command": req.command,
            }

        if risk_info["requires_confirmation"] and not req.allow_danger:
            return {
                "success": False,
                "blocked": False,
                "requires_confirmation": True,
                "risk_level": risk_info["level"],
                "reason": risk_info["reason"],
                "suggestion": risk_info["suggestion"],
                "command": req.command,
            }

        confirm = lambda r: True  # HTTP 调用时，确认由客户端负责（allow_danger=True）
        result = await bridge.executor.run(req.command, confirm_callback=confirm)
        return format_result(result)

    @app.post("/execute/batch")
    async def execute_batch(req: BatchRequest):
        """顺序执行多条命令"""
        confirm = (lambda r: True) if req.allow_danger else None
        results = []
        for cmd in req.commands:
            res_obj = await bridge.executor.run(cmd, confirm_callback=confirm)
            results.append(format_result(res_obj))
            if req.stop_on_error and (res_obj.blocked or not res_obj.success):
                break
        return {"results": results, "total": len(results)}

    @app.post("/check")
    async def check_risk(req: ExecRequest):
        """仅做风险检查"""
        return bridge.check_risk(req.command)

    return app


# 供 uvicorn 直接使用
try:
    app = create_http_app()
except Exception:
    app = None


# ─────────────────────────────────────────────
#  简单测试
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("启动 Agent Bridge HTTP API，端口 8765...")
    print("主力A 调用示例：")
    print("  POST http://localhost:8765/execute  {'command': 'df -h'}")
    print("  POST http://localhost:8765/check    {'command': 'rm -rf /'}")
    uvicorn.run("agent_bridge:app", host="0.0.0.0", port=8765, reload=True)
