"""
风控引擎 (Risk Control Engine)
主力B - Day1/Day2 核心模块

功能：对 Agent 准备执行的命令进行风险分级与拦截
风险等级：
  SAFE    - 只读查询，直接执行
  WARN    - 有副作用但可控，需展示说明
  DANGER  - 高风险操作，需用户二次确认
  BLOCK   - 禁止执行，直接拒绝
"""

import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


class RiskLevel(Enum):
    SAFE = "safe"
    WARN = "warn"
    DANGER = "danger"
    BLOCK = "block"


RISK_COLORS = {
    RiskLevel.SAFE: "green",
    RiskLevel.WARN: "yellow",
    RiskLevel.DANGER: "red",
    RiskLevel.BLOCK: "bright_red",
}

RISK_LABELS = {
    RiskLevel.SAFE:   "✅ 安全",
    RiskLevel.WARN:   "⚠️  警告",
    RiskLevel.DANGER: "🔴 危险",
    RiskLevel.BLOCK:  "🚫 拒绝",
}


@dataclass
class RiskRule:
    name: str
    level: RiskLevel
    patterns: List[str]           # 正则模式列表（匹配命令字符串）
    reason: str                   # 风险说明
    suggestion: str = ""          # 替代建议
    tags: List[str] = field(default_factory=list)


@dataclass
class RiskResult:
    level: RiskLevel
    rule_name: str
    reason: str
    suggestion: str
    matched_pattern: str
    command: str

    @property
    def requires_confirmation(self) -> bool:
        return self.level == RiskLevel.DANGER

    @property
    def is_blocked(self) -> bool:
        return self.level == RiskLevel.BLOCK

    @property
    def is_allowed(self) -> bool:
        return self.level in (RiskLevel.SAFE, RiskLevel.WARN)

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "rule_name": self.rule_name,
            "reason": self.reason,
            "suggestion": self.suggestion,
            "command": self.command,
        }


