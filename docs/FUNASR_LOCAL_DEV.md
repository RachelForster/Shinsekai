# FunASR 本地开发部署

这份说明用于本地开发 `funasr_wss` 插件前，先把 FunASR WebSocket 服务跑起来。

## 为什么这样配

- 使用 FunASR 官方 realtime runtime Docker 镜像
- 启动 `2pass` 服务，便于后续插件同时接收 partial / final 结果
- 默认关闭 SSL：本地联调用 `ws://127.0.0.1:10096` 更直接
- 模型和热词文件挂载到宿主机 `./funasr-runtime-resources/models`

## 启动

在项目根目录执行：

```bash
mkdir -p funasr-runtime-resources/models
docker compose -f docker-compose.funasr.yml up -d
```

首次启动会下载镜像和模型，耗时会比较长。

## 查看日志

```bash
docker compose -f docker-compose.funasr.yml logs -f
```

如果看到类似 WebSocket 服务开始监听端口的日志，就说明服务已经起来了。

## 停止

```bash
docker compose -f docker-compose.funasr.yml down
```

## 重启

```bash
docker compose -f docker-compose.funasr.yml restart
```

## 本地联调建议

插件首版建议使用下面这组连接参数：

- host: `127.0.0.1`
- port: `10096`
- use_ssl: `false`
- mode: `2pass`

对应关系是：

- 宿主机端口 `10096`
- 容器内 FunASR 服务端口 `10095`

## 验证服务是否可用

最简单的是先看日志。

如果你后面还想做更严格的验证，可以再补一段最小 Python websocket client，向 `ws://127.0.0.1:10096` 发送 PCM 音频并检查是否返回 partial/final transcript。

## 可能遇到的问题

- 首次拉模型慢：这是正常现象，尤其是第一次启动
- Apple Silicon/macOS：FunASR 官方 runtime 文档写明 ARM64 镜像已支持，但个别版本可能有兼容波动；这份 compose 固定用了文档中的 `funasr-runtime-sdk-online-cpu-0.1.13`
- 如果启动失败：先执行日志命令确认是镜像拉取、模型下载、还是容器内路径问题
