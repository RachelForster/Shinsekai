# 简化剧情节点协议

剧情由少量节点组成。节点描述“这一段演什么”和“满足什么情况后去哪里”，
对白使用普通模板聊天链路，剧本只注入当前剧情提示；对白完成后另行判断节点跳转。

## 节点类型

- `limited_turn_node`：最多演出 `maxRounds` 轮。可以提前跳转；到达上限时必须
  输出目标节点，或者由运行时采用 `defaultTo`。
- `free_chat_node`：不限轮数。每轮可以留在当前节点，也可以跳转。
- `ending_node`：剧情终点，不包含跳转。

一轮表示一次用户输入及其对应的完整 LLM 对白输出，不是单条人物台词。

## YAML 示例

```yaml
metadata:
  backgrounds:
    - 旧校舍门口
    - 旧校舍大厅

startNodeId: school-gate

nodes:
  - id: school-gate
    title: 旧校舍门口
    type: limited_turn_node
    background: 旧校舍门口
    instruction: |
      绫邀请玩家调查旧校舍。表现她的紧张，并透露钥匙的来历。
    maxRounds: 3
    transitions:
      - to: school-lobby
        when: 玩家愿意进入旧校舍
      - to: leave-school
        when: 玩家明确拒绝或决定离开
    defaultTo: school-lobby

  - id: school-lobby
    title: 旧校舍大厅
    type: free_chat_node
    background: 旧校舍大厅
    instruction: |
      玩家可以和绫自由调查、交谈。不要替玩家作出决定。
    transitions:
      - to: leave-school
        when: 玩家明确表示离开旧校舍

  - id: leave-school
    title: 离开旧校舍
    type: ending_node
    background: 旧校舍门口
```

`when` 是提供给 LLM 的自然语言，不是条件表达式。运行时不会解释它，只校验
LLM 返回的目标是否出现在当前节点的 `transitions` 中。

## 对白与状态判断

对白沿用普通模板生成的系统提示词和 `dialog` 输出格式，包括人物、立绘、背景和
插件字段。剧本不要求对白增加状态字段，也不提供另一套对白格式。

独立的状态判断请求只分析已经发生的对话，返回：

```json
{
  "nextNodeId": "school-lobby"
}
```

留在当前节点时，`nextNodeId` 为 `null`。不要使用特殊人物名表达跳转，也不要
把节点 ID 写进台词字段。

## 运行时约束

1. 服务端只接受当前节点 `transitions[].to` 中声明的目标。
2. 每次成功生成后，当前节点的轮次加一。
3. 进入新节点时，轮次重置为零。
4. `limited_turn_node` 到达上限但没有返回目标时，采用 `defaultTo`；没有默认
   目标且未判断出合法目标时保留当前状态，继续下一轮判断，不拒绝或重写普通对白。
5. 新节点不能定义 `choices` 或 `freeformIntents`。

## AI 生成流程

新剧情只经过三个创作阶段：

1. `foundation`：标题、前提、世界规则、事实和秘密。
2. `characters`：提供故事人物的叙事参考，不限制实际说话者，不指定节点出场名单。
3. `narrative`：生成简单节点及其自然语言跳转条件，可选填地点提示。

生成器不再让 LLM 创建变量、语义信号或逻辑图。为了继续使用现有故事文件格式，
输出文件中的 `variables`、`semanticSignals` 和 `logicGraph` 由程序写成空结构。
`initialCast` 和 `maxActive` 也由人物列表自动派生，而不是由 LLM 决定。

背景列表只是生成参考，不是地点白名单；节点可以不指定背景，也可以描述新的地点。
节点切换不会直接切换背景或立绘。实际媒体输出、资源选择和 workflow 沿用普通模板，
剧本状态更新仅附加剧情进度信息。

所有简单节点共享这份故事级人物列表。节点中不允许出现 `castPolicy` 或人物 ID
列表，场景 LLM 根据当前节点的剧情要求决定本轮由谁发言。

旧节点字段目前只用于读取既有剧情工程。AI 剧情生成器只应产生本文格式。
