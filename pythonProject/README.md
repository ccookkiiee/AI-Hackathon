# OS 智能代理 - 主力B 模块

## 📁 模块结构

```
os_agent/
├── risk_engine.py    # 风控规则引擎
├── executor.py       # 安全命令执行器
├── tui.py            # 终端 TUI 前端
├── web_app.py        # Streamlit Web 前端
├── agent_bridge.py   # 与主力A的集成接口
└── requirements.txt  # 依赖
```

---

## 🔧 安装依赖

```bash
pip install rich streamlit fastapi uvicorn asyncssh
```

---

## 🚀 快速启动

### TUI 模式
```bash
python tui.py
python tui.py --ssh --host 192.168.1.100
```

### Web 模式
```bash
streamlit run web_app.py
```

### HTTP Bridge（与主力A联调）
```bash
python agent_bridge.py
# 或
uvicorn agent_bridge:app --port 8765
```

---

## 🛡️ 风控规则说明

| 级别   | 说明               | 处理方式         |
|--------|--------------------|-----------------|
| SAFE   | 只读/查询命令      | 直接执行         |
| WARN   | 有副作用但可控     | 展示说明后执行   |
| DANGER | 高风险操作         | 二次确认后执行   |
| BLOCK  | 绝对禁止           | 拒绝，返回原因   |

### 典型拦截场景

- `rm -rf /` → **BLOCK**（销毁根目录）
- `dd if=/dev/zero of=/dev/sda` → **BLOCK**（擦除磁盘）
- `:(){ :|:& };:` → **BLOCK**（Fork Bomb）
- `chmod -R 777 /var/www` → **DANGER**（递归777权限）
- `userdel --remove-home john` → **DANGER**（删除用户）
- `systemctl stop nginx` → **WARN**（停止服务）
- `useradd testuser` → **WARN**（创建用户）
- `df -h` → **SAFE**（只读查询）

---

## 🔗 与主力A对接

**方式1 - 直接调用（推荐，同进程）**

```python
from agent_bridge import AgentBridge

bridge = AgentBridge()
result = await bridge.execute("df -h")
print(result["stdout"])
```

**方式2 - HTTP API（跨进程）**

```python
import httpx

# 主力A 通过 HTTP 调用主力B 的安全执行接口
resp = httpx.post("http://localhost:8765/execute", json={"command": "df -h"})
data = resp.json()
print(data["stdout"])
```

**方式3 - 主力A 在工具定义里集成风控检查**

```python
# 主力A 的 tool 定义
async def shell_tool(command: str) -> str:
    result = await bridge.execute(command)
    if result["blocked"]:
        return f"[风控拦截] {result['block_reason']}"
    if result["requires_confirmation"]:
        return f"[需要确认] {result['reason']}"
    return result["stdout"] or result["stderr"]
```


