# 把自己的电脑接到 ChatGPT，再交给 Codex Loop 使用

这份教程整理了本次 macOS + Desktop Commander + Secure MCP Tunnel 的配置经验。目标是让 ChatGPT 通过你自己的 MCP 读写指定文件、执行终端命令，再由 Codex Loop 选择连接和工作位置。已有可用的本地文件/终端 MCP 可以直接从第 5 步开始。

这里的 `My Mac`、`my-mac`、`mac` 和路径都是示例，不包含作者的账号、Tunnel ID、密钥或个人目录。Windows 用户可复用连接登记和选择规则；下面的安装、凭证保存和进程管理命令只针对 macOS。

## 1. 先分清功能、权限和费用

| 项目 | 在这个方案中的作用 |
| --- | --- |
| 本地 MCP server | 真正在你的电脑上提供文件和终端工具，例如 Desktop Commander |
| Secure MCP Tunnel / `tunnel-client` | 把 ChatGPT 的工具请求送到本地 MCP |
| Platform API key | `tunnel-client` 的认证凭证；不要把它交给 Codex Loop 的连接配置 |
| ChatGPT 自定义 app | 聊天中实际选择的连接，例如 `My Mac` |
| Codex Loop 私有配置 | 保存连接优先顺序、默认 Web/电脑等偏好 |

本次实测在已有账号权限下完成了接入和文件/终端验证，没有充值、购买 API credits 或启用收费 RDC 服务。这是一次配置结果，**不是所有账号、套餐或未来 Tunnel 使用都免费的承诺**。官方 Tunnel 指南说明了认证和接入要求，没有在该页面给出足以保证本方案永久免费的信息。不要把“需要 API key”直接当成“必须充值”，也不要把“创建连接成功”当成“没有任何费用”。[官方 Tunnel 指南](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)

