# SteerWX

**在微信里继续电脑上的 ChatGPT 和 Codex 工作。**

*部署在个人电脑上的轻量微信伴侣。*

[English](README.md) | **简体中文**

**通过微信查看 ChatGPT Work、继续讨论本地项目，并显式触发本机 Codex 只读分析。**

```text
微信 → SteerWX → ChatGPT Work / ChatGPT Web / Codex CLI
```

离开电脑后，你仍可在微信中查看 ChatGPT Work 的状态与结果，继续当前项目的 ChatGPT 对话，必要时显式触发本地 Codex 只读分析。手机无需安装额外 App。SteerWX 运行在你自己的 Windows PC 上；源码、日志和长输出留在电脑。使用 ChatGPT 和 Codex 仍须满足各自的地区、账号与网络访问要求。

- **`/work` 负责观察**：查看本地 ChatGPT Work 的状态与结果；
- **`/chat` 负责讨论**：结合轻量本地上下文继续和 ChatGPT 讨论项目，但不会执行代码修改；
- **`/codex` 负责显式分析**：只有明确调用时，才在配置好的项目上启动 Codex CLI 只读分析；
- 详细工作、源码、日志与长输出仍留在电脑上，SteerWX 不要求把开发机直接暴露到公网。

你只需要其中一部分能力时，其余能力可以保持未配置状态。

> **项目状态：v0.2.0 Alpha / Early Stage**
> 当前完整首次安装流程只在 Windows 上完成验证。SteerWX 仍处于早期阶段，不建议作为生产级基础设施使用。腾讯 iLink / 微信 ClawBot 属于外部依赖，其账号、会话、绑定、限频和消息投递行为可能独立变化。

SteerWX 是独立开源项目，与腾讯、微信或 OpenAI 均无隶属、授权或背书关系。

---

## 实际效果

在微信中，可以直接围绕当前本地项目继续讨论：

<p align="center">
  <img src="docs/images/steerwx-wechat-chat-overview.jpg" alt="SteerWX 微信 /chat 实际效果" width="430">
</p>

例如：

```text
/chat 这个项目主要解决什么问题？
```

SteerWX 会让 ChatGPT 在当前项目上下文中回答，而不是把每条微信消息都当成一次完全独立、无上下文的新请求。

更完整的回答示例：

<p align="center">
  <img src="docs/images/steerwx-wechat-chat-details.jpg" alt="SteerWX 微信对话详细效果" width="430">
</p>

---

## 它是怎么工作的

```text
微信 ClawBot
     ↕
 SteerWX
     ├─ /work  → 本地 ChatGPT Work 状态
     ├─ /chat  → ChatGPT Web + 项目上下文
     └─ /codex → 本机 Codex CLI（只读分析）
                    ↓
                 本地项目
```

SteerWX 有意保持明确的命令边界：

- **`/work` 负责观察**：读取本地 Work 的事实、状态和结果；
- **`/chat` 负责讨论**：和 ChatGPT 分析问题、讨论方案、准备 Codex handoff；
- **`/codex` 负责显式执行分析**：只有用户明确输入 `/codex <project> <task>` 时，才启动本地 Codex。

`/chat` 中即使出现“修改代码”“运行测试”“提交代码”或“部署”等内容，也**不会自动执行这些动作**。

SteerWX 不是一个“大而全”的 Agent Framework。它不提供模型路由、RAG、长期记忆或通用工作流编排，也不依赖 QClaw 或 OpenClaw。

---

## 当前能力

| 能力 | 用途 | 依赖 |
|---|---|---|
| `/work` | 查看本地 ChatGPT Work 的事实、状态和结果 | 本地可访问的 Work 状态 |
| `/chat` | 讨论、分析项目，并可准备 Codex handoff | 已登录 ChatGPT Web 的独立 Chrome Profile |
| `/codex` | 显式启动本地 Codex 只读分析 | 已配置项目 + 可用的 Codex CLI |
| Git Context | 按需向 `/chat` 注入只读 Git 信息 | Git 仓库 + Git CLI |
| 微信传输 | 从微信发送命令并接收结果 | 微信 + 腾讯 iLink / 微信 ClawBot |

---

## 环境要求

目前完整首次安装流程只在 **Windows** 上完成验证。Linux 和 macOS 尚未作为已验收平台。

按你需要使用的能力准备依赖：

