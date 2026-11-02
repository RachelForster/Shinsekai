---
name: shinsekai-plugin-development
description: 为 Shinsekai 设计、起草和检查基于现有 SDK 的 Python 插件。在用户要求写插件、扩展功能、创建插件脚手架或修复插件时使用。
metadata:
  version: "1.0.0"
---

# Shinsekai 插件开发

先确定插件功能、输入输出、配置和需要的 SDK 扩展点。代码使用真实提供的 SDK 接口；没有源码或参考资料支撑的接口不要编造。

## 当前 SDK 基础

插件是 `plugins/<package>/` 下的 Python 包，入口指向 `sdk.plugin.PluginBase` 的子类。
实例用无参数构造创建，宿主调用 `initialize(register, plugin_root, host)` 注册能力，退出时调用 `shutdown()`。
`plugin_id` 是必需的稳定标识；可提供 `plugin_version`、名称、描述和优先级。
注册接口由 `sdk.register.PluginCapabilityRegistry` 提供。插件使用 SDK 窄接口与宿主交互，不直接依赖 application 或 bridge 实现。

有工作目录与执行工具时，可在独立 workspace 运行应用已有的脚手架命令；必须先核对执行环境与目标目录：

```text
python -m sdk.cli create my_plugin --root <workspace> --plugin-id com.example.my_plugin --display-name "My Plugin"
```

包名使用小写 snake_case，例如 `my_plugin`。脚手架生成 `plugins/my_plugin/`，默认带设置页示例；`--minimal` 生成最小插件。
上述命令是可执行步骤，只有工具返回成功或用户提供执行证据后才能说脚手架已生成。

## 最小代码草稿

```python
from pathlib import Path
from sdk.plugin import PluginBase
from sdk.plugin_host_context import PluginHostContext
from sdk.register import PluginCapabilityRegistry


class MyPlugin(PluginBase):
    @property
    def plugin_id(self) -> str:
        return "com.example.my_plugin"

    def initialize(
        self,
        register: PluginCapabilityRegistry,
        plugin_root: Path,
        host: PluginHostContext,
    ) -> None:
        # 在此使用已核实的 SDK 接口注册所需能力。
        pass

    def shutdown(self) -> None:
        pass
```

这段代码只有生命周期骨架，没有实现业务功能。新增能力时核对对应注册方法、回调签名和生命周期，不把 Qt 旧 UI 接口当作当前 React 页面方案。

## 实施与交付

1. 在任务 workspace 起草工程，复用现有脚手架。没有文件工具时，交付文件名与代码内容。
2. 只加入功能所需的依赖，并说明安装方法。配置避免硬编码秘密。
3. 用已有检查工具检查代码与入口；若有可用运行环境，再做实际业务验证。不要在 bridge 内 import 生成代码来执行校验。
4. 总结文件与 diff、真实检查结果、未验证内容。代码生成不等于检查通过。
5. 按应用现有插件安装和启用流程提交。没有安装工具时，引导用户到 `/settings/plugins`；不能声称已安装、启用或发布。

插件启用后会在宿主进程运行，因此工程检查与安装是不同步骤。只对实际工具结果确认的状态作完成声明。