如果你的要求是零新增费用，开始前就说明：**出现充值、绑卡、升级套餐、购买 credits 或接受收费服务的要求，立即停止，不点击确认。** 同时查看当前账号的账单/用量和服务条款。这里不需要写一个调用 Responses API 模型的程序；如果另外调用模型 API，应按其独立计价核实费用。[API 价格说明](https://developers.openai.com/api/docs/pricing)

可以把下面这段话交给正在你电脑上运行的 Codex：

```text
帮我配置一个连接这台电脑的自定义文件/终端 MCP，接到 ChatGPT，
再登记到 Codex Loop 的私有配置。先解释将授予的权限。
若要求充值、绑卡、升级或接受收费服务就停止。
只在我指定的工作目录测试，不读取或显示密钥。
连接成功后验证终端以及文件创建、修改和回读。
保持 Web 默认，除非我明确让你记住这台电脑为默认。
```

## 2. 准备账号权限和本地 server

在 [Platform Tunnels](https://platform.openai.com/settings/organization/tunnels) 创建或选择 Tunnel，并关联目标 ChatGPT workspace。创建/修改需要 **Tunnels Read + Manage**；运行客户端需要 **Read + Use**。在 [Runtime API keys](https://platform.openai.com/settings/organization/api-keys) 给长期运行的客户端创建单独的受限 runtime key，只授予 Read + Use，不使用 admin key。ChatGPT 开发者模式另受账号/workspace 权限控制。[权限说明](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)

先确认 Node.js、npm 和 Python 3 可用。已有满足文件和终端需求的 MCP 不必再装 Desktop Commander。下面演示本次验证过的 Desktop Commander `0.2.52`；它是实测版本，不代表当前最新版。升级后应重新验证工具行为。项目和工具说明见 [Desktop Commander](https://github.com/wonderwhy-er/DesktopCommanderMCP)。

```bash
MCP_DIR="$HOME/Library/Application Support/codex-loop-mcp"
mkdir -p "$MCP_DIR"
cd "$MCP_DIR"
npm install --save-exact @wonderwhy-er/desktop-commander@0.2.52
```

确定你要授权的工作目录，例如 `/Users/alice/PiWork`。接入后、文件测试前，用 Desktop Commander 的 `get_config` 检查现有设置；若需修改，让用户授权后通过 `set_config_value` 设置 `allowedDirectories`，保留其他配置。文件目录设置不构成终端进程的完整沙箱；终端命令仍可能访问其他目录。因此只执行当前任务授权范围内的命令，不能把一个宽松的 server 配置解释为整台电脑的授权。文件/终端 MCP 也不自动提供浏览器或 GUI 控制。

## 3. 私下保存凭证并启动 Tunnel

从 Platform 的下载入口取得 `tunnel-client`，放到稳定的本地工具目录并加入 PATH。用 `tunnel-client help quickstart` 检查当前版本的用法；不同版本以实际帮助为准。不要把二进制、server 安装目录或凭证放进项目仓库。[客户端下载和启动说明](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)

本次使用“私有 key 文件 + profile 中的文件引用”，避免把 key 粘进命令历史、截图、聊天或 YAML。下面的脚本从终端隐藏输入，文件权限为 `0600`，且拒绝覆盖已有文件。请在本机交互式终端运行，不要把密钥发给聊天：

```bash
python3 - <<'PY'
import getpass
import os
from pathlib import Path

path = Path.home() / "Library/Application Support/tunnel-client/secrets/my-mac.key"
path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
secret = getpass.getpass("粘贴受限 Tunnel runtime key（不会显示）: ").strip()
if not secret:
    raise SystemExit("未保存：输入为空")
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as file:
    file.write(secret + "\n")
print("已保存私有 key 文件，未显示内容")
PY
```

把下方的 `tunnel_REPLACE_WITH_YOUR_ID` 替换成你自己的 Tunnel ID；不需要把 key 本身写入命令。先生成 profile、检查配置，再通过客户端自带的 managed runtime 启动。这里的 `my-mac` 只是本机运行别名。命令来自本次使用的 `tunnel-client` 帮助，若你的版本没有 `runtimes`，可以用 `run --profile my-mac` 在前台保持运行，不用 `nohup` 或 `disown` 代替管理。

```bash
MCP_DIR="$HOME/Library/Application Support/codex-loop-mcp"
KEY_FILE="$HOME/Library/Application Support/tunnel-client/secrets/my-mac.key"
NODE_BIN="$(command -v node)"
MCP_COMMAND="\"$NODE_BIN\" \"$MCP_DIR/node_modules/@wonderwhy-er/desktop-commander/dist/index.js\""
TUNNEL_ID="tunnel_REPLACE_WITH_YOUR_ID"

tunnel-client init --sample sample_mcp_stdio_local --profile my-mac \
  --tunnel-id "$TUNNEL_ID" --mcp-command "$MCP_COMMAND" \
  --control-plane-api-key-ref "file:$KEY_FILE" --health-listen-addr 127.0.0.1:0
tunnel-client doctor --profile my-mac --explain
tunnel-client runtimes connect --alias my-mac --profile my-mac \
  --tunnel-id "$TUNNEL_ID" --runtime-api-key "file:$KEY_FILE" \
  --mcp-command "$MCP_COMMAND"
tunnel-client runtimes status my-mac --json
```

如果检查失败，先处理权限、server 启动或认证错误，再继续。状态必须证明进程运行、健康并且 ready，不能只根据“启动命令已返回”判断成功。客户端停止、电脑关机/休眠或网络断开时，聊天连接可能不可用；不要把一次启动成功说成永久在线或已经设置开机启动。

需要暂停连接时使用 `tunnel-client runtimes stop my-mac`；前台 `run` 使用该终端的 Ctrl-C。之后用同一份配置恢复并检查状态。不要删除密钥、Tunnel 或 Codex Loop 的生命周期目录来解决暂时断线。若密钥曾进入截图、工具输出或聊天，创建替代的受限 key、更新本地引用并验证，再撤销旧 key；不要继续使用已泄露的 key。

## 4. 在 ChatGPT 接入并做实际验证

在 ChatGPT 的 Settings → Security and login 打开 Developer mode，然后到 Plugins 新建 app，命名为 `My Mac`，Connection 选择 Tunnel 并选中上述 Tunnel。检查发现的工具。新建聊天并从工具菜单加入 `My Mac`。[官方接入和测试步骤](https://developers.openai.com/plugins/deploy/connect-chatgpt)

先验证只读电脑身份和预期目录，再在你明确授权的 scratch 目录做以下小测试：

```text
请使用 My Mac，确认连接的是我指定的电脑。
只在 /Users/alice/PiWork/mcp-connection-test 目录操作：
运行 pwd 和 python3 --version；新建 connection-test.txt 写入第一行，
追加第二行，然后读回两行。报告真实工具返回，不扫描其他目录。
```

本次就是用终端、创建、修改和回读确认整条链路。App 创建成功或能列出工具只能证明发现阶段，不能证明写文件和执行终端都正常。失败时先检查同一操作是否已经完成，尤其写入或命令超时后不要直接重发。测试通过后可按用户意愿删除这个明确的测试目录。

## 5. 登记到 Codex Loop，并选择默认位置

连接运行起来后，进入已更新的 Codex Loop 源码/工具目录使用下面的 CLI；聊天用户也可以让 Codex Loop 通过已连接的电脑执行同样的设置。`scripts/codex_loop.py` 必须来自包含连接选择功能的版本。如果命令缺失，先升级相应 Skill/本地 runtime cache，不能把旧版本当成已经接入。

先查看现有登记；`set execution.connections` 替换整个连接列表。有现有条目时，保留它们并合并新条目，不要盲目复制覆盖。下面的 Web 默认适用于首次设置；已有默认位置时，只有用户要求改变才更新。

```bash
python3 scripts/codex_loop.py host-config get execution.connections
python3 scripts/codex_loop.py host-config set execution.connections '[
  {"name":"my-mac","computer":"mac","connector":"My Mac","kind":"mcp"}
]'
python3 scripts/codex_loop.py host-config set execution.default_target web
python3 scripts/codex_loop.py host-config set workspace.environments '{"mac":{"default_root":"/Users/alice/PiWork"}}'
```

`connector` 必须匹配当前聊天可见的 app 名称或 ID；`name` 是 Codex Loop 的连接别名，`computer` 是执行环境的 ID；Mac、Windows 和每个 WSL 发行版分别登记，默认工作区放在对应的 `workspace.environments` 中。它们不必等于 Tunnel ID。这些命令先写入当前主机的私有 `~/.codex-loop/host.json`。要让新的 Web 会话恢复设置，还必须按文末流程保存到自己的 Drive；不能假定 Mac 上的文件会自动出现在新 Web 容器里。配置不随 Git push、Skill ZIP 或任务持久化携带。只保存非敏感连接标识和路径，凭证留在前面的私有 key 文件中。

如果有两个 MCP 都连接同一台 Mac，并且 RDC 也确实连接这台 Mac，可以把列表设为：

```json
[
  {"name":"my-mac","computer":"mac","connector":"My Mac","kind":"mcp"},
  {"name":"backup-mac","computer":"mac","connector":"My second Mac MCP","kind":"mcp"},
  {"name":"rdc-mac","computer":"mac","connector":"Remote Desktop Commander","kind":"rdc"}
]
```

没有连接第二个 MCP 或 RDC 时，删除相应示例条目。不要仅为了补齐例子安装或购买 RDC，也不要把未验证的 RDC 标成同一台电脑。自定义 MCP 在前，RDC 在后；同一类内按数组顺序优先。单独指定电脑 `mac` 时，后备必须仍是这台电脑。没有登记 RDC 的传统路径，只能在未指定电脑的 `local` 自动选择中发现通用 `rdc`，并重新确认电脑身份。

下面的默认位置命令二选一，不需要依次运行：

```bash
# 记住这台 Mac 为以后新会话的默认电脑；先完成上述连接登记。
python3 scripts/codex_loop.py host-config set execution.default_target mac
# 恢复 Web 默认。
python3 scripts/codex_loop.py host-config set execution.default_target web
```

手动指定当前连接，不改保存的默认值：

```bash
# 仅查看本次手动选择的候选；不改保存的默认值。
python3 scripts/codex_loop.py execution-resolve --connection my-mac
```

也可以说“记住这台 Mac 为默认”“以后默认用 Web”“这次用第二个 MCP”。前两种保存偏好，最后一种是当前任务选择，不写默认值。新会话读取偏好；已开始的生命周期保持原电脑，不能因为你改了默认值就迁移。多个电脑之间的设置文件只有一个明确的持久 owner，见 [连接配置合同](local-connections.md)。

`execution-resolve` 返回 `needs_observation` 表示只选出了候选。Host 必须实际确认该连接可见、具备所需能力，并把可用连接别名传给 `--available-connections-json`；不要把示例列表当成检测结果。手动指定的连接不可用时停止，不改用其他连接；自动选择才会在已观察到的候选中按顺序选择。

## 排查时先看哪一层

| 现象 | 先检查 |
| --- | --- |
| Platform 显示 Tunnels access required | 当前组织及 Read / Manage / Use 权限；不通过充值解决权限缺失 |
| ChatGPT 看不到 Tunnel | 目标 workspace 是否关联、创建者是否有 Use 权限、是否有开发者模式权限 |
| App 可以创建，实际工具调用失败 | 客户端是否仍运行、server 是否正常、当前聊天是否加入该 app |
| 能读文件，不能执行 Local 任务 | MCP 是否真的提供终端和 Python，所需路径/命令是否获准 |
| `needs_observation` 或 no available connection | 尚未得到实际可用性证据；不能仅凭登记跳过检查 |
| 命令返回缺失/超时 | 在原连接核对原操作状态，再决定下一步；不通过后备重放写操作 |
| 新会话用了别的默认位置 | 确认连接的是自己的 Drive、固定配置路径恢复成功，并检查 `execution.default_target` |
| 出现账单、充值或升级要求 | 按零新增费用约束停止，报告具体页面和要求，不继续付费 |

这份教程负责首次配置和实际验证；运行时的优先级、手动选择、跨电脑限制和授权边界以 [local-connections.md](local-connections.md) 为准。

## 新会话保留设置

连接自己的 Google Drive 后，Codex Loop 在新会话首次调用时，先从固定的“我的云端硬盘 → `codex-loop/settings/host-profile.json`”恢复默认电脑和连接顺序，再选择执行位置。名称固定，不由 LLM 自己取；不会使用作者的网盘。修改并要求记住设置时，按 [Drive 配置恢复与保存流程](host-profile-drive.md) 更新同一私有文件，读回核验后才算跨会话保存。没有连接 Drive 或没有保存的配置时，Web 使用默认值；读取失败或同名冲突需要报告。只恢复偏好，不自动恢复任务，不恢复执行授权。

## 精简界面与多会话并发

Desktop Commander 的配置面板、文件预览是可选 MCP UI，不是 ChatGPT 的操作许可。工具定义里的 UI 元数据会触发卡片；不要为隐藏卡片取消工具的安全声明或扩大文件访问范围。正常恢复任务不重复读取完整配置面板，也不读取全局工具历史。

优先使用下述 HTTP 纯文本桥接，在接入层处理工具定义和返回结果。继续使用 stdio 时，0.2.52 的 UI 显示决策受厂商实验配置控制，不是稳定的用户关闭开关；需要本机无卡片模式时，可在 `dist/ui/contracts.js` 的 `buildUiToolMeta` 中加入明确的环境开关：当 `DESKTOP_COMMANDER_MCP_UI_PREVIEWS=0` 时返回 `undefined`，省略可选 UI 元数据。启动该后端时设置此变量，并验证工具发现没有 UI 模板、文件和终端工具仍存在。这是本机适配，不是上游原生参数；重装/升级依赖后必须重新检查适配，不可假定它一直有效。现有聊天可能缓存工具界面，需要连接刷新后才能看到变化。

Tunnel 的 `mcp.max_concurrent_requests` 默认 10，可在用户私有 profile 中设置为 20 等更大的值。它限制同时执行的请求，不是允许打开多少聊天；修改需要重启客户端生效。扩容前检查本机负载和等待队列，不保证加大数值会解决连接问题。不要在其他会话仍有终端工作时直接重启共享后端。

stdio 是 Tunnel 与一个本机 MCP 子进程通过标准输入、输出管道通信。当前实现每通道共享子进程，没有独立的 MCP 会话隔离。需要更可靠的多会话使用时，应采用支持独立会话/进程状态的 Streamable HTTP 后端，绑定本机回环地址，再通过 Tunnel 访问；仅把连接改成 HTTP 或扩大并发数不足以证明会话隔离。会话结束不应关闭其他会话使用的服务，终端句柄也应按会话管理。HTTP 服务需分别处理带会话 ID 的调用和不带会话 ID 的调用，不能把“一个聊天”直接当作“一条 MCP 会话”。

[客户端并发和 stdio 边界](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md) · [可选 MCP UI](https://developers.openai.com/plugins/build/chatgpt-ui)


### 本机 HTTP 后端和桌面启动文件

HTTP 后端和桌面启动文件由用户在自己的电脑上单独配置，实际安装位置、认证文件和 Tunnel ID 留在私有配置中；Codex Loop 的安装包只携带通用教程与连接选择功能。下面的结构和启动约定可用于搭建本机接入。

本机 Mac 就能运行 HTTP 服务，不需要另租服务器：

```text
ChatGPT → OpenAI Tunnel → 127.0.0.1 上的 HTTP MCP 后端
                            ├─ MCP 会话 A → 独立 Desktop Commander 子进程
                            ├─ MCP 会话 B → 独立 Desktop Commander 子进程
                            └─ 无会话 ID → 已初始化的共享工作进程
```

有状态后端按 `Mcp-Session-Id` 分配进程、保存终端句柄，并只在对应会话结束时清理该进程。没有会话 ID 的请求不能可靠识别聊天身份；可复用已初始化的工作进程，避免每个聊天重新初始化共享 stdio 连接，但其终端句柄仍共享。两种路径都访问同一个文件系统，不能保证同时编辑同一文件不会冲突。

HTTP 监听仅绑定回环地址，验证 Host/Origin，并使用独立的本机认证密钥。Tunnel profile 的 `mcp.server_urls` 指向该监听地址；`mcp.extra_headers.Authorization` 使用 `file:` 引用包含完整 `Bearer …` 头值的私有文件。发现和初始化探测也需要同样的认证，可在 `mcp.discovery_extra_headers` 配置同一引用。文件设为仅当前用户可读写；不要把真实头值、个人路径或 Tunnel ID 复制到公开配置。

macOS 的 `.command` 启动文件可按用户要求做到双击直接启动，无需重复输入 `yes`。用户已授权切换时，启动程序可先确认 HTTP 后端健康，再自动停止旧 stdio Tunnel，启动 HTTP Tunnel。切换会中断旧连接的终端会话，首次使用前应暂停相关工作。启动文件应按以下顺序启动：先检查后端是否已运行；使用 `launchd` 管理后端并等待本机健康检查；确认旧 Tunnel 已停止后，再使用同一 alias 启动 HTTP Tunnel；最后检查 Tunnel 的进程和 ready 状态。首次从 stdio 切换应在用户暂停其他聊天后执行，不能为了测试启动同一 Tunnel 的第二个客户端。重复运行启动文件应复用现有服务，关闭终端窗口不应关闭后台服务。服务的 plist 可保存在用户私有应用目录，仅由启动文件加载；这不等于配置了登录自动启动。

注意：`tunnel-client runtimes connect` 会重新生成 native profile。并发数和 HTTP 认证头必须在启动环境中提供，并写回生成的私有配置，不能只在启动前修改 profile 后假定设置仍在。环境中保存文件引用，避免把密钥本身写进命令行。

验证至少包括：两个同时连接的会话 ID 不同，终端列表互相隔离，结束其中一个后另一个继续执行；不带会话 ID 的工具发现和调用可以执行；工具安全声明仍存在、可选 UI 模板已移除；无认证和不受信任 Origin 被拒绝。先验证本机 HTTP 和 macOS 服务，再切换 Tunnel 验证 ChatGPT 的实际调用。不得把本机测试通过说成已经完成整条 ChatGPT 链路验证。


### 启动失败：`main channel is required`

即使生成的 profile 已包含正确的 `mcp.server_urls`，启动环境中的 `MCP_SERVER_URL=""` 或 `MCP_COMMAND=""` 仍可能覆盖它，导致客户端报告没有主通道。不要把设置为空当成删除环境变量。HTTP 启动程序应删除继承的 `MCP_COMMAND`，并把 `MCP_SERVER_URL` 显式设为本机 HTTP 地址；不要把两者都设为空：

```javascript
const env = { ...process.env, MCP_SERVER_URL: localMcpUrl };
delete env.MCP_COMMAND;
```

`localMcpUrl` 来自用户的私有配置。启动 managed runtime 时将该环境传入子进程，同时提供 `--mcp-server-url`；认证头、并发数也通过启动环境提供，并写回生成的私有 profile。错误处理应显示客户端返回的具体错误，而不是只打印一长串启动命令。排查时检查运行状态和客户端日志，不能把这个错误归因于充值或聊天连接数量。

这套方式已验证 HTTP 后端与 Tunnel 都能达到 healthy/ready，桌面启动文件在无交互输入时成功运行，重复启动保持同一个 Tunnel PID。这里的验证范围是本机服务和 Tunnel；ChatGPT 聊天中的实际工具调用仍须单独验证。桌面只保留一份当前的启动文件和一份停止文件：启动复用服务，停止同时关闭 Tunnel 和 HTTP 后端；删除旧的重复文件不会停止正在运行的连接。


### 会话不是并发名额：自动释放闲置连接

无需把累计 MCP 会话数限制为 20。初始化和工具发现可能不断产生新会话，客户端也不一定在结束时发送 DELETE；按历史会话数拒绝新的 initialize 会让工具调用失败，而 HTTP 健康检查仍返回成功。并发请求上限只限制当前执行的请求，不能拿来代替会话生命周期管理；保持连接的 SSE GET 也不应长期占用执行名额。

可采用以下已验证的本机实现约定：

- 不设置累计会话数量上限；HTTP 会话先保存轻量协议状态，第一次实际工具调用时才启动该会话的独立工作进程。
- 工具发现共用一个已初始化的工作进程和工具定义缓存，探测会话不各自启动 Desktop Commander。
- 仅做初始化或发现的会话闲置 2 分钟后释放；执行过工具的会话闲置 30 分钟后检查并清理。这些时间是本机后端的默认值，不是 MCP 或 Tunnel 的协议规定。
- 运行中的工具调用、终端命令或搜索阻止闲置清理。清理前查询后端的实际工作状态，并重新核对是否刚有请求到来；查询失败时保留会话，不能把未知状态当成任务结束。
- 客户端明确 DELETE 时立即关闭该会话；无会话 ID 的每次请求关闭自己的 HTTP 请求上下文，共用的工作进程作为后台服务保留。长期命令完成且达到闲置时间后，其独立会话和进程才释放。

清理仅处理 MCP 连接和进程，不删除项目文件、Codex Loop task 或 semantic isolation。已保存的任务记录和结果可在重新连接后用于原任务续跑；终端句柄、已结束命令的输出缓存、交互式 Python 的内存变量等临时状态会丢失。未提交的 semantic result 只有写入持久文件后才可恢复，不能仅凭 isolation 存在就认定结果已保存。已过期的 MCP 会话需要重新初始化；不能把新的连接误当作必须新建业务任务。监测应同时记录会话数、工作进程数和执行请求数，健康/ready 状态仍需配合真实工具调用检查。

回归验证应包含超过 20 个连续会话、发现会话只共用一个工作进程、闲置自动释放、运行中的长命令不被清理、命令结束后释放以及清理后继续执行新请求。本次这些验证已通过；仍需在发生故障的原 ChatGPT 聊天中重新观察工具调用，不能代替业务任务的完成确认。


### 调整同时执行请求数

请求上限可按本机负载调整，例如从 20 放宽到 64。Tunnel 的 `MCP_MAX_CONCURRENT_REQUESTS` / `mcp.max_concurrent_requests` 与自建 HTTP 后端的执行请求上限需要同步，否则较低的一层仍会拒绝请求。改完重启相应服务，验证实际生效值、重复启动不会重启健康连接，以及并发调用结束后名额释放。本机回归已验证同时接受 64 个发现请求、对第 65 个执行限流、已接受请求全部完成后归还名额；这只证明限流逻辑，不代表 64 个重计算任务同时运行的性能保证。

文件系统或 OneDrive 的访问速度不能替代 CPU、内存和磁盘负载判断。长命令的启动请求返回后，后台任务仍继续运行；分析、构建等重任务需通过各自的进程数、线程数或任务调度单独控制并行度。这个设置不改变项目任务的并行参数。


### 配置面板仍显示时：纯文本工具与旧界面缓存

只移除工具发现中的 UI 元数据，不一定能阻止已缓存界面的聊天继续展示旧配置面板。Desktop Commander 的 `get_config` 还会返回用于配置编辑器的 `structuredContent`，包含配置项和 UI 提示。纯文本 HTTP 桥接应同时处理工具定义、工具结果和 UI 资源：移除可选 UI 元数据，不公开 HTML/MCP App 资源；普通结果保留文本、真实文件内容、媒体和错误标志，省略仅用于可选面板的结构数据。

日常连接身份检查可改成只读的 `get_host_info`，返回简短电脑信息，避免每次恢复任务调用整个配置编辑器。曾绑定 UI 的文件工具可使用新的纯文本名称，例如 `read_local_file`、`read_local_files`、`list_local_directory`、`edit_local_file`，内部仍调用原来的读写实现，保留原安全声明和参数。旧工具名应明确提示更新工具列表，不能继续返回整个配置面板。

新名称用于避免复用旧的界面定义，不意味着能清除 ChatGPT 已缓存的模板。应用更改后，检查当前服务实际工具列表与结果；已有聊天若仍显示旧卡片，需要重新获取 My Mac 工具列表，例如重新加入该连接，必要时在 app 配置中刷新工具发现。已经显示过的卡片不会因后台更新而自动消失。ChatGPT 自己的工具调用提示与权限请求由平台控制，这里只移除自定义配置面板和文件预览，不承诺所有调用完全不可见。