# ─────────────────────────────────────────────
#  规则库
# ─────────────────────────────────────────────
RULES: List[RiskRule] = [

    # ── BLOCK 级别：绝对禁止 ──────────────────
    RiskRule(
        name="fork_bomb",
        level=RiskLevel.BLOCK,
        patterns=[r":\(\)\s*\{.*\}", r"fork\s*bomb"],
        reason="检测到 Fork Bomb，执行将导致系统资源耗尽崩溃",
        suggestion="请描述您真正需要完成的任务",
        tags=["dos", "destructive"],
    ),
    RiskRule(
        name="rm_root",
        level=RiskLevel.BLOCK,
        patterns=[
            r"\brm\b.*-[a-z]*r[a-z]*f[a-z]*\s+/\s*$",
            r"\brm\b.*-[a-z]*f[a-z]*r[a-z]*\s+/\s*$",
            r"\brm\b.*--no-preserve-root",
        ],
        reason="禁止删除根目录，此操作将摧毁整个系统",
        suggestion="请明确指定要清理的目标目录",
        tags=["destructive", "filesystem"],
    ),
    RiskRule(
        name="disk_wipe",
        level=RiskLevel.BLOCK,
        patterns=[
            r"\bdd\b.*of=/dev/(sda|vda|nvme|hda)\b(?!.*seek)",
            r"\bshred\b.*/dev/(sda|vda|nvme)",
            r"\bwipefs\b",
        ],
        reason="检测到磁盘擦除操作，将永久销毁数据",
        suggestion="如需清理磁盘分区，请先确认目标分区和备份状态",
        tags=["destructive", "disk"],
    ),
    RiskRule(
        name="kernel_module_dangerous",
        level=RiskLevel.BLOCK,
        patterns=[r"\brmmod\b.*-f\b", r"\bmodprobe\b.*-r\b.*-f\b"],
        reason="强制卸载内核模块可能导致系统崩溃",
        suggestion="请先检查模块依赖：lsmod | grep <模块名>",
        tags=["kernel", "destructive"],
    ),

    # ── DANGER 级别：需要二次确认 ─────────────
    RiskRule(
        name="rm_recursive_system_dirs",
        level=RiskLevel.DANGER,
        patterns=[
            r"\brm\b.*-[a-z]*r[a-z]*\s+/(etc|usr|lib|bin|sbin|boot|var|home|root)\b",
            r"\brm\b.*-[a-z]*r[a-z]*\s+~\b",
        ],
        reason="递归删除系统核心目录，将造成不可恢复的损坏",
        suggestion="请仅删除明确的子目录，并先用 ls 确认内容",
        tags=["destructive", "filesystem"],
    ),
    RiskRule(
        name="rm_recursive_force",
        level=RiskLevel.DANGER,
        patterns=[r"\brm\b.*-[a-z]*r[a-z]*f[a-z]*\s+\S+", r"\brm\b.*-[a-z]*f[a-z]*r[a-z]*\s+\S+"],
        reason="强制递归删除操作，文件将无法恢复",
        suggestion="建议先用 ls -la <路径> 确认内容，再使用 trash-put 替代",
        tags=["destructive", "filesystem"],
    ),
    RiskRule(
        name="chmod_recursive_777",
        level=RiskLevel.DANGER,
        patterns=[r"\bchmod\b.*-[Rr]\b.*777\b", r"\bchmod\b.*777\b.*/\b"],
        reason="递归赋予777权限将使目录完全可写，存在严重安全隐患",
        suggestion="请使用最小权限原则，仅对需要的文件设置权限",
        tags=["permissions", "security"],
    ),
    RiskRule(
        name="user_del",
        level=RiskLevel.DANGER,
        patterns=[r"\buserdel\b", r"\bdeluser\b.*--remove-home"],
        reason="删除用户账号及其主目录",
        suggestion="建议先锁定账号：usermod -L <username>，确认后再删除",
        tags=["user_management"],
    ),
    RiskRule(
        name="passwd_root",
        level=RiskLevel.DANGER,
        patterns=[r"\bpasswd\b\s+root\b", r"\bchpasswd\b.*root"],
        reason="修改 root 账号密码",
        suggestion="请确认您有权限执行此操作",
        tags=["user_management", "security"],
    ),
    RiskRule(
        name="firewall_disable",
        level=RiskLevel.DANGER,
        patterns=[
            r"\bsystemctl\b.*(stop|disable)\b.*(firewalld|ufw|iptables)",
            r"\bufw\b\s+disable\b",
            r"\biptables\b.*-F\b",
        ],
        reason="关闭防火墙将使系统暴露于网络威胁",
        suggestion="请确认是否有其他安全措施，或仅开放必要端口",
        tags=["security", "network"],
    ),
    RiskRule(
        name="selinux_disable",
        level=RiskLevel.DANGER,
        patterns=[r"\bsetenforce\b\s+0\b", r"SELINUX=disabled"],
        reason="禁用 SELinux 会移除强制访问控制保护",
        suggestion="如需临时关闭，建议使用 permissive 模式而非完全禁用",
        tags=["security"],
    ),
    RiskRule(
        name="crontab_danger",
        level=RiskLevel.DANGER,
        patterns=[r"\bcrontab\b.*-r\b"],
        reason="删除所有定时任务",
        suggestion="使用 crontab -l 先查看现有任务，再决定是否删除",
        tags=["scheduler"],
    ),
    RiskRule(
        name="kill_all",
        level=RiskLevel.DANGER,
        patterns=[r"\bkillall\b\s+-9\b", r"\bpkill\b.*-9\b.*-u\s+root"],
        reason="强制终止多个进程可能导致数据丢失或服务中断",
        suggestion="先用 ps/pgrep 确认目标进程，再进行单独终止",
        tags=["process"],
    ),
    RiskRule(
        name="sudoers_edit",
        level=RiskLevel.DANGER,
        patterns=[r"\bvisudo\b", r"echo.*>>\s*/etc/sudoers", r"\bchmod\b.*sudoers"],
        reason="修改 sudo 权限配置，可能导致权限提升漏洞",
        suggestion="使用 visudo 进行安全编辑，避免直接写入文件",
        tags=["security", "permissions"],
    ),
    RiskRule(
        name="ssh_config_edit",
        level=RiskLevel.DANGER,
        patterns=[
            r">\s*/etc/ssh/sshd_config",
            r"\bsed\b.*-i.*sshd_config",
            r"PermitRootLogin\s+yes",
            r"PasswordAuthentication\s+yes",
        ],
        reason="修改 SSH 配置影响远程访问安全性",
        suggestion="修改前备份：cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak",
        tags=["security", "ssh"],
    ),
    RiskRule(
        name="package_remove_critical",
        level=RiskLevel.DANGER,
        patterns=[
            r"\b(apt|yum|dnf|zypper)\b.*remove.*\b(openssh|sudo|systemd|glibc|kernel)\b",
            r"\b(apt|yum|dnf)\b.*purge\b",
        ],
        reason="删除关键系统软件包可能导致系统不可用",
        suggestion="请确认软件包依赖关系后再操作",
        tags=["package_management"],
    ),

    # ── WARN 级别：提醒用户注意 ───────────────
    RiskRule(
        name="service_stop",
        level=RiskLevel.WARN,
        patterns=[r"\bsystemctl\b\s+stop\b", r"\bservice\b.*stop\b"],
        reason="停止系统服务可能影响依赖该服务的应用",
        suggestion="停止前请确认服务名称和依赖关系",
        tags=["service"],
    ),
    RiskRule(
        name="useradd",
        level=RiskLevel.WARN,
        patterns=[r"\buseradd\b", r"\badduser\b"],
        reason="创建新用户账号",
        suggestion="请确认用户名和权限组设置",
        tags=["user_management"],
    ),
    RiskRule(
        name="chmod_sensitive",
        level=RiskLevel.WARN,
        patterns=[r"\bchmod\b.*\b(600|700|755|644)\b.*/etc/"],
        reason="修改系统配置文件权限",
        suggestion="请确认目标文件和新权限的正确性",
        tags=["permissions"],
    ),
    RiskRule(
        name="network_config",
        level=RiskLevel.WARN,
        patterns=[
            r"\bip\b.*\b(link|addr|route)\b.*\b(add|del|set)\b",
            r"\bifconfig\b",
            r"\bnmcli\b.*\b(con|device)\b.*\b(add|del|modify)\b",
        ],
        reason="修改网络配置可能导致连接中断",
        suggestion="远程操作前请确认有备用连接方式",
        tags=["network"],
    ),
    RiskRule(
        name="package_install",
        level=RiskLevel.WARN,
        patterns=[r"\b(apt|yum|dnf|zypper|pip3?)\b.*install\b"],
        reason="安装软件包会修改系统状态",
        suggestion="请确认软件来源可信，建议在测试环境先验证",
        tags=["package_management"],
    ),
    RiskRule(
        name="cron_add",
        level=RiskLevel.WARN,
        patterns=[r"\bcrontab\b.*-e\b", r"cron\.(daily|weekly|monthly|d)"],
        reason="添加定时任务将在后台周期性执行命令",
        suggestion="请明确任务执行时间和目的",
        tags=["scheduler"],
    ),
]


