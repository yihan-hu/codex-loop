#!/bin/zsh
cd -- "${0:A:h}" || exit 1
python3 manage.py stop
read -r '?按回车关闭此窗口。'