- Python 3.11 或更高版本；
- Google Chrome：用于独立的 ChatGPT Web Profile；
- ChatGPT Web 账号：仅 `/chat` 需要，SteerWX **不使用 OpenAI API**；
- 微信与腾讯 iLink / 微信 ClawBot：用于微信传输；
- Codex CLI：仅 `/codex` 需要，并需提前完成它自己的认证和配置；
- Git CLI 与 Git 仓库：仅 Git Context 需要；
- 一个或多个本地项目目录；
- 本地可访问的 ChatGPT Work 状态：仅 Work Observer 需要。

仅仅 Clone 仓库并运行 `python -m steerwx run`，并不会自动启用全部能力。例如 `/work` 不依赖 ChatGPT Browser，而 `/chat` 需要。

---

# 快速开始

下面是一套启用当前全部主要能力的首次安装路径。

## 1. 安装 SteerWX

```powershell
git clone https://github.com/samzhou1972/steerwx.git
cd steerwx
python -m pip install -e .
```

先确认 CLI 可用：

```powershell
python -m steerwx --help
```

任何时候都可以运行下面的非破坏性首次安装检查：

```powershell
python -m steerwx doctor
```

Doctor 会把尚未配置的可选能力显示为 `SETUP`，而不是直接判定失败。如果要进一步验证 ChatGPT 浏览器登录状态，再运行 `python -m steerwx chat-browser doctor`。

---

## 2. 配置本地项目

运行时配置位于：

```text
%LOCALAPPDATA%\SteerWX\config.toml
```

将仓库中的 `config.example.toml` 复制到这个位置，然后显式配置允许 SteerWX 使用的项目：

```toml
[projects.steerwx]
root = "C:\\path\\to\\steerwx"
```

这里：

- `steerwx` 是逻辑项目名；
- `root` 是真实本地目录。

`[projects.<name>].root` 是 `/chat` 项目上下文、Git Context、Work 匹配和 `/codex` 的唯一项目路径依据。

在微信中：

```text
/chat use steerwx
```

即可选择这个项目。

之后直接发送普通 `/chat ...` 即可；SteerWX 会自动创建并管理 ChatGPT 对话。用户不需要创建、复制或手工绑定 ChatGPT 对话 URL。

SteerWX 不会扫描整块磁盘来猜测你的项目，也不要把个人运行配置、凭据或浏览器 Profile 提交到 Git。

---

## 3. 绑定微信 ClawBot

SteerWX 使用腾讯 iLink / 微信 ClawBot 作为传输层，而不是普通的 WeChat Web API。

开始绑定：

```powershell
python -m steerwx login
```

终端会请求并显示绑定二维码。然后：

1. 用手机微信扫码；
2. 如果微信显示数字验证码，在终端中输入；
3. 完成 ClawBot 绑定；
4. 凭据只保存在本地运行环境中，不要提交到 Git。

---

## 4. 验证微信传输

先运行最小 M0 smoke test：

```powershell
python -m steerwx echo
```

然后在微信 ClawBot 中发送：

```text
hello
```

预期回复：

```text
world
```

这一步只验证：

```text
微信 ↔ 腾讯 iLink ↔ SteerWX
```

建议先确保它正常，再排查 ChatGPT、Work 或 Codex。

> 注意：接口返回发送成功，只表示请求被服务端接受，并不必然意味着消息已经真正到达微信客户端。详见后面的“外部服务限制”。

---

## 5. 准备 ChatGPT Browser

SteerWX 使用独立的 Chrome Profile：

```text
%LOCALAPPDATA%\SteerWX\browser\chrome-profile
```

执行一次登录初始化：

```powershell
python -m steerwx chat-browser setup
```

该命令会使用上述 Profile 启动系统 Chrome。

在打开的浏览器窗口中：

1. 手工登录 `chatgpt.com`；
2. 确认 ChatGPT 可以正常使用；
3. 关闭该 Chrome 窗口。

登录状态会保存在这个独立 Profile 中。

SteerWX 不会要求、收集或保存你的 ChatGPT 密码。

> 你平时使用的 Chrome 或 Edge 已经登录 ChatGPT，并不代表 SteerWX 的独立 Profile 已登录。SteerWX 不使用你的日常 Edge Profile，也不依赖浏览器扩展。

---

## 6. 验证 ChatGPT Browser

关闭刚才用于登录的 Chrome 后运行：

```powershell
python -m steerwx chat-browser doctor
```

环境正常时，Chrome executable、Profile directory、browser launch、ChatGPT reachability、ChatGPT session、page readiness 和 composer 等检查应显示 `PASS`。

然后执行端到端检查：

```powershell
python -m steerwx chat-browser doctor --send
```

成功时会返回：

```text
STEERWX_BROWSER_OK
```

首次配置时，不建议直接拿 `/chat` 当浏览器诊断工具。

---

## 7. 准备 Codex CLI（可选）