class RiskEngine:
    """风控规则引擎"""

    def __init__(self, rules: List[RiskRule] = None):
        self.rules = rules or RULES
        self._compiled = [
            (rule, [re.compile(p, re.IGNORECASE) for p in rule.patterns])
            for rule in self.rules
        ]

    def evaluate(self, command: str) -> RiskResult:
        """
        对命令进行风险评估，返回最高风险等级的结果。
        优先级：BLOCK > DANGER > WARN > SAFE
        """
        command = command.strip()
        best: Optional[Tuple[RiskRule, str]] = None
        best_level_value = -1

        level_order = {
            RiskLevel.SAFE: 0,
            RiskLevel.WARN: 1,
            RiskLevel.DANGER: 2,
            RiskLevel.BLOCK: 3,
        }

        for rule, compiled_patterns in self._compiled:
            for pattern in compiled_patterns:
                if pattern.search(command):
                    lv = level_order[rule.level]
                    if lv > best_level_value:
                        best_level_value = lv
                        best = (rule, pattern.pattern)
                    break  # 同一规则只匹配一次

        if best is None:
            return RiskResult(
                level=RiskLevel.SAFE,
                rule_name="default",
                reason="命令通过风险检查",
                suggestion="",
                matched_pattern="",
                command=command,
            )

        rule, matched_pattern = best
        return RiskResult(
            level=rule.level,
            rule_name=rule.name,
            reason=rule.reason,
            suggestion=rule.suggestion,
            matched_pattern=matched_pattern,
            command=command,
        )

    def evaluate_pipeline(self, command: str) -> RiskResult:
        """
        支持管道命令：将管道分割后分别评估，取最高风险
        """
        try:
            parts = [p.strip() for p in re.split(r"[|;&]", command)]
        except Exception:
            parts = [command]

        worst = self.evaluate(command)  # 先整体评估
        level_order = {RiskLevel.SAFE: 0, RiskLevel.WARN: 1, RiskLevel.DANGER: 2, RiskLevel.BLOCK: 3}

        for part in parts:
            result = self.evaluate(part)
            if level_order[result.level] > level_order[worst.level]:
                worst = result

        return worst

    def batch_evaluate(self, commands: List[str]) -> List[RiskResult]:
        return [self.evaluate_pipeline(cmd) for cmd in commands]


# ─────────────────────────────────────────────
#  快速使用
# ─────────────────────────────────────────────
_engine = RiskEngine()


def check(command: str) -> RiskResult:
    """全局快捷评估函数"""
    return _engine.evaluate_pipeline(command)


# ─────────────────────────────────────────────
#  CLI 测试
# ─────────────────────────────────────────────
if __name__ == "__main__":
    test_cases = [
        "df -h",
        "ls -la /home",
        "ps aux | grep nginx",
        "useradd -m testuser",
        "systemctl stop nginx",
        "chmod -R 777 /var/www",
        "rm -rf /etc/nginx",
        "userdel --remove-home john",
        "rm -rf /",
        ":(){ :|:& };:",
        "dd if=/dev/zero of=/dev/sda",
        "iptables -F",
    ]

    print(f"{'命令':<45} {'级别':<10} {'规则'}")
    print("─" * 80)
    for cmd in test_cases:
        r = check(cmd)
        label = RISK_LABELS[r.level]
        print(f"{cmd:<45} {label:<10} {r.rule_name}")
        if r.reason and r.level != RiskLevel.SAFE:
            print(f"  └─ {r.reason}")
