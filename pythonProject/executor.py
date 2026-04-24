"""
命令执行器 (Command Executor)
主力B - Day1 模块

职责：
  - 接收来自 Agent 核心的命令
  - 先过风控引擎
  - 安全执行并捕获输出
  - 支持超时、输出截断
"""

import asyncio
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from risk_engine import RiskEngine, RiskLevel, RiskResult, check


@dataclass
class ExecutionResult:
    command: str
    stdout: str
    stderr: str
    returncode: int
    elapsed: float
    risk: RiskResult
    blocked: bool = False
    confirmed: bool = False
    error: str = ""

    @property
    def success(self) -> bool:
        return self.returncode == 0 and not self.blocked

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "elapsed": round(self.elapsed, 3),
            "success": self.success,
            "risk_level": self.risk.level.value,
            "blocked": self.blocked,
        }


class CommandExecutor:
    """
    安全命令执行器

    典型用法（配合前端二次确认）:
        executor = CommandExecutor()
        result = await executor.run(cmd, confirm_callback=ask_user)
    """

    def __init__(
        self,
        timeout: int = 30,
        max_output_bytes: int = 1024 * 50,  # 50 KB
        working_dir: str = "/tmp",
        allowed_shells: List[str] = None,
    ):
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes
        self.working_dir = working_dir
        self.allowed_shells = allowed_shells or ["/bin/bash", "/bin/sh"]
        self.risk_engine = RiskEngine()
        self._history: List[ExecutionResult] = []

    # ── 核心执行 ──────────────────────────────────────────────
    async def run(
        self,
        command: str,
        confirm_callback: Optional[Callable[[RiskResult], bool]] = None,
        env: dict = None,
    ) -> ExecutionResult:
        """
        执行命令的完整流程：
          1. 风控检查
          2. BLOCK → 拒绝
          3. DANGER → 调用 confirm_callback 等待确认
          4. SAFE / WARN → 直接执行
        """
        risk = self.risk_engine.evaluate_pipeline(command)

        # ── BLOCK ──
        if risk.is_blocked:
            result = ExecutionResult(
                command=command,
                stdout="",
                stderr="",
                returncode=-1,
                elapsed=0.0,
                risk=risk,
                blocked=True,
                error=f"[风控拦截] {risk.reason}",
            )
            self._history.append(result)
            return result

        # ── DANGER：等待用户确认 ──
        confirmed = True
        if risk.requires_confirmation:
            if confirm_callback is None:
                # 没有确认回调时默认拒绝
                result = ExecutionResult(
                    command=command,
                    stdout="",
                    stderr="",
                    returncode=-1,
                    elapsed=0.0,
                    risk=risk,
                    blocked=True,
                    error="危险操作需要二次确认，但未提供确认方式",
                )
                self._history.append(result)
                return result

            confirmed = confirm_callback(risk)
            if not confirmed:
                result = ExecutionResult(
                    command=command,
                    stdout="",
                    stderr="",
                    returncode=-1,
                    elapsed=0.0,
                    risk=risk,
                    blocked=True,
                    confirmed=False,
                    error="用户取消了操作",
                )
                self._history.append(result)
                return result

        # ── 执行 ──
        result = await self._execute(command, risk, confirmed, env)
        self._history.append(result)
        return result

    async def _execute(
        self,
        command: str,
        risk: RiskResult,
        confirmed: bool,
        env: dict = None,
    ) -> ExecutionResult:
        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir,
                env=env,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                elapsed = time.monotonic() - start
                return ExecutionResult(
                    command=command,
                    stdout="",
                    stderr="",
                    returncode=-1,
                    elapsed=elapsed,
                    risk=risk,
                    confirmed=confirmed,
                    error=f"命令执行超时（{self.timeout}s）",
                )

            elapsed = time.monotonic() - start
            stdout = self._truncate(stdout_bytes.decode("utf-8", errors="replace"))
            stderr = self._truncate(stderr_bytes.decode("utf-8", errors="replace"))

            return ExecutionResult(
                command=command,
                stdout=stdout,
                stderr=stderr,
                returncode=proc.returncode,
                elapsed=elapsed,
                risk=risk,
                confirmed=confirmed,
            )

        except Exception as e:
            elapsed = time.monotonic() - start
            return ExecutionResult(
                command=command,
                stdout="",
                stderr="",
                returncode=-1,
                elapsed=elapsed,
                risk=risk,
                confirmed=confirmed,
                error=str(e),
            )

    # ── 同步版本（给非异步调用方使用）──────────
    def run_sync(
        self,
        command: str,
        confirm_callback: Optional[Callable[[RiskResult], bool]] = None,
    ) -> ExecutionResult:
        return asyncio.run(self.run(command, confirm_callback))

    # ── 工具方法 ──────────────────────────────
    def _truncate(self, text: str) -> str:
        encoded = text.encode("utf-8")
        if len(encoded) > self.max_output_bytes:
            truncated = encoded[: self.max_output_bytes].decode("utf-8", errors="ignore")
            return truncated + f"\n... [输出已截断，超过 {self.max_output_bytes // 1024}KB 上限]"
        return text

    @property
    def history(self) -> List[ExecutionResult]:
        return list(self._history)

    def clear_history(self):
        self._history.clear()


