# suenplayer backend (APP_VERSION 2.1)
#
# 多阶段构建：frontend 阶段构建前端（国内走 npmmirror），runtime 阶段组装。
# 国内网络加速构建：
#   基础镜像走 DaoCloud 中转；npm/pip/apt 源在构建时切换为国内镜像。
# Build:  docker build -t suenplayer-backend .
# 海外构建（走官方源）:
#         docker build --build-arg BASE_IMAGE=python:3.11-slim \
#                      --build-arg NODE_IMAGE=node:20-slim \
#                      --build-arg USE_CN_MIRROR=0 -t suenplayer-backend .
# Run:    docker run -p 8080:8080 -v suenplayer_data:/app/data suenplayer-backend
#         （bind mount 宿主目录也可以，entrypoint 会自动修正属主）

ARG BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
ARG NODE_IMAGE=docker.m.daocloud.io/library/node:20-slim

# ── 阶段 1：前端构建 ──
FROM ${NODE_IMAGE} AS frontend
ARG USE_CN_MIRROR=1
WORKDIR /build
COPY static/package.json static/package-lock.json ./
RUN if [ "$USE_CN_MIRROR" = "1" ]; then npm config set registry https://registry.npmmirror.com; fi \
    && npm ci
COPY static/ ./
RUN npm run build

# ── 阶段 2：运行镜像 ──
FROM ${BASE_IMAGE}
ARG USE_CN_MIRROR=1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Debian apt 换清华源；gosu 用于 entrypoint 降权；
# jpegtran（libjpeg-turbo-progs）是封面无损压缩的依赖
RUN if [ "$USE_CN_MIRROR" = "1" ]; then \
        sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
        sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends libjpeg-turbo-progs gosu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
# pip 换清华镜像（USE_CN_MIRROR=0 时走官方 PyPI）
RUN if [ "$USE_CN_MIRROR" = "1" ]; then \
        pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

COPY app.py config.py quick.py ./
COPY --from=frontend /build/dist /app/static/dist

# entrypoint 直接内嵌（无需额外文件，避免构建上下文缺文件失败）
COPY <<'EOF' /usr/local/bin/entrypoint.sh
#!/bin/sh
# root 启动时修正挂载数据卷属主后降权 appuser；bind mount / 命名卷均可自愈
if [ "$(id -u)" = "0" ] && command -v gosu >/dev/null 2>&1; then
    mkdir -p /app/data
    chown -R appuser:appuser /app/data 2>/dev/null || true
    exec gosu appuser "$@"
fi
exec "$@"
EOF
RUN chmod +x /usr/local/bin/entrypoint.sh

# /app/data holds the SQLite database, settings and downloaded files and
# must be writable by the app; ownership is fixed at startup by entrypoint.
RUN useradd --system --create-home --uid 10001 appuser

VOLUME ["/app/data"]
EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
