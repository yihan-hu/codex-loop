#!/bin/zsh
cd -- "${0:A:h}" || exit 1
print '在 Perplexity 新建空白普通问答，选中 Codex Loop Mac Batch。'
python3 shortcut.py list || exit 1
read -r 'loop_request?任务（例如 /write 一段面向科研人员的英文说明）：'
python3 manage.py start && python3 shortcut.py run "$loop_request"
read -r '?按回车关闭此窗口。'
