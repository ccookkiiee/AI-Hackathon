# tui.py
import asyncio
from typing import List
import platform
from executor import CommandExecutor
from risk_engine import check, RiskLevel, RISK_LABELS, RiskResult


class AgentTUI:
    """
    终端版 Linux 智能代理

    功能：
    - 自然语言映射到常用系统命令
    - 支持直接输入 shell 命令
    - 执行前风险评估
    - DANGER 命令二次确认
    - 历史记录查看
    """

    def __init__(self):
        self.executor = CommandExecutor(timeout=30)
        self.running = True

    # ─────────────────────────────────────────────
    #  对外入口
    # ─────────────────────────────────────────────
    def run(self):
        def run(self):
            import platform

            system = platform.system()

            if system == "Windows":
                print("⚠️ 当前系统：Windows")
                print("❌ 无法直接执行 Linux 命令")
                print("👉 推荐方案：")
                print("   1. 使用 WSL")
                print("   2. 使用 SSH 连接 Linux 服务器\n")

            elif system == "Linux":
                print("✅ 当前系统：Linux，命令可正常执行\n")

            else:
                print(f"⚠️ 未知系统：{system}\n")
        self._print_banner()

        while self.running:
            try:
                user_input = input("\nagent> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\n已退出。")
                break

            if not user_input:
                continue

            if self._handle_builtin(user_input):
                continue

            commands = self._process_intent(user_input)
            if not commands:
                print("未识别输入，请输入 :help 查看帮助。")
                continue

            if len(commands) > 1:
                print(f"\n将顺序执行 {len(commands)} 条命令：")
                for i, cmd in enumerate(commands, 1):
                    print(f"  {i}. {cmd}")

            for cmd in commands:
                should_continue = self._run_command_sync(cmd)
                if not should_continue:
                    break

    # ─────────────────────────────────────────────
    #  内建命令
    # ─────────────────────────────────────────────
    def _handle_builtin(self, text: str) -> bool:
        cmd = text.lower()

        if cmd in (":q", ":quit", "exit", "quit"):
            self.running = False
            print("已退出。")
            return True

        if cmd in (":help", "help", "?"):
            self._print_help()
            return True

        if cmd == ":history":
            self._print_history()
            return True

        if cmd == ":clear":
            self.executor.clear_history()
            print("历史已清空。")
            return True

        return False

    # ─────────────────────────────────────────────
    #  自然语言 → 命令
    # ─────────────────────────────────────────────
    def _process_intent(self, user_text: str) -> List[str]:
        demos = {
            "磁盘": ["df -h","du -h --max-depth=1 / 2>/dev/null | sort -hr | head -10"],
            "内存": ["free -h"],
            "进程": ["ps aux --sort=-%cpu | head -15"],
            "端口": ["ss -tlnp"],
            "用户": ["awk -F: '$3>=1000{print $1,$3,$7}' /etc/passwd"],
            "网络": ["ip addr show", "ss -s"],
            "负载": ["uptime", "top -bn1 | head -5"],
            "日志": ["journalctl -n 50 --no-pager"],
            "服务": ["systemctl list-units --type=service --state=running"],
        }

        for kw, cmds in demos.items():
            if kw in user_text:
                return cmds

        stripped = user_text.strip()
        if stripped:
            return [stripped]

        return []

    # ─────────────────────────────────────────────
    #  执行单条命令
    # ─────────────────────────────────────────────
    def _run_command_sync(self, cmd: str) -> bool:
        if platform.system() == "Windows" and cmd.startswith(("ps", "df", "grep", "top", "ss")):
            print("❌ 当前为 Windows，无法执行 Linux 命令")
            print("👉 推荐方案：")
            print("   1. 使用 WSL")
            print("   2. 使用 SSH 连接 Linux 服务器\n")
            return False
        risk = check(cmd)
        self._print_risk(cmd, risk)

        if risk.level == RiskLevel.BLOCK:
            print(f"🚫 已拦截：{risk.reason}")
            if risk.suggestion:
                print(f"💡 建议：{risk.suggestion}")
            return False

        if risk.level == RiskLevel.DANGER:
            ans = input("该操作为危险命令，是否继续？(yes/no): ").strip().lower()
            if ans not in ("yes", "y", "是"):
                print("已取消。")
                return False

            result = asyncio.run(
                self.executor.run(cmd, confirm_callback=lambda r: True)
            )
        else:
            result = asyncio.run(self.executor.run(cmd))

        self._print_result(result)
        return True

    # ─────────────────────────────────────────────
    #  输出
    # ─────────────────────────────────────────────
    def _print_banner(self):
        print("=" * 72)
        print("🖥️  Linux 系统智能代理 - TUI")
        print("=" * 72)
        print("输入自然语言或直接输入 shell 命令。")
        print("例如：查看磁盘使用情况 / 查看内存 / ps aux | grep nginx")
        print("输入 :help 查看帮助，:quit 退出。")

    def _print_help(self):
        print("\n可用命令：")
        print("  :help      查看帮助")
        print("  :history   查看执行历史")
        print("  :clear     清空执行历史")
        print("  :quit      退出")
        print("\n支持的快捷中文意图：")
        print("  查看磁盘 / 查看内存 / 查看进程 / 查看端口 / 查看用户")
        print("  查看网络 / 查看负载 / 查看日志 / 查看服务")
        print("\n也可以直接输入 shell 命令，例如：")
        print("  df -h")
        print("  ps aux | grep nginx")
        print("  systemctl stop nginx")

    def _print_risk(self, cmd: str, risk: RiskResult):
        print("\n" + "-" * 72)
        print(f"$ {cmd}")
        print(f"风险等级：{RISK_LABELS[risk.level]}")
        if risk.reason:
            print(f"原因：{risk.reason}")
        if risk.suggestion:
            print(f"建议：{risk.suggestion}")
        print("-" * 72)

    def _print_result(self, result):
        status = "成功" if result.success else "失败"
        print(f"\n[{status}] rc={result.returncode}  elapsed={result.elapsed:.2f}s")

        if result.error:
            print(f"错误：{result.error}")

        if result.stdout:
            print("\n--- STDOUT ---")
            print(result.stdout.rstrip())

        if result.stderr:
            print("\n--- STDERR ---")
            print(result.stderr.rstrip())

        if not result.stdout and not result.stderr and not result.error:
            print("(无输出)")

    def _print_history(self):
        history = self.executor.history
        if not history:
            print("暂无历史记录。")
            return

        print(f"\n历史记录（共 {len(history)} 条）：")
        for i, item in enumerate(history, 1):
            status = "SUCCESS" if item.success else ("BLOCKED" if item.blocked else "FAILED")
            print(
                f"{i:>3}. [{status}] "
                f"risk={item.risk.level.value:<6} "
                f"rc={item.returncode:<3} "
                f"cmd={item.command}"
            )