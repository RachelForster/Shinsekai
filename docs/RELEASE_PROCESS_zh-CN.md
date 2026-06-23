# Shinsekai 发布流程

本文定义 Shinsekai 的发布分支、预发布测试、缺陷修复和正式发布流程。目标是让 `main` 持续开放开发，同时给每次发布一个稳定、可测试、可回滚的候选分支。

## 分支角色

- `main`: 主开发分支。所有功能、修复和重构默认先进 `main`，通过 PR、CI 和 code review 保护质量。发布期间不冻结 `main`。
- `release/x.y`: 发布候选分支，只接受当前版本必须修复的 bug、发布脚本、版本号、文档和配置修正。禁止合入新功能和大重构。
- `feat/*`, `fix/*`, `chore/*`: 日常开发分支，合入目标通常是 `main`。

示例：

```bash
git checkout main
git pull --ff-only
git checkout -b release/2.1
git push -u origin release/2.1
```

## 发布节奏

1. **Code cut**
   - 从当前 `main` 切出 `release/x.y`。
   - 如需调整发布版本，先修改根目录 `VERSION`，然后在 `frontend` 目录运行 `pnpm sync:version`，由脚本同步所有版本文件。
   - 推送 `release/x.y` 分支。不要手动创建 release tracking issue；它会在 Release workflow 首次运行时自动创建或复用。

2. **RC 构建**
   - 在 `release/x.y` 上手动触发 Release workflow，生成 prerelease 包。
   - Release workflow 会自动创建或更新 `Release tracking: vx.y.z` issue，并填入人工冒烟测试清单、阻塞问题表格和发布负责人。
   - tag 使用 `vx.y.z-rc.n`，例如 `v2.1.0-rc.1`。
   - RC 只给测试者使用，不标记为 latest。

3. **预发布测试**
   - 不重复要求 `main` 已经通过的自动测试矩阵。RC 阶段只验证当前候选包和 release 分支上的 blocker 收敛。
   - 至少覆盖以下人工冒烟测试：
     - Windows x64 安装、启动、退出、再次启动
     - 核心聊天流程
     - 插件/工具调用基础流程
     - 角色、模板、配置读写
     - 本地 runtime 检测和缺失依赖提示
     - 自动更新 manifest 生成和签名检查

4. **RC bug 修复**
   - 默认先把修复 PR 合入 `main`。
   - 再把同一个修复 cherry-pick 到 `release/x.y`。
   - 如果 bug 只存在 release 分支，可以直接修 release 分支，但需要在 PR 描述里说明为什么不需要回灌 `main`。
   - RC 测试中发现的每个 bug 都单独开 `RC Bug` issue，并填写 `Parent release: vx.y.z` 或 `Parent tracking issue: #123`。GitHub Actions 会把这些 bug 自动挂到 release tracking issue 的 sub-issues 下，并同步到 Blockers 表格。
   - 也可以直接在 release tracking issue 里评论 `#123` 或 issue URL，GitHub Actions 会把评论中提到的 issue 挂成 sub-issue，并补入 Blockers 表格。

推荐命令：

```bash
git checkout main
git pull --ff-only
# 合入修复 PR 后记录 commit sha

git checkout release/2.1
git pull --ff-only
git cherry-pick -x <fix_commit_sha>
git push
```

`-x` 会在提交信息里记录来源 commit，方便追踪 release 分支和 `main` 的差异。

5. **重新出 RC**
   - 每批阻塞 bug 修完后递增 RC 号，例如 `v2.1.0-rc.2`。
   - 不要复用旧 RC tag。
   - tracking issue 里记录每个 RC 的 commit、构建链接、已知问题和测试结论。

6. **正式发布**
   - 当 `release/x.y` 没有阻塞问题，且测试矩阵通过，从 release 分支打正式 tag：

```bash
git checkout release/2.1
git pull --ff-only
git tag -a v2.1.0 -m "Release v2.1.0"
git push origin v2.1.0
```

   - Release workflow 由正式 tag 构建发布包。
   - 正式 release 可以标记为 latest；RC 保持 prerelease。
   - 发布后确认下载资产、`latest.json`、安装包签名和版本号。

7. **发布后收尾**
   - 确认 `release/x.y` 上所有修复已经存在于 `main`。
   - 关闭 tracking issue。
   - 保留 release 分支一段时间用于热修；下个 minor/major 发布后可归档或删除旧分支。

## Hotfix 流程

当正式版本发布后发现严重问题：

1. 从对应正式 tag 或 `release/x.y` 切 `hotfix/x.y.z`。
2. 修复优先合入 `main`。
3. cherry-pick 到 `hotfix/x.y.z` 或 `release/x.y`。
4. 跑完整 RC 测试，至少出一个 `vx.y.z+1-rc.1`。
5. 通过后打正式 patch tag，例如 `v2.1.1`。

## 合入规则

- `main` 的 PR 必须通过自动测试并经过 review。
- `release/x.y` 的 PR 只允许以下类型：
  - `fix:*`
  - `test:*`
  - `ci:*`
  - `docs:*`
  - `chore(release):*`
- release 分支禁止 squash 多个无关修复；每个 cherry-pick 应保持原始修复的边界。
- release 分支禁止直接合入 feature branch。
   - 如果必须跳过某项人工冒烟测试，tracking issue 必须记录原因、风险、替代验证方式和负责人。

## GitHub ruleset

仓库已经为 `main` 配置 ruleset。`release/*` 不需要单独维护一套保护规则，直接复用或纳入现有 main ruleset 即可，确保发布分支和 `main` 使用一致的合入约束。

## 发布放行标准

发布负责人只有在以下条件都满足时才能打正式 tag：

- 当前 RC 有成功产出的 prerelease 包。
- 当前 RC 至少完成一次安装包验证。
- 本次 release 纳入的 feature/bugfix 变更应具备相关测试覆盖；新增或实质修改代码的测试覆盖率目标为 85%。如果无法达到，需要在 release tracking issue 中记录原因、风险和替代验证方式。
- 没有 P0/P1 blocker。
- 所有 P2 问题已有明确处理结论：修复、延期或已知问题。
- 版本号已通过 `pnpm sync:version` 同步，Release workflow 的版本一致性检查通过。
- release notes 已覆盖用户可见变化、破坏性变化、已知问题和升级提示。
- 回滚方案明确：上一个稳定 tag 和对应 release asset 可用。
