# Perplexity Q&A → 本地 Skill / Mac / Codex Loop

Perplexity 普通问答提供全部模型推理；本机程序推进会话，通过独立密钥的 HTTPS MCP 访问授权项目、登记的本地 Skill 和 Codex Loop 生命周期。无需另一个模型或模型 API。

完整安装、项目范围、短命令、恢复和验证见 **[从零设置与使用教程](../../references/perplexity-mcp-tutorial.md)**。

登记 Epi Prose 并保存项目后：在 Perplexity 新建空白问答、选中 **Codex Loop Mac Skills**，双击 `Write.command`，输入 `@epi prose /help`、`@epi prose /prepare` 或 `@epi prose /write Discussion`。也支持启动器文字别名 `@my mac@epi prose /write Discussion`。直接在 Perplexity 聊天框输入它不会启动本地驱动器。

本适配器加载原始完整技能资源，使用其固定 Python 与原 runtime；独立语义角色由真正分开的 Perplexity 无痕会话执行，父会话只接收身份与路径。所有阶段保留同一外层 task_id；Epi Prose 内层 native backend 不调用 Codex 模型。原 Epi Prose 源码和 Current 产出权限保持由它自身管理。

已验证实际技能加载、`/help`、两个独立角色会话的读写返回和公开 PDF/HTML 存档提取；尚未对真实论文运行完整生产验收。代码受信任并拥有本机用户权限，不把 argv/项目范围检查称为 OS 沙箱。源码不含密钥、机器配置或用户项目；可选 Mac 接入从本仓库安装，不在 ChatGPT Skill ZIP 中运行。
