---
name: 发布 Tracking Issue
about: 用于跟踪一次 release/x.y code cut、RC 测试、blocker 修复和正式发布。
title: "Release tracking: v"
labels: "maintenance,p1"
assignees: ""
---

## Release

- Version:
- Release branch:
- Current RC tag:
- Owner:

## Release setup

- [ ] Root `VERSION` updated if needed
- [ ] `pnpm sync:version` run from `frontend`

## Manual smoke tests

- [ ] Windows x64 install/start/restart
- [ ] Core chat
- [ ] Plugin/tool call
- [ ] Character/template/config read-write
- [ ] Runtime diagnostics
- [ ] Updater manifest/signature

## Blockers

| Issue | Severity | Owner | Status | Fix commit | Cherry-picked |
| --- | --- | --- | --- | --- | --- |

Comment with an issue reference, such as `#123`, to automatically add it as a sub-issue and sync it into this table.

## Release decision

- [ ] Ship
- [ ] Re-spin RC
- [ ] Abort release

## Labels

labels:
  - maintenance
  - p1