如果你需要 `/codex`，请单独安装并完成 Codex CLI 自身的认证与配置。

SteerWX 的 `/codex` 会对已配置项目显式运行只读分析：

```text
codex exec --sandbox read-only
```

SteerWX 不提供 Codex/OpenAI 账号，也不会把 `/chat` 中的普通讨论隐式转成 `/codex` 执行。

---

## 8. 启动 SteerWX

```powershell
python -m steerwx run
```

这是一个持续运行的 Bridge 进程。PowerShell 窗口停止后，SteerWX 也会停止。

如果微信没有收到回复，首先确认这个进程仍在运行。

---

## 首次安装检查清单

开始使用 `/chat`：

1. 安装 SteerWX；
2. 在 `%LOCALAPPDATA%\SteerWX\config.toml` 中配置至少一个本地项目；
3. 运行 `python -m steerwx login` 绑定微信；
4. 运行 `python -m steerwx chat-browser setup`，在专用 Chrome 中登录 ChatGPT，然后关闭该窗口；
5. 运行 `python -m steerwx run`；
6. 在微信中发送 `/chat use <project>`，例如 `/chat use steerwx`；
7. 直接发送普通 `/chat ...`；SteerWX 会自动创建并管理 ChatGPT 对话。

如遇问题，可用 `python -m steerwx echo` 检查微信传输，用 `python -m steerwx chat-browser doctor` 检查浏览器。`doctor --send` 是可选的浏览器测试；只有显式使用 `/codex` 才需要配置 Codex CLI。

---

# 微信命令

| 命令 | 作用 |
|---|---|
| `/work status` | 查看最新 Work 状态 |
| `/work last` | 查看最近一次 Work 活动 |
| `/work result` | 查看最近一次 Work 结果 |
| `/work watch` | 当一个完整任务首次进入 `COMPLETE` 时发送一次简短通知 |
| `/work unwatch` | 关闭 Work 完成通知 |
| `/codex <project> <task>` | 对已配置项目显式启动只读 Codex 分析 |
| `/chat use <project>` | 为后续 `/chat` 选择已配置的本地项目 |
| `/chat <message>` | 和 ChatGPT 讨论或分析，不执行代码修改 |
| `/chat status` | 查看本地 Chat Session 状态 |
| `/chat reset` | 结束当前 ChatGPT 对话，保留项目绑定；下一条 `/chat` 自动开始新对话 |

---

# 微信消息策略

SteerWX 把微信定位为：

**控制入口 + 短摘要 + 完成提醒**

而不是长日志输出通道。

当前策略包括：

- 一次业务响应通常最多发送一条微信消息；
- outbound hard cap 为 1000 个 Unicode 字符；
- 不自动进行多段编号消息切分；
- `/chat` 默认要求 ChatGPT 返回短摘要；
- 1000 字符以内的 Codex handoff 会完整返回；
- 超过 1000 字符的 Codex handoff 不会被截断或拆分，而会提示用户回到电脑继续查看；
- 完整报告、日志、traceback、测试输出和详细开发工作保留在 PC；
- Work 主动通知只在整个任务首次到达 `COMPLETE` 时发送，并保持极短；需要详情时使用 `/work result`。

---

# 本地数据与凭据

SteerWX 的本地运行状态位于：

```text
%LOCALAPPDATA%\SteerWX
```

### 从 ClawBridge 升级

v0.2.0 仍支持 `python -m clawbridge` 和旧的 `clawbridge` 命令；新文档以 `python -m steerwx` 为标准入口。若 `%LOCALAPPDATA%\SteerWX` 不存在，会继续使用已有的 `%LOCALAPPDATA%\ClawBridge`，包括配置、Chrome Profile、对话 session、微信/iLink 元数据和路由状态。旧 `CLAWBRIDGE_*` 环境变量与系统凭据库中的旧键仍可读取。

确认服务已停止并关闭专用 Chrome 窗口后，可以显式复制到新目录：

```powershell
python -m steerwx migrate-data
python -m steerwx doctor
```

复制不会删除旧目录，也不会覆盖已有 SteerWX 目录；发现 Chrome Profile 占用标记时会停止。若旧配置显式填写了旧目录下的默认 Profile 路径，复制后的程序会使用新目录中的副本；自定义 Profile 路径保持原样。若配置了 `CLAWBRIDGE_HOME`、`CLAWBRIDGE_CONFIG` 或 `CLAWBRIDGE_CHAT_PROFILE`，复制后需检查这些显式覆盖值。若中断后留下 `SteerWX.migrating`，请先检查再重试。完成本地核对前保留旧数据。项目逻辑名与项目根目录不会自动改名。

