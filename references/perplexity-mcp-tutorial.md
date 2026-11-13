# Perplexity 普通问答接入 Mac 与 Codex Loop：完整教程

本教程记录一套在 Perplexity Mac 26.44.0 实际验证过的设置：继续使用 Perplexity 订阅里的普通问答模型，由本机程序推进多轮模型调用，通过 MCP 操作授权文件，并由 Mac 上的 Codex Loop 保存任务和完成状态。没有新增本地模型或模型 API 订阅。

## 先看日常怎么用

一次性保存项目目录和操作范围后：

1. 在 Perplexity 新建空白普通问答，选中 **Codex Loop Mac Batch** 连接器。
2. 双击接入目录的 **Write.command**。
3. 输入一句任务，例如：

```text
/write 写一段面向科研人员的英文说明，保存为 final.md
```

程序会把固定执行规则加进会话，并推动需要的后续审查和修订。授权范围内的确认由程序处理，不需要逐步手输 `yes`。目标或文件名变了可以直接写在短任务里；超出已保存文件/命令范围则停住，需由你修改项目配置。也接受 `@my mac /write …` 作为本地启动器的文字别名；**这不是 Perplexity 原生的 @mention**，也不是在普通输入框发送短句就已启动驱动器。

终端等价调用（在接入目录内）：

```sh
python3 shortcut.py run '/write 写一段英文说明，保存为 final.md'
python3 shortcut.py run --project paper '/revise 按 review.md 修改 final.md'
```

### 与 `@My Mac @Epi Prose /write` 的区别

在已经安装对应技能的 ChatGPT/Codex 中，可以按那个产品实际提供的技能和连接器入口调用 Epi Prose。Perplexity 官方的 Skills 说明针对 **Computer**；不能因此推断普通问答会自动加载 ChatGPT 的技能，或把输入的 `@Epi Prose` 当作已安装。

**这里交付的是 Perplexity 普通问答的通用多轮文件写作入口，不是完整 Epi Prose 适配器。** 当前不实现其技能资源加载、独立上下文的角色边界和专门运行时生产路线。启动器对 `@Epi Prose` 明确报错，避免用普通写作循环冒充完整技能。短命令不能代替项目材料和科学决策；材料不足时模型应请求补充，不能编造研究事实。

