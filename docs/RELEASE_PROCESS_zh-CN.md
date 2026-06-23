# Shinsekai 发布流程

本文定义 Shinsekai 的发布分支、RC 验证、缺陷收敛、cherry-pick 和正式发布流程。目标是：`main` 保持正常开发节奏，发布工作在 `release/x.y` 分支上收敛，避免因为发版冻结主线。

## 分支职责

- `main`：主开发分支。功能、修复和重构默认先进 `main`，通过 PR、CI 和 review 保证质量。发布期间不冻结 `main`。
- `release/x.y`：发布候选分支。只接受当前版本必须带上的修复、发布配置、版本号同步、文档和 CI 调整，不合入新功能或大重构。
- `feat/*`、`fix/*`、`chore/*`：日常开发分支，默认合入目标是 `main`。

## 总体原则

- 发布从 `main` code cut，不在 `main` 上直接发布。
- RC 阶段不重复验证 `main` 已经通过的完整自动测试矩阵，只验证候选包、安装体验、核心路径和 blocker 收敛。
- RC 发现的 bug 单独开 issue，挂到 release tracking issue 的 sub-issues 下，并进入同一个 milestone。
- 修复默认先合入 `main`，再 cherry-pick 到 `release/x.y`。
- GitHub Actions 负责创建 tracking issue、milestone、同步 sub-issues、更新 Blockers 表格和流转 cherry-pick 状态。

## 1. Code Cut

从最新 `main` 切出发布分支：

```bash
git checkout main
git pull --ff-only
git checkout -b release/2.1
git push -u origin release/2.1
```

如果本次发布需要调整版本号，先修改根目录 `VERSION`，再在 `frontend` 目录运行：

```bash
pnpm sync:version
```

这个脚本会把版本号同步到前端 package、Tauri Cargo/runtime manifest 等相关文件。不要手动全局替换版本号。

不要手动创建 release tracking issue。第一次运行 Release workflow 时，它会自动创建或复用 `Release tracking: vx.y.z`。

## 2. RC 构建

在 `release/x.y` 分支上手动触发 Release workflow，输入 RC tag，例如：

```text
v2.1.0-rc.1
```

Release workflow 会自动完成这些事：

- 创建或更新 `Release tracking: v2.1.0`
- 创建或复用 `v2.1.0` milestone
- 把 tracking issue 挂到该 milestone
- 在 tracking issue 中写入人工冒烟测试清单、Blockers 表格和本次 workflow run 记录
- 生成 prerelease 包

RC 包只用于测试，不标记为 latest。

## 3. RC 验证

RC 验证重点是候选包本身，不重复要求 `main` 已经通过的全量自动测试。

至少完成以下人工测试：

- Windows x64 安装、启动、退出、再次启动
- 核心聊天流程
- 插件/工具调用基础流程
- 角色、模板、配置读写
- 本地 runtime 检测和缺失依赖提示
- 自动更新 manifest 生成和签名检查

如果某项人工测试必须跳过，需要在 release tracking issue 中记录原因、风险、替代验证方式和负责人。

## 4. RC Bug 跟踪

RC 测试中发现的每个 bug 都单独开 `RC Bug` issue。

开 issue 时填写以下任意一种关联方式：

```markdown
- Parent release: v2.1.0
```

或：

```markdown
- Parent tracking issue: #123
```

GitHub Actions 会自动把该 bug：

- 挂到对应 release tracking issue 的 sub-issues 下
- 同步到 tracking issue 的 Blockers 表格
- 继承 release milestone

也可以直接在 release tracking issue 里评论 bug issue，例如：

```markdown
#456
```

或粘贴 issue URL。Actions 会把评论中提到的 issue 挂成 sub-issue，并同步 Blockers 表格和 milestone。

## 5. Bug 修复与 Cherry-Pick

默认修复路径是：

1. 修复 PR 先合入 `main`
2. 再把同一个修复 cherry-pick 到 `release/x.y`

修复 PR 必须关联对应 RC bug issue。推荐在 PR 评论中使用现有 link workflow：

```markdown
/link owner/repo#123
```