其中可能包含：

- `config.toml`；
- `chat\session.json`；
- 独立 Chrome Profile；
- 微信 / iLink 账号元数据；
- route/runtime state。

ChatGPT 登录信息保存在独立 Chrome Profile 中；iLink token 通过本地 credential store / OS keyring 保存。

**不要把 token、凭据、Profile、session state 或个人配置提交到 Git。**

---

# 外部服务限制

腾讯 iLink / 微信 ClawBot 是外部传输服务，其可用性、限频、消息频率、会话有效性、绑定状态和真实客户端投递行为均由腾讯控制，可能在 SteerWX 没有修改的情况下发生变化。

当前需要特别注意：

- 腾讯没有公开一个可长期依赖的固定限频阈值，因此不要假设存在稳定的“N 条消息/分钟”规则；
- 短时间连续发送或高频 outbound 可能被限制，因此 SteerWX 倾向于短消息和低频主动通知；
- `sendmessage ret=0` 或类似接口成功，只代表服务端接受请求，不代表微信客户端一定收到；
- 对这种情况，SteerWX 记录为 `ACCEPTED_UNCONFIRMED`，不会对“已接受但未确认投递”的消息进行密集自动重试；
- 已完成受监督的真实微信 E2E 投递验证，但账号级 iLink 绑定异常或客户端投递异常仍可能独立发生。

---

# 架构

```text
WeChat ClawBot
      ↕
SteerWX Core
      ├─ M1 Work Observer
      ├─ M2 Codex Executor
      └─ M3 Conversation Core
             └─ ChatGPT Browser Driver
```

## M3-A：ChatGPT Browser

运行期浏览器自动化使用 Playwright，并复用手工登录时使用的独立 Chrome Profile。

它会等待新的 assistant response、稳定的非空文本以及相应完成信号。

## M3-B：本地会话

默认 session 保存其规范 ChatGPT `/c/...` URL，以及最多 24 条近期 audit messages：

```text
%LOCALAPPDATA%\SteerWX\chat\session.json
```

后续运行会重新打开同一个 thread。

只有已认证页面明确显示原 thread 不存在或无权访问时，SteerWX 才会新建一次对话，保留项目绑定，并发送本次 `/chat` 原消息。登录、网络、浏览器和无法明确判断的页面异常仍按原失败路径处理。SteerWX 不搜索 ChatGPT sidebar，也不人工注入历史记录。

## M3-C：轻量项目上下文

项目上下文按需加载，而且保持只读。

目前可补充的信息包括：

- Work；
- Git branch；
- working tree clean / dirty；
- changed file count；
- last local commit。

它不会执行：

- `git fetch` / `pull`；
- checkout；
- commit；
- 源码搜索；
- 项目执行。

## M3-D：微信对话桥

同一时间只有一个 `/chat` 请求会驱动默认浏览器 session。

控制命令不会启动浏览器。

完整 assistant response 保留在本地，微信只接收受 outbound policy 限制后的结果。

---

# 当前开发状态

目前：

- M0：WeChat / iLink Transport —— 已通过自动化验收；
- M1：Work Observer —— 已通过自动化验收；
- M2：Codex Executor —— 已通过自动化验收；
- M3-A / B / C / D —— 已通过自动化验收；
- M0 与 M3-D —— 已完成受监督的真实微信 E2E 验证。

但这仍然是一个早期项目。

特别是微信传输依赖腾讯 iLink / ClawBot，外部服务行为可能改变，因此不要把上述验收状态理解成生产级 SLA。

---

# 为什么做这个项目

SteerWX 解决的是一个非常具体的问题：

> 当开发工作已经大量依赖 ChatGPT、Codex 和本地 AI 工具后，人离开电脑，怎样还能低成本地知道任务进行到哪里、继续讨论问题，并在真正需要时显式触发本地分析？

我的选择不是再做一套完整的远程 IDE，也不是把开发机直接暴露到公网。

微信本来就在手机上。

所以 SteerWX 尝试把微信变成一个很轻的入口：

**平时用 `/chat` 讨论，用 `/work` 观察，真正需要本地分析时再明确使用 `/codex`。**

项目会继续保持“小而明确”的边界。如果它刚好解决了你的问题，可以直接使用；如果你的需求不同，也欢迎 Fork 后按自己的工作流修改。

---

# 贡献

欢迎 Issue、Bug Report、文档改进和 Pull Request。

提交代码前请阅读：

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md)

---

# License

SteerWX 使用 [MIT License](LICENSE)。

如果这个小工具对你有帮助，欢迎给项目一个 ⭐ Star，让更多有类似需求的人更容易看到它。
