# Shinsekai 桌面端内嵌 Python 运行时方案(python-build-standalone)

> 状态:已批准,实施中。本文件为方案 1 的实施提案与进度归档。
> 相关:[desktop_runtime_strategy.md](./desktop_runtime_strategy.md)、[shinsekai_desktop_runtime_strategy_proposal.md](./shinsekai_desktop_runtime_strategy_proposal.md)

## 背景与决策

当前桌面端在「用户机器上没有可用 Python」时只能引导用户自行安装或选择已有 Python
(`frontend/src-tauri/src/runtime/resolver.rs::scan_message`),失败面完全暴露在不可控的用户环境上
(版本、架构、缺 pip/ensurepip、PEP 668 externally-managed 等)。

**决策:采用方案 1 —— 随安装包内嵌一份 python-build-standalone(PBS)解释器,为无 Python 环境兜底。**
接受其代价(安装包/更新包体积增大),换取最高稳定性:无 Python 用户拿到一个我们完全掌控、
版本/架构正确、自带 pip/venv/ensurepip 的解释器。

### 为什么是 PBS 而非 Windows embeddable

- Windows 官方 embeddable 不带 pip/venv/ensurepip,且 `._pth` 默认关闭 `import site`,不可直接用于装依赖。
- PBS(astral-sh)是完整、可重定位的 CPython,自带 pip/venv/ensurepip,是 uv/rye 的底座。

### PBS 已知硬约束(均可在构建期选产物 + 安装期修正内消解)

- Linux gnu 构建要求 **glibc ≥ 2.17**;优化版 x86-64 需 **post-Nehalem CPU**(老 CPU 会崩)。
- musl `+static` 变体**无法加载 .so 扩展** → 必须用 **gnu 动态** 构建。
- Windows 依赖 **VC++ 运行库**;Windows 上无 `Scripts/pip.exe`,须用 `python -m pip`(现有代码已是)。
- macOS 下载二进制带 **quarantine**,需 **签名/公证**。
- PBS 含**构建期硬编码路径**,只影响**源码编译扩展**;装预编译 wheel 不受影响。
- SSL:自带 OpenSSL,部分系统缺 CA bundle,需随包 `certifi` 或设 `SSL_CERT_FILE`。

## 目标产物与范围

- 5 个构建 target(对齐 `.github/workflows/tauri-desktop.yml` 矩阵)各自内嵌匹配的 PBS 解释器。
- 首启「离线优先(随包 vendored wheels)→ 在线网络感知镜像回退」完成依赖安装。
- 无 Python 用户:装好即用、首启可全程离线;有合格 Python 用户:仍走现有检测快路径,行为不变。
- 不在范围:重构现有检测/resolver 架构(仅增量接入);PBS 多版本/卸载管理。

## 平台 × 架构 → PBS 产物映射

锁定:PBS release `20260602`,Python `3.10.20` 优先(满足 manifest `>=3.10,<3.14`)。资产命名
`cpython-<ver>+<tag>-<target>-install_only.tar.gz`,sha256 取自 GitHub Release 资产内联 `digest`。

| 构建 target | PBS target triple | 备注 |
|---|---|---|
| `linux-x64` | `x86_64-unknown-linux-gnu` | gnu 动态,baseline 变体 |
| `linux-arm64` | `aarch64-unknown-linux-gnu` | gnu 动态 |
| `windows-x64` | `x86_64-pc-windows-msvc` | 随包确认 VC++ redist |
| `windows-arm64` | `aarch64-pc-windows-msvc` | PBS 无 CPython 3.10 资产,当前锁定 3.11.15 fallback |
| `macos-arm64` | `aarch64-apple-darwin` | 签名/公证 |

## 网络环境处理

- **构建期(CI 取 PBS)**:可配置下载基址(代理/镜像)+ 失败重试 + 镜像回退;与用户网络无关。
- **运行期(首启装依赖)**:
  1. 离线优先 `pip install --no-index --find-links <bundled wheels>`;
  2. 在线回退,复用 `manifest::pip_index_urls_for_source`
     (`SHINSEKAI_PIP_INDEX_URL(S)` > `SHINSEKAI_RUNTIME_SOURCE` > `detect_network_region` 自动 china/official,多镜像故障转移);
  3. 尊重用户系统 `PIP_INDEX_URL`/`PIP_CONFIG_FILE`(已有逻辑)。

## 实施落点(关键文件)

