# 任务 4｜跨模块流程验证结果

## 运行方式
```
./.venv/bin/python docs/review/flow-tests/test_flows.py
```
- 隔离：切到临时 SQLite 库，不碰正式 `learner_agent.db`，跑完自动清理。
- 无模型调用、无付费调用。

## 结果：11 项全 PASS

| 流程 | 断言 | 实际 |
|---|---|---|
| 成长事件 draft→confirm | 创建为 draft，确认后 confirmed 且摘要可改 | ✅ |
| 暂停/取消 | draft 列表不含已确认；草稿可删除 | ✅ |
| 导演模式 | run 持久化 director（focus/intensity/feedback） | ✅ |
| 分支提取 | `_run_to_branches` 提取用户说法+角色回应 | ✅ |
| 实验 | 创建 → 复盘 done + outcome | ✅ |
| 经验卡 | 收藏 → 编辑生效 → 删除 | ✅ |
| 自律→宠物 | 打卡给宠物 +10 经验 | ✅ |
| 自律→农场 | 打卡解锁种植额度（3+打卡数） | ✅ |

## 未验证 / 待确认

### 1. 真实模型联调（待确认，未调用）
- `scene_character` / `scene_compare` / `explore` / `scene_generate` 需要真实 DeepSeek 调用；本批**不新增付费模型调用**，只验证了它们依赖的数据结构（scene_runs/events/experiments/cards 等）。
- 这些接口历史上已用真实模型跑通过（见既有记录），但本批未重跑。

### 2. 浏览器流程（未验证）
- 上述 PASS 是**数据层/接口层**结果；「探索→剧场→实验」的**前端交接 UI、刷新恢复、失败后输入保留、窄屏、键盘操作**，需真实浏览器点一遍才能确认。
- 依据：`docs/review/ux-audit.md`（代码级）+ 上述数据层测试，不等同浏览器通过。

### 3. 模拟模型说明
- 本批测试里**未模拟任何模型输出**；涉及模型生成内容的环节直接跳过，仅测数据结构。无「模拟模型冒充真实」的情况。

## 失败证据
- 无（11 项全过）。若后续有失败，会在此列 FAIL 项 + 实际输出。
