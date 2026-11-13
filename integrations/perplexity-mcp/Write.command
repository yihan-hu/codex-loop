#!/bin/zsh
cd -- "${0:A:h}" || exit 1
print '在 Perplexity 新建空白普通问答，选中已保存项目配置中的连接器（技能项目为 Codex Loop Mac Skills）。'
python3 shortcut.py list || exit 1
read -r 'loop_request?任务（例如 @epi prose /write Discussion 或 @epi prose /help）：'
python3 manage.py start && python3 shortcut.py run "$loop_request"
read -r '?按回车关闭此窗口。'
