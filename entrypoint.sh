#!/bin/sh
# 容器以 root 启动时，修正挂载数据卷的属主后降权到 appuser；
# 使 bind mount（宿主目录任意属主）与命名卷都能正常写入。
if [ "$(id -u)" = "0" ] && command -v gosu >/dev/null 2>&1; then
    mkdir -p /app/data
    chown -R appuser:appuser /app/data 2>/dev/null || true
    exec gosu appuser "$@"
fi
exec "$@"