参考：[Perplexity Search 的 Spaces](https://www.perplexity.ai/en-GB/hub/products/search)、[Computer Skills 官方说明](https://www.perplexity.ai/en-GB/hub/academy/how-to-use-computer-skills)。Space 可保存指令，但不等于本机程序已被启动；本实现不依赖尚未验证的 Search 技能或 Slash 自动分发。

## 1. 理解各部分的职责

```mermaid
flowchart LR
  TASK[短任务 + 一次性项目范围] --> LOCAL[本机会话驱动器]
  LOCAL -->|发送任务与续接| Q[Perplexity 普通问答模型]
  Q -->|工具调用，独立密钥认证| HTTPS[HTTPS MCP 隧道]
  HTTPS --> BRIDGE[本机 MCP 桥接]
  BRIDGE --> MAC[已有 My Mac HTTP 后端]
  BRIDGE --> LOOP[Mac 上的 Codex Loop runtime]
  MAC --> FILES[授权文件与受管理命令]
  Q -->|可见阶段结论与下一步| LOCAL
  LOCAL -->|检查实际文件并收尾| LOOP
```

模型负责理解、写作、审查和决定下一步；程序负责发送、核对身份和范围、保存状态、检查实际产物。Codex Loop 本身不含模型。驱动器不会在 Mac 休眠、客户端不可用或会话关闭后凭空继续推理。

本接入是独立的 Perplexity 适配器，显式配置本机 runtime 和项目。它不加载或修改 ChatGPT 控制器的 Drive Host Profile，也不声称完整复刻 ChatGPT 的宿主能力。

## 2. 准备 Mac 和源码

需要：

- 已登录且可用的 Perplexity Mac 客户端，账户能添加远程自定义 MCP；本次实测版本为 26.44.0。
- Python 3.10+、提供 `node:sqlite` 的 Node.js（建议 22.13+）、Xcode Command Line Tools 的 `swiftc`、`cloudflared`。
- Mac 上现有 Codex Loop 源码/runtime，以及已验证的 My Mac 本地 HTTP 后端。

如果还没有 My Mac，先完成 [Mac 本地 MCP 设置教程](local-mcp-tutorial.md) 的本机文件和命令验收。这里要求的是本机 HTTP 适配器目录：含 `http-launch.json`（本机回环 URL 和凭证文件路径）、`package.json`，并且可解析 MCP SDK 和 AJV。**仅安装 Desktop Commander 的 stdio 包不能冒充这个前提**。需要先部署本地 HTTP 后端，再继续本教程；已有 My Mac 用户直接复用，不重建原 ChatGPT 隧道。

首次获取 Codex Loop 时可克隆到自己的选定目录；已有维护 checkout 应直接复用，不覆盖改动：

```sh
git clone https://github.com/yihan-hu/codex-loop.git
cd codex-loop/integrations/perplexity-mcp
```

安装缺少的常用命令可使用其官方安装方式。例如已有 Homebrew 时，`brew install node cloudflared`。`xcode-select --install` 会打开 Apple 的系统安装对话框，按提示完成；已有 `swiftc` 无需重装。Node 的实际 SQLite API 与后端依赖由下一步配置脚本现场检查。

## 3. 生成仅属于本机的配置

先创建或选定你授权的现有工作目录。把下面两个路径替换成真实绝对路径：

```sh
python3 configure.py \
  --my-mac-directory '/absolute/path/to/existing-my-mac-http' \
  --workspace '/absolute/path/to/authorized-project'
```

若 Node/cloudflared 不在 PATH，显式加 `--node '/absolute/path/to/node'`、`--cloudflared '/absolute/path/to/cloudflared'`。runtime 默认为本 checkout 的 `scripts/codex_loop.py`，可用 `--runtime-cli` 指定同一台 Mac 上的已验证安装。

配置脚本会检查前提、编译原生 UI helper，在本机 Application Support 创建或复用独立随机密钥，并生成：

- 接入目录的私有 `config.json`：机器路径和端口；Git 忽略它。
- `~/Library/Application Support/PerplexityCodexLoop/bin/perplexity-ui`。
- `~/Library/Application Support/PerplexityCodexLoop/state/project-example.json`：项目范围模板，只在首次创建时生成，避免覆盖你的配置。

默认本机监听 `127.0.0.1:31843`；更改端口可用 `--port`。密钥文件权限为 0600，不写入 Git、教程或日志。配置阶段不会启动或重启服务。

在 macOS「系统设置 → 隐私与安全性 → 辅助功能」中允许实际承载程序的应用（例如 Terminal；授权归属可能因启动方式不同而变化）。运行 helper 做只读检查：

```sh
"$HOME/Library/Application Support/PerplexityCodexLoop/bin/perplexity-ui" snapshot
```

输出应能识别 Perplexity 主会话窗口。若被系统拒绝，按系统设置授权后重试；不要把无权限误当成空白会话。程序不使用键盘或剪贴板作为隐式回退，也不调用 Perplexity 私有 HTTP 接口。

## 4. 启动本地服务和带密钥的 HTTPS 隧道

```sh
python3 manage.py start
python3 manage.py status
```

也可以双击 `Start.command`、`Status.command`。看到 `ready: true` 后，复制返回的 `mcp_url`，格式是 `https://…trycloudflare.com/mcp`。

Perplexity 26.44.0 的实测界面只提供远程 URL，没有旧教程里的本地 stdio 启动框，因此这里使用 Streamable HTTP + Cloudflare Quick Tunnel。**配置公网隧道意味着授权请求和结果会经过 Perplexity 与 Cloudflare**；使用前确认你允许该传输。所有 MCP/健康检查请求都要求独立密钥；未携带或错误密钥均拒绝。

launchd 只管理这个接入的 HTTP 和隧道两个服务，不重启原 My Mac/ChatGPT Tunnel。它们维持当前登录会话，不安装登录自启。Quick Tunnel 进程重新启动后域名会变，需要更新 Perplexity 的 URL；仅重启 HTTP 不会改变域名。稳定域名需要另行设置命名隧道，不能把临时 URL 当作永久服务承诺。

参考：[Cloudflare Quick Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)。

## 5. 在 Perplexity 添加远程 MCP

在客户端的插件/连接器设置中添加自定义远程 MCP（具体菜单名可能随版本变化）：

- 名称：**Codex Loop Mac Batch**。
- MCP URL：上一节返回的完整 `https://…/mcp`。
- 认证：独立 API key/Bearer；若界面提供自定义请求头，使用 `Authorization: Bearer <独立密钥>`。
- 从本机私有文件安全地复制密钥到该认证框，保存后收起认证设置；不要贴进聊天或截图。

本机密钥位置是 `~/Library/Application Support/PerplexityCodexLoop/state/https-api-key`。连接成功后应发现 12 个工具。普通问答输入框「更多选项 → 连接器」里还需要选中它；只安装而没有选中，并不代表当前会话可调用。

若旧连接器缓存了 11 个工具目录，可重新登记这个新名称，避免误以为服务缺少 `loop_submit`。服务升级无需到处创建重复连接器，先核对实际工具目录。

参考：[Perplexity 自定义远程连接器](https://www.perplexity.ai/help-center/en/articles/13915507-adding-custom-remote-connectors)。

## 6. 一次性保存项目，后面只写任务

编辑第 3 步生成的 `project-example.json`。例如：

```json
{
  "workspace": "/absolute/path/to/authorized-project",
  "goal": "项目范围模板；每次运行由用户短任务替换目标",
  "allowed_files": ["Plan.md", "draft.md", "review.md", "final.md"],
  "required_files": ["final.md"],
  "allowed_commands": [],
  "max_rounds": 12,
  "min_rounds": 1,
  "round_timeout_seconds": 900,
  "max_approvals_per_round": 16
}
```

`workspace` 必须是已有目录。`allowed_files` 是允许读取和修改的相对文件；`required_files` 是完成前必须实际存在的交付物。把任务用到的输入材料也加入范围。`dir/**` 表示目录内文件，`**` 表示整个项目，按真实授权选择，不默认扩大。显式允许 shell 时，`allowed_commands` 必须列出完整精确字符串；它不是 OS 沙箱，命令仍有当前用户权限。常规写作保持空列表即可。

保存为项目 `paper`，并设为默认：

```sh
python3 shortcut.py save paper \
  "$HOME/Library/Application Support/PerplexityCodexLoop/state/project-example.json" \
  --default
python3 shortcut.py list
```

保存的是这次你审阅过的本地范围，不是对未来任何 Mac 路径的全局授权。新任务只替换目标，不更改文件或命令白名单。可以保存多个项目，调用时用 `--project NAME`；`Write.command` 使用默认项目并在提问前显示它。

然后按教程开头的一句话调用。不要把不同项目共用一个过宽的默认目录。项目配置只保存在本机私有状态目录，不提交 Git。

## 7. 多轮执行、状态与恢复

启动返回 `run_id`、`task_id`、进程号和状态文件。固定协议由代码直接注入，用户不必每次写它。每轮由 Perplexity 真实完成阶段工作，再返回带随机轮次标记的 `CONTINUE`、`DONE` 或 `NEEDS_USER`；本地程序读取可见回答，发送模型提出的具体下一步。始终使用同一个 Codex Loop task_id。

自动 `yes` 只允许绑定会话、同任务、同轮的授权写入/编辑、精确白名单命令和检查点。新任务、提前收尾、其他文件及新增命令不会被自动批准。即使读操作不弹窗，也受到 MCP 桥接端同一文件范围的约束；符号链接不能绕开授权。一次只允许一个驱动器使用客户端。

运行期间保持原会话选中，输入框不要放自己的草稿。切换会话、模型超时、超出轮数/批准次数、出现陌生确认或用户决策时会停在 `needs_attention`，不会伪报完成。

在接入目录执行（替换 RUN_ID）：

```sh
python3 conversation.py status RUN_ID
python3 conversation.py pause RUN_ID
python3 conversation.py resume RUN_ID
python3 conversation.py cancel RUN_ID
```

- `pause` 阻止后续发送，不能撤回已经发出的消息和动作。
- `resume` 在前台继续同一个已暂停任务；先选回 `[PCL:RUN_ID]` 开头的原标签。恢复原会话/连接后才继续，不重新创建任务。
- 进程崩溃但状态仍为 running 时，确认旧进程已结束、原会话仍存在后，使用 `python3 conversation.py run RUN_ID` 接续观察。
- `cancel` 停止生命周期及受管理命令。若需改变目标或权限，当前版本应取消旧运行，更新项目配置，在新空白会话启动。恢复命令不接受新目标。

逐轮可见回答、配置、状态和事件记录在 `~/Library/Application Support/PerplexityCodexLoop/state/conversations/RUN_ID/`；不会读取隐藏推理。最终先核对所需文件的实际存在、大小与 SHA-256，再尝试 canonical runtime 收尾。`PASS` 证明这些操作验收完成，不能独立证明科学或语义正确。

## 8. 验证与问题定位

配置完成、HTTP/隧道启动后，在接入目录运行：

```sh
python3 check-conversation.py
node check-http.mjs
```

前者检查任务/轮次绑定、文件/命令授权、符号链接、结果标记和真实文件检查；不调用模型。后者检查回环与 HTTPS 的缺失/错误密钥拒绝、认证后工具发现、真实状态调用及不受信任 Origin 拒绝。真实 UI/模型验收需要在客户端单独执行，不能用这些静态检查替代。

本实现曾从空白普通问答连续完成“初稿 → 实际读取并审查 → 实际读取并修订”三阶段：3 次模型任务发送、3 次程序范围内自动 yes、3 个实际文件写入、同一个 task_id，过程无手动确认或中途修复，最终 `complete / PASS`。终稿通过实际文件分词核对为 157 词。这是当前 Mac/客户端版本的实测，不是对未来版本的保证。

常见问题：

| 现象 | 处理 |
| --- | --- |
| 普通问答每步要求 yes | 单纯把工具权限设为“允许”仍可能被宿主确认；使用本教程驱动器，只批准已配置范围 |
| 输入 @Epi Prose 后并没有加载技能 | 这不是普通问答已支持的技能路由；完整技能继续用已安装它的 ChatGPT/Codex |
| 检测不到会话/输入框 | 检查 Accessibility 授权、Perplexity 主窗口与当前版本；不盲目自动按键 |
| 连接器已安装但程序拒绝启动 | 在空白问答的输入框中选中正确连接器，清空用户草稿 |
| 写入/读取不在授权范围 | 修改自己审阅的项目配置并重新保存；模型不能自行扩大授权 |
| 隧道显示新域名但暂时无法解析 | 检查 DNS 生效及 HTTPS 状态；脚本的 DoH 检查保留 TLS 校验，不使用跳过证书验证 |
| 重启后 URL 不同 | 把新的 MCP URL 更新到 Perplexity 原连接器 |
| 写操作结果不明 | 查询原 task/operation；复用原 request_id，不换 ID 盲重试 |
| 需要后台持续运行 | 电脑需唤醒且会话可用；本驱动器不会自动唤醒 Mac 或启动新聊天 |

## 9. 只需要一次确定性批量操作时

不需要模型再次判断的明确步骤，可直接让 Perplexity 用一次 `loop_submit` 提交整批 `write_file / edit_file / read_file / list_directory / command / verify_file`。批准一次后，本地服务按持久清单执行并用只读 `loop_status(batch_id)` 查询。这与本教程的多轮模型驱动是两种不同任务形态；`loop_submit` 不包含模型，不能自动决定新的科学或写作方向。

## 10. 停止、升级和保密

`python3 manage.py stop` 或 `Stop.command` 只停止本接入的 HTTP/隧道，不关闭原 My Mac/ChatGPT 服务；先取消仍在运行的任务。不要把停连接误当成命令已被终止。

源码更新后保留私有配置，检查变化再重新运行配置/编译。`manage.py start` 不会替换已加载进程；若服务程序路径变化，需先停止再启动，随后更新可能改变的 Quick Tunnel URL。仅更换 HTTP 代码且路径不变时可重启 HTTP launchd 服务，保留隧道域名。

GitHub 中只保存源码和教程，不上传 `config.json`、项目配置、密钥、SQLite、会话日志或未授权的项目内容。官方 ChatGPT Skill ZIP 只包含运行时 allowlist；这个可选 Mac 接入目录从源码仓库使用，不在云端 Skill 包里运行。