对于 release bug，link workflow 会自动写入：

```markdown
Refs owner/repo#123
```

不要在合入 `main` 的修复 PR 中使用 `Fixes #123`、`Closes #123` 或 `Resolves #123`，否则 GitHub 可能会在修复尚未 cherry-pick 到 release 分支前提前关闭 RC bug。

状态流转由 GitHub Actions 自动处理：

- RC bug 新建后默认为 `needs-fix`
- 修复 PR 合入 `main` 后，状态变为 `fixed-on-main` + `needs-cherrypick`
- cherry-pick PR 合入 `release/x.y` 后，状态变为 `cherry-picked`
- 每次状态变化都会刷新 tracking issue 的 Blockers 表格

推荐 cherry-pick 命令：

```bash
git checkout release/2.1
git pull --ff-only
git cherry-pick -x <fix_commit_sha>
git push
```

`-x` 会在提交信息中记录来源 commit，方便追踪 release 分支与 `main` 的差异。

如果 bug 只存在于 release 分支，可以直接修 release 分支，但 PR 描述里需要说明为什么不需要回灌 `main`。

## 6. 重新出 RC

每批 blocker 修完后递增 RC 号，例如：

```text
v2.1.0-rc.2
```

不要复用旧 RC tag。每次重新运行 Release workflow 时，已有 tracking issue 不会被重置；workflow 只会追加本次运行记录。

## 7. 正式发布

当 release 分支没有 P0/P1 blocker，且当前 RC 通过放行标准后，从 `release/x.y` 打正式 tag：

```bash
git checkout release/2.1
git pull --ff-only
git tag -a v2.1.0 -m "Release v2.1.0"
git push origin v2.1.0
```

正式 tag 会触发 Release workflow 构建正式发布包。正式 release 可以标记为 latest；RC 始终保持 prerelease。

发布后确认：

- release assets 可下载
- `latest.json` 正确生成
- 安装包签名有效
- 版本号正确
- release notes 覆盖用户可见变化、破坏性变化、已知问题和升级提示

## 8. 发布后收尾

发布完成后：

- 确认 `release/x.y` 上的所有修复都已经存在于 `main`
- 关闭 release tracking issue
- 关闭或归档 milestone
- 保留 release 分支一段时间用于 hotfix

## Hotfix

正式发布后如果发现严重问题：

1. 从对应正式 tag 或 `release/x.y` 切出 `hotfix/x.y.z`
2. 修复优先合入 `main`
3. cherry-pick 到 hotfix 或 release 分支
4. 至少出一个新的 RC，例如 `v2.1.1-rc.1`
5. 验证通过后打正式 patch tag，例如 `v2.1.1`

## 合入规则

- `main` PR 必须通过自动测试并经过 review。
- `release/x.y` PR 只允许以下类型：
  - `fix:*`
  - `test:*`
  - `ci:*`
  - `docs:*`
  - `chore(release):*`
- release 分支禁止直接合入 feature branch。
- release 分支禁止把多个无关修复 squash 成一个提交；每个 cherry-pick 应保持原始修复边界。

## GitHub Ruleset

仓库已经为 `main` 配置 ruleset。`release/*` 不需要单独维护另一套保护规则，直接复用或纳入现有 main ruleset 即可，确保发布分支和 `main` 使用一致的合入约束。

## 发布放行标准

发布负责人只有在以下条件都满足时才能打正式 tag：

- 当前 RC 有成功产出的 prerelease 包。
- 当前 RC 至少完成一次安装包验证。
- 本次 release 纳入的 feature/bugfix 变更具备相关测试覆盖；新增或实质修改代码的测试覆盖率目标为 85%。如果无法达到，需要在 release tracking issue 中记录原因、风险和替代验证方式。
- 没有 P0/P1 blocker。
- 所有 P2 问题已有明确处理结论：修复、延期或列为已知问题。
- 版本号已通过 `pnpm sync:version` 同步，Release workflow 的版本一致性检查通过。
- release notes 已覆盖用户可见变化、破坏性变化、已知问题和升级提示。
- 回滚方案明确：上一个稳定 tag 和对应 release assets 可用。
