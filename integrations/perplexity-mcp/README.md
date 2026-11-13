# Perplexity Q&A → Mac / Codex Loop

可选 Mac 接入：Perplexity 普通问答模型继续提供全部推理，本机程序推进会话，通过带独立密钥的 HTTPS MCP 使用现有 My Mac 后端与 Codex Loop。原 ChatGPT 接入保持独立。

完整步骤、项目保存、短命令、权限、恢复和真实验收见 **[从零设置与使用教程](../../references/perplexity-mcp-tutorial.md)**。

日常：新建空白问答、选中 **Codex Loop Mac Batch**，双击 `Write.command`，输入 `/write …`。需要先按教程配置并保存默认项目；仅在 Perplexity 输入短句不会启动本地驱动器。

这是同会话多轮写作入口，不是完整 Epi Prose 的角色隔离与生产运行时适配。`@my mac` 只作为本地启动器文字别名；`@Epi Prose` 不会被伪装成可用技能。

源码中不含密钥、机器配置或用户项目。Python 标准库、原生 Swift Accessibility、已有后端 MCP SDK/AJV；没有新模型运行时或模型 API。