# ─────────────────────────────────────────────
#  SSH 远程执行扩展
# ─────────────────────────────────────────────
class SSHExecutor(CommandExecutor):
    """
    通过 SSH 在远程 Linux 服务器执行命令
    依赖：pip install asyncssh
    """

    def __init__(self, host: str, username: str, key_path: str = None, password: str = None, **kwargs):
        super().__init__(**kwargs)
        self.host = host
        self.username = username
        self.key_path = key_path
        self.password = password
        self._conn = None

    async def connect(self):
        try:
            import asyncssh
            connect_kwargs = {
                "host": self.host,
                "username": self.username,
                "known_hosts": None,
            }
            if self.key_path:
                connect_kwargs["client_keys"] = [self.key_path]
            if self.password:
                connect_kwargs["password"] = self.password
            self._conn = await asyncssh.connect(**connect_kwargs)
        except ImportError:
            raise RuntimeError("请安装 asyncssh：pip install asyncssh")

    async def disconnect(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    async def _execute(self, command: str, risk: RiskResult, confirmed: bool, env: dict = None) -> ExecutionResult:
        if self._conn is None:
            await self.connect()

        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._conn.run(command, timeout=self.timeout),
                timeout=self.timeout + 5,
            )
            elapsed = time.monotonic() - start
            return ExecutionResult(
                command=command,
                stdout=self._truncate(result.stdout or ""),
                stderr=self._truncate(result.stderr or ""),
                returncode=result.exit_status,
                elapsed=elapsed,
                risk=risk,
                confirmed=confirmed,
            )
        except Exception as e:
            elapsed = time.monotonic() - start
            return ExecutionResult(
                command=command,
                stdout="",
                stderr="",
                returncode=-1,
                elapsed=elapsed,
                risk=risk,
                confirmed=confirmed,
                error=str(e),
            )


# ─────────────────────────────────────────────
#  简单测试
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio

    def cli_confirm(risk: RiskResult) -> bool:
        print(f"\n⚠️  危险操作确认")
        print(f"  命令：{risk.command}")
        print(f"  原因：{risk.reason}")
        if risk.suggestion:
            print(f"  建议：{risk.suggestion}")
        ans = input("  是否继续执行？(yes/no): ").strip().lower()
        return ans in ("yes", "y", "是")

    async def test():
        executor = CommandExecutor()
        cmds = [
            "df -h",
            "ls /tmp",
            "useradd testuser123",
            "rm -rf /tmp/testdir",
        ]
        for cmd in cmds:
            print(f"\n执行：{cmd}")
            result = await executor.run(cmd, confirm_callback=cli_confirm)
            if result.blocked:
                print(f"  [拦截] {result.error}")
            elif result.success:
                print(f"  [成功] {result.stdout[:200]}")
            else:
                print(f"  [失败] rc={result.returncode} {result.stderr[:200]}")

    asyncio.run(test())
