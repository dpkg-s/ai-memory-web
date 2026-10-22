# ai-memory-web 控制台镜像
#
# 只含**控制台**（前端静态资源 + web_console + 反向代理），不含 MCP 服务端 ——
# 上游 MCP 由 AI_MEMORY_WEB_MCP 指过去（本机、另一容器、局域网设备都行）。
#
# 构建与运行：
#   docker build -t ai-memory-web:1.11.1 .
#   docker run -d --name ai-memory-web -p 8811:8811 \
#     -v am-conf:/config \
#     -e AI_MEMORY_WEB_MCP=http://host.docker.internal:8700/mcp \
#     ai-memory-web:1.11.1
#   然后打开 http://127.0.0.1:8811 登录。
#
# 🔴 桥接网络（-p 8811:8811）下连宿主机的 MCP 会 **421 Invalid Host header**：
#    MCP 的 streamable HTTP transport 默认只放行 localhost / 127.0.0.1 作为
#    Host（防 DNS rebinding），host.docker.internal 与局域网域名同样被拒。
#    解法在 **MCP 侧**放行（实测同一 IP:端口只换 Host 头：127.0.0.1 → 200，
#    host.docker.internal → 421）：
#      AI_MEMORY_HTTP_ALLOWED_HOSTS="127.0.0.1:*,localhost:*,host.docker.internal:8700"
#    该变量是**替换**默认值，回环两项要一起写。详见 README。
#    ⚠️ 不要指望 --network host：Docker Desktop for Windows/macOS 下它是 VM 的
#    网络命名空间，既连不到宿主机回环，外部也访问不到容器端口（实测拒连）。
#
# 🔴 默认账号 admin / password 是**首次启动的种子**：
#    web_console 只在 /config/users.json 为空时用它建初始管理员（存 scrypt 哈希，
#    磁盘上没有明文）。一旦在「访问控制」页改过口令，环境变量就不再起作用 ——
#    这是刻意的，否则每次重启都会把口令打回默认值。
#    对外暴露前请务必改掉；改不了就删掉 /config 卷重来。
#
# 🔴 多架构：本文件用 pip 装依赖，构建时需要网络。设备离线构建请用
#    设备侧的 Dockerfile.offline（基座镜像里已装好 mcp），二者 ENV 保持一致。

FROM python:3.13-slim

LABEL org.opencontainers.image.title="ai-memory-web" \
      org.opencontainers.image.description="ai-memory Web 控制台（调试台 + 配置面 + 访问控制）" \
      org.opencontainers.image.source="https://github.com/dpkg-s/ai-memory-web" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AI_MEMORY_WEB_HOST=0.0.0.0 \
    AI_MEMORY_WEB_PORT=8811 \
    AI_MEMORY_WEB_CONFIG=/config/config.json \
    AI_MEMORY_WEB_USERS=/config/users.json \
    AI_MEMORY_WEB_TOKENS=/config/tokens.json \
    AI_MEMORY_DIR=/vault \
    AI_MEMORY_WEB_USER=admin \
    AI_MEMORY_WEB_PASSWORD=password

WORKDIR /app

# 依赖单独一层：改源码不会重装 mcp（它带 starlette/uvicorn/httpx，装一次几十秒）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 非 root 运行；/config 是唯一需要写权限的目录
RUN groupadd -g 10001 amweb \
 && useradd -u 10001 -g 10001 -M -s /usr/sbin/nologin amweb \
 && mkdir -p /config /vault \
 && chown -R 10001:10001 /config

USER 10001

VOLUME ["/config"]
EXPOSE 8811

# 探活打 /api/session（公开端点）。别用 /api/health —— 开启登录后它要 401，
# 容器会被判成不健康然后反复重启。
# 端口读环境变量：用 --network host 或改 AI_MEMORY_WEB_PORT 时硬编码会误判。
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; p=os.environ.get('AI_MEMORY_WEB_PORT','8811'); urllib.request.urlopen('http://127.0.0.1:%s/api/session'%p, timeout=2)"

CMD ["python", "serve_web.py"]
