# 真实帧立绘动画

Shinsekai 默认仍兼容单张静态立绘。若某个立绘条目额外配置了
`animation_manifest`，聊天窗会优先读取 manifest 中的 spritesheet 行，并按
`durations_ms` 播放真实帧；读取失败时回退到该条目的 `path` 静态图。

## 角色配置示例

`data/config/characters.yaml` 中的单个立绘条目可写成：

```yaml
sprites:
  - path: data/sprite/nanami/idle-fallback.png
    animation_manifest: data/sprite/nanami/animation-manifest.json
    animation_state: idle
```

字段说明：

- `path`：必填，静态 fallback 图；旧角色包只配置这个字段即可。
- `animation_manifest`：可选，真实帧动画 manifest 路径。
- `animation_state`：可选，manifest 的 `rows[].name`；为空时默认播放 `idle`。

## Manifest 格式

当前支持横向 spritesheet，每一行代表一个状态：

```json
{
  "cell_size": [512, 896],
  "columns": 12,
  "rows": [
    {
      "name": "idle",
      "frame_count": 12,
      "durations_ms": [100, 80, 80, 80, 100, 80, 80, 80, 100, 80, 80, 140]
    }
  ],
  "spritesheet_png": "final-spritesheet.png"
}
```

`spritesheet_png` / `spritesheet_webp` 可使用相对 manifest 所在目录的路径。
如果没有 `durations_ms`，会使用该行的 `duration_ms` 作为等长帧间隔。

这个机制只播放已经存在的真实帧，不会在前端生成补间动作。