- **锁定清单**:`frontend/src-tauri/runtime_sources.json`(本提案新增)。
- **构建脚本**:`frontend/scripts/prepare-runtime.mjs`(本提案新增),物化 `repoRoot/runtime` + `wheels/`;
  现有 `frontend/scripts/prepare-tauri-resources.mjs` 已会把 `runtime/` 拷入 `resources/`(需扩展拷 `wheels/`)。
- **矩阵校验**:`frontend/scripts/verify-runtime-matrix.mjs` 校验 PBS 清单、GitHub Actions 构建矩阵、
  matrix bundles、artifact 上传路径、Tauri resources 映射和构建前 runtime 准备命令一致。
- **产物校验**:`frontend/scripts/verify-packaged-runtime.mjs` 在 `tauri build` 后扫描 `target/release`
  构建输出,确认目标平台 runtime、wheelhouse、必需文件和 marker 已进入打包输出;Linux `.deb`/`.rpm`
  会进一步检查安装包文件列表。CI 使用 `--require-installers` 强制校验每个矩阵 target 的预期安装器文件已产出。
- **检测接入**:复用 `python_probe.rs::runtime_root_candidates` / `install_runtime_roots`(已对 `resources` 特判)。
- **provision / 缺 pip 兜底**:`runtime/managed.rs`(`ensure_python_pip_available` 增加 ensurepip→get-pip 自举)。
- **CI**:`.github/workflows/tauri-desktop.yml` 5 target build 前执行 PBS 物化,build 后校验打包输出。

## Definition of Done

1. 断网 + 无 Python 的干净机首启,自动以内嵌 PBS 完成 provision 并 Ready,bridge 正常启动。
2. 五个构建平台各自打包内嵌正确 triple,CI 全绿,产物可启动。
3. 缺部分 vendored wheels 时,联网经 china/official 镜像各验一次成功补装。
4. 有合格 Python 的机器仍走快路径不退化;`cargo test runtime` 与 UI 契约测试通过。
5. macOS 公证、首启无 Gatekeeper 拦截;Windows 无 VC++ 也能启动。
6. 缺 pip 解释器经 ensurepip/get-pip 自举成功(单测覆盖)。

## 风险登记

| # | 风险 | 缓解 |
|---|---|---|
| R1 | Linux 选到 musl static | 清单强制 gnu 动态;CI 校验 marker triple |
| R2 | 优化版 x86-64 老 CPU 崩 | 选 baseline 变体;文档标注最低 CPU |
| R3 | glibc < 2.17 | 声明最低 glibc;启动失败给清晰报错 |
| R4 | Windows 缺 VC++ redist | 随包/安装器带 redist;失败给指引 |
| R5 | macOS quarantine/未公证 | 签名+公证+清 xattr,必测 |
| R6 | PBS 硬编码构建路径 | sysconfig 修正;依赖只用 wheel |
| R7 | SSL CA 缺失 | 随包 certifi / 设 SSL_CERT_FILE |
| R8 | windows-arm64 产物缺失/不成熟 | 优先验证;缺失则该 target 降级,不阻塞其余 5 平台 |
| R9 | 内嵌与外部 Python 优先级冲突 | 明确优先级;必要时新增 Bundled kind;单测固定排序 |
| R10 | wheels 与 PBS ABI 不匹配 | 严格按 PBS py/平台/arch pip download;CI 同解释器验证可装 |
| R11 | 更新包膨胀 | 接受;锁版降频;记录后续拆 updater delta |
| R12 | provision 与 install.lock 并发 | 复用 `acquire_install_lock` |
| R13 | 多 bundler 资源路径不一致 | 各 bundle 实测;覆盖 exe-relative 与 resources |
| R14 | provision 失败无回退 | 保留重试 + SelectDifferentRuntime;失败清理暂存 |
| R15 | 体积超 CI/Release 上限 | 监控大小;压缩/strip |

## 验证方法

- 5 个构建平台 ×「无 Python+断网」/「无 Python+有网(china、official)」干净环境全链路。
- 回归:有合格 Python 走快路径不变。
- 自动化:`pnpm --dir frontend verify:runtime-matrix`;
  `pnpm --dir frontend verify:packaged-runtime --target <matrix-platform>`;
  `pnpm --dir frontend verify:packaged-runtime --target <matrix-platform> --require-installers`(CI);
  `cargo test --manifest-path frontend/src-tauri/Cargo.toml runtime`;`pnpm exec vitest run`;CI 全矩阵 + 体积报告。
- 签名:macOS `spctl`/Gatekeeper 实机;Windows 无 VC++ 机器启动。
