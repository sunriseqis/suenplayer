# suenplayer backend (APP_VERSION 2.1)
#
# 国内网络加速构建：
#   基础镜像走 DaoCloud 中转（也可改回 python:3.11-slim 配合 docker registry mirror）；
#   Debian apt 源与 pip 源在构建时切换为清华镜像。
# Build:  docker build -t suenplayer-backend .
# 海外构建（走官方源）:
#         docker build --build-arg BASE_IMAGE=python:3.11-slim \
#                      --build-arg USE_CN_MIRROR=0 -t suenplayer-backend .
# Run:    docker run -p 8080:8080 -v suenplayer_data:/app/data suenplayer-backend
#         （bind mount 宿主目录也可以，entrypoint 会自动修正属主）

ARG BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
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
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# /app/data holds the SQLite database, settings and downloaded files and
# must be writable by the app; ownership is fixed at startup by entrypoint.
RUN useradd --system --create-home --uid 10001 appuser

VOLUME ["/app/data"]
EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
