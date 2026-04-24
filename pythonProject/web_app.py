"""
Web 前端 (Streamlit)
主力B - Day3 模块

功能：
  - 聊天式对话界面
  - 实时风险评估可视化
  - 二次确认弹窗
  - 执行历史面板
  - 语音输入（HTML5 Web Speech API）

依赖：pip install streamlit
运行：streamlit run web_app.py
"""

import asyncio
import time
from datetime import datetime
from typing import List

import streamlit as st

from risk_engine import RiskLevel, RiskResult, check, RISK_LABELS
from executor import CommandExecutor, ExecutionResult


# ─────────────────────────────────────────────
#  页面配置
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Linux 智能代理",
    page_icon="🖥️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ──────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Noto+Sans+SC:wght@400;600;700&display=swap');

  :root {
    --color-safe:   #22c55e;
    --color-warn:   #f59e0b;
    --color-danger: #ef4444;
    --color-block:  #7f1d1d;
    --bg-dark:      #0f172a;
    --bg-card:      #1e293b;
    --text-main:    #f8fafc;
    --accent:       #38bdf8;
  }

  html, body, [data-testid="stAppViewContainer"] {
    background-color: var(--bg-dark) !important;
    color: var(--text-main);
    font-family: 'Noto Sans SC', sans-serif;
  }

  .chat-bubble-user {
    background: linear-gradient(135deg, #1e3a5f, #1e40af);
    border-radius: 16px 16px 4px 16px;
    padding: 14px 18px;
    margin: 8px 0 8px auto;
    max-width: 80%;
    color: #e0f2fe;
    font-size: 15px;
    border: 1px solid #3b82f6;
    line-height: 1.6;
  }

  .chat-bubble-agent {
    background: var(--bg-card);
    border-radius: 16px 16px 16px 4px;
    padding: 14px 18px;
    margin: 8px auto 8px 0;
    max-width: 90%;
    border: 1px solid #334155;
    font-size: 14px;
    color: #f1f5f9;
    line-height: 1.6;
  }

  .risk-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
  }
  .risk-safe   { background: #14532d; color: var(--color-safe); }
  .risk-warn   { background: #451a03; color: var(--color-warn); }
  .risk-danger { background: #450a0a; color: var(--color-danger); }
  .risk-block  { background: #7f1d1d; color: #fca5a5; }

  .cmd-block {
    background: #020617;
    border-left: 3px solid var(--accent);
    border-radius: 4px;
    padding: 10px 14px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    color: #7dd3fc;
    margin: 8px 0;
  }

  .output-block {
    background: #020617;
    border-radius: 6px;
    padding: 12px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: #a3e635;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 300px;
    overflow-y: auto;
    margin-top: 6px;
  }

  .output-error {
    color: #f87171;
  }

  .meta-line {
    font-size: 11px;
    color: #94a3b8;
    margin-top: 4px;
  }

  [data-testid="stSidebar"] {
    background: #0f172a !important;
    border-right: 1px solid #1e293b;
  }

  [data-testid="stSidebar"] * {
    color: #e5e7eb !important;
  }

  [data-testid="stSidebar"] .stCaption {
    color: #cbd5e1 !important;
  }

  [data-testid="stSidebar"] label,
  [data-testid="stSidebar"] p,
  [data-testid="stSidebar"] div {
    font-weight: 500;
  }

  .stTextInput > div > div > input {
    background: #1e293b !important;
    color: #f8fafc !important;
    border: 1px solid #475569 !important;
    border-radius: 8px;
    font-family: 'Noto Sans SC', sans-serif;
  }

  .voice-btn {
    background: linear-gradient(135deg, #0ea5e9, #2563eb);
    color: white;
    border: none;
    border-radius: 50%;
    width: 44px;
    height: 44px;
    font-size: 20px;
    cursor: pointer;
    transition: all 0.2s;
    box-shadow: 0 4px 12px rgba(14,165,233,0.3);
  }
  .voice-btn:hover { transform: scale(1.1); }
  .voice-btn.recording {
    background: linear-gradient(135deg, #ef4444, #dc2626);
    animation: pulse 1s infinite;
  }

  @keyframes pulse {
    0%, 100% { box-shadow: 0 4px 12px rgba(239,68,68,0.3); }
    50%      { box-shadow: 0 4px 24px rgba(239,68,68,0.6); }
  }

  .fixed-input-bar {
    position: sticky;
    top: 0;
    z-index: 999;
    background: rgba(15, 23, 42, 0.96);
    backdrop-filter: blur(8px);
    padding: 14px 0 12px 0;
    border-bottom: 1px solid #1e293b;
    margin-bottom: 12px;
  }

  .chat-list-wrap {
    padding-top: 4px;
  }

  .block-container {
    padding-top: 1rem;
  }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  状态初始化
# ─────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_confirm" not in st.session_state:
    st.session_state.pending_confirm = None
if "executor" not in st.session_state:
    st.session_state.executor = CommandExecutor(timeout=30)


# ─────────────────────────────────────────────
#  侧边栏
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🖥️ OS 智能代理")
    st.markdown("---")

    mode = st.selectbox("执行模式", ["本地", "SSH 远程"])
    if mode == "SSH 远程":
        ssh_host = st.text_input("主机", "192.168.1.100")
        ssh_user = st.text_input("用户名", "root")
        ssh_key = st.text_input("密钥路径", "~/.ssh/id_rsa")

    st.markdown("---")
    st.markdown("#### 风险等级说明")
    for level, label in RISK_LABELS.items():
        css_cls = f"risk-{level.value}"
        st.markdown(f'<span class="risk-badge {css_cls}">{label}</span>', unsafe_allow_html=True)
        descriptions = {
            RiskLevel.SAFE:   "只读查询，自动执行",
            RiskLevel.WARN:   "有副作用，展示说明",
            RiskLevel.DANGER: "高风险，需二次确认",
            RiskLevel.BLOCK:  "禁止执行，直接拒绝",
        }
        st.caption(descriptions[level])

    st.markdown("---")
    if st.button("🗑️ 清空对话"):
        st.session_state.messages = []
        st.rerun()

    st.markdown("---")
    st.markdown("#### 执行统计")
    history = st.session_state.executor.history
    total = len(history)
    success = sum(1 for r in history if r.success)
    blocked = sum(1 for r in history if r.blocked)
    col1, col2, col3 = st.columns(3)
    col1.metric("总计", total)
    col2.metric("成功", success, delta=None)
    col3.metric("拦截", blocked)


# ─────────────────────────────────────────────
#  核心函数
# ─────────────────────────────────────────────
def _risk_badge(risk: RiskResult) -> str:
    css_cls = f"risk-{risk.level.value}"
    label = RISK_LABELS[risk.level]
    return f'<span class="risk-badge {css_cls}">{label}</span>'


def _run_command(cmd: str, confirmed: bool = False):
    """执行单条命令并将结果追加到消息历史"""
    risk = check(cmd)
    badge = _risk_badge(risk)

    # BLOCK
    if risk.is_blocked:
        html = f"""
        <div>
          {badge} 命令已被拦截<br>
          <div class="cmd-block">$ {cmd}</div>
          <div class="output-block output-error">🚫 {risk.reason}</div>
          {f'<div class="meta-line">💡 {risk.suggestion}</div>' if risk.suggestion else ""}
        </div>
        """
        st.session_state.messages.append({"role": "agent", "content": html})
        st.rerun()
        return

    # DANGER（未确认）
    if risk.requires_confirmation and not confirmed:
        st.session_state.pending_confirm = {"cmd": cmd, "risk": risk}
        st.rerun()
        return

    # 执行
    with st.spinner(f"执行中：{cmd[:50]}..."):
        result = asyncio.run(
            st.session_state.executor.run(cmd, confirm_callback=lambda r: True)
        )

    output_cls = "" if result.success else "output-error"
    output_text = (result.stdout or result.stderr or "(无输出)").strip()
    rc_label = f"✅ rc=0  {result.elapsed:.2f}s" if result.success else f"❌ rc={result.returncode}  {result.elapsed:.2f}s"

    html = f"""
    <div>
      {badge} &nbsp;
      <span class="meta-line">{rc_label}</span><br>
      <div class="cmd-block">$ {cmd}</div>
      <div class="output-block {output_cls}">{output_text[:3000]}</div>
    </div>
    """
    st.session_state.messages.append({"role": "agent", "content": html})
    st.rerun()


def _process_intent(user_text: str) -> List[str]:
    """
    意图解析 → 命令列表
    TODO: 替换为主力A的 Agent 接口调用
    """
    demos = {
        "磁盘": ["df -h", "du -sh /* 2>/dev/null | sort -hr | head -10"],
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

    # 直接把输入当命令
    stripped = user_text.strip()
    if stripped:
        return [stripped]
    return []


# ─────────────────────────────────────────────
#  语音输入组件
# ─────────────────────────────────────────────
VOICE_INPUT_HTML = """
<div style="display:flex; align-items:center; gap:10px; margin:8px 0;">
  <button class="voice-btn" id="voiceBtn" onclick="toggleVoice()" title="语音输入">🎤</button>
  <span id="voiceStatus" style="color:#64748b; font-size:13px;">点击开始语音输入</span>
</div>

<script>
let recognition = null;
let isRecording = false;

function toggleVoice() {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    document.getElementById('voiceStatus').innerText = '浏览器不支持语音识别';
    return;
  }
  if (isRecording) {
    recognition.stop();
    return;
  }
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.lang = 'zh-CN';
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onstart = () => {
    isRecording = true;
    document.getElementById('voiceBtn').classList.add('recording');
    document.getElementById('voiceStatus').innerText = '🔴 正在录音...';
  };
  recognition.onresult = (e) => {
    const transcript = e.results[0][0].transcript;
    document.getElementById('voiceStatus').innerText = '识别结果：' + transcript;
    // 将结果写入 Streamlit 输入框
    const inputs = window.parent.document.querySelectorAll('input[type=text]');
    if (inputs.length > 0) {
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeInputValueSetter.call(inputs[inputs.length-1], transcript);
      inputs[inputs.length-1].dispatchEvent(new Event('input', {bubbles: true}));
    }
  };
  recognition.onerror = (e) => {
    document.getElementById('voiceStatus').innerText = '识别错误：' + e.error;
  };
  recognition.onend = () => {
    isRecording = false;
    document.getElementById('voiceBtn').classList.remove('recording');
  };
  recognition.start();
}
</script>
"""


# ─────────────────────────────────────────────
#  主界面
# ─────────────────────────────────────────────
st.markdown("# 🖥️ Linux 系统智能代理")
st.markdown('<div class="meta-line">通过自然语言管理您的 Linux 服务器</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  输入区（固定顶部）
# ─────────────────────────────────────────────
st.markdown('<div class="fixed-input-bar">', unsafe_allow_html=True)
st.markdown("### 💬 输入指令")

# 语音按钮（Day3 功能）
with st.expander("🎤 语音输入（实验性）"):
    st.components.v1.html(VOICE_INPUT_HTML, height=60)

col_input, col_btn = st.columns([5, 1])
with col_input:
    user_input = st.text_input(
        label="输入自然语言指令",
        placeholder='例如："查看磁盘使用情况" 或 "ps aux | grep nginx"',
        label_visibility="collapsed",
        key="user_input",
    )
with col_btn:
    send_clicked = st.button("发送 ▶", type="primary", use_container_width=True)

# 快捷指令
st.markdown("**快捷查询：**")
quick_cols = st.columns(6)
quick_cmds = [
    ("💾 磁盘", "查看磁盘使用情况"),
    ("🧠 内存", "查看内存使用"),
    ("⚙️ 进程", "查看进程列表"),
    ("🌐 端口", "查看端口占用"),
    ("👤 用户", "查看系统用户"),
    ("📊 负载", "查看系统负载"),
]
for col, (label, cmd) in zip(quick_cols, quick_cmds):
    if col.button(label, use_container_width=True):
        user_input = cmd
        send_clicked = True

st.markdown('</div>', unsafe_allow_html=True)

# ── 处理提交 ──────────────────────────────────
if send_clicked and user_input:
    # 追加用户消息
    st.session_state.messages.append({"role": "user", "content": user_input})

    commands = _process_intent(user_input)
    if not commands:
        st.session_state.messages.append({
            "role": "agent",
            "content": "未能识别指令，请尝试更明确的描述，例如「查看磁盘」「查看进程」。",
        })
        st.rerun()
    else:
        # 多命令时先告知
        if len(commands) > 1:
            cmds_html = "".join(f'<div class="cmd-block">$ {c}</div>' for c in commands)
            st.session_state.messages.append({
                "role": "agent",
                "content": f"📋 需要执行 {len(commands)} 条命令：{cmds_html}",
            })

        for cmd in commands:
            _run_command(cmd)

# ── 二次确认面板 ──────────────────────────────
if st.session_state.pending_confirm:
    pending = st.session_state.pending_confirm
    risk: RiskResult = pending["risk"]
    cmd: str = pending["cmd"]

    st.warning(f"⚠️ **危险操作确认**")
    st.code(cmd, language="bash")
    st.error(f"**风险原因：** {risk.reason}")
    if risk.suggestion:
        st.info(f"💡 **建议：** {risk.suggestion}")

    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("✅ 确认执行", type="primary", use_container_width=True):
            st.session_state.pending_confirm = None
            # _run_command(cmd, confirmed=True)
    with col_no:
        if st.button("❌ 取消", use_container_width=True):
            st.session_state.pending_confirm = None
            st.session_state.messages.append({
                "role": "agent",
                "content": f"已取消操作：<code>{cmd}</code>",
            })
            st.rerun()

# ── 聊天历史（从上往下排列）──────────────────────
st.markdown('<div class="chat-list-wrap">', unsafe_allow_html=True)
chat_container = st.container()

with chat_container:
    for msg in st.session_state.messages:
        role = msg["role"]
        content = msg["content"]
        html_class = "chat-bubble-user" if role == "user" else "chat-bubble-agent"
        icon = "👤" if role == "user" else "🤖"
        st.markdown(f'<div class="{html_class}">{icon} {content}</div>', unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)