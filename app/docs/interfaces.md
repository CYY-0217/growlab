# 接口与数据模型（interfaces）

> 已有实现 + Design V2 新增。状态：✅已实现 / 🟡拟新增 / ⬜占位。

## 1. 现有 API（✅ 已实现，可复用）

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/config` | key 配置状态 |
| GET/POST | `/api/users` | 列（含 stats）/ 增 |
| GET | `/api/users/{id}` | 详情（goals+entries+stats+outputs） |
| POST | `/api/users/{id}/goals` | 加目标 |
| POST | `/api/users/{id}/breakdown` | Agent 拆解 |
| POST | `/api/users/{id}/goals/bulk` | 确认后批量入库 |
| POST | `/api/users/{id}/entries` | 提交回传→Agent 解析 |
| POST | `/api/users/{id}/entries/confirm` | 确认入库结算 |
| POST | `/api/users/{id}/report` | 周报 |
| POST | `/api/idea` | 想法拆解 |
| POST | `/api/agent_outputs/{id}/decide` | 审批 Agent 输出 |
| POST | `/api/users/{id}/import-paper` | 纸质数据导入 |
| GET | `/api/users/{id}/history` | W-Complete 序列 |

## 2. 现有数据表（✅）

`users` / `goals` / `daily_entries` / `agent_outputs` —— 见 `database.py`，保留。

## 3. 新增数据表（🟡 拟新增，实现时建）

| 表 | 字段 | 对应模块 |
|---|---|---|
| `explorations` | id, user_id, direction, stance(想试/不确定/不喜欢/暂放), hypothesis, created_at | A |
| `scenarios` | id, title, roles_json, background, goal, constraints, content_version | B/G |
| `scene_runs` | id, user_id, scenario_id, branch_timeline_json, key_nodes, replay_records, behavior_basis | B |
| `discussions` | id, user_id, question, perspectives_json, assumptions_map, user_choice, reason | C |
| `learning_events` | id, user_id, goal_id, mode, feedback_style, prompted_or_independent, result | D |
| `experiments` | id, user_id, hypothesis, action, record_what, review_date, outcome, expected_vs_actual, keep_or_drop | E |
| `memory_entries` | id, user_id, kind(偏好/假设/经历/作品), content, source_ref, editable, deleted | F |
| `knowledge_cards` | id, topic, source, source_date, supports, not_supports, feature_hypothesis, how_to_verify, risk_limits, verified | G |
| `content_versions` | id, content_type, version, status(draft/review/approved), limits | G |
| `failure_cases` | id, module, scenario, symptom, repro_steps, report | G |
| `consent_log` | id, user_id, scope, granted, created_at | 隐私 |

## 4. 新增 API（🟡 拟新增，示意）

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/explore` | 提交模糊感受→探索地图+小实验 |
| POST | `/api/scenes/{id}/run` | 情境推进 |
| POST | `/api/scenes/{id}/replay` | 分支重演 |
| POST | `/api/discuss` | 多视角圆桌 |
| POST | `/api/experiments` | 建实验 / 回访 |
| GET | `/api/growth-map` | 成长档案（可编辑/删除） |
| GET/POST | `/api/memory/{id}` | 查看/纠正/删除记忆 |
| POST | `/api/knowledge-cards` | 研究卡管理（后台） |

> 具体字段在实现时细化；以上是契约形状，非最终 schema。

## 5. 调用角色定义

| 角色 | 职责 | 备注 |
|---|---|---|
| 教练 | 学习工坊 D、实验室 E 的主角色 | 三种反馈方式可切换 |
| 模拟角色 | 情境剧场 B | 多角色独立，标注“非预测真人” |
| 视角角色 | 多视角圆桌 C | 同模型多角色，标“共享偏见” |
| 探索教练 | 探索空间 A | 不诊断不定型 |
| 研究 Agent | 工作台 G | 人工核验后放行 |
| 评审/评测 Agent | 独立验收 | 新上下文测试、失败案例 |

## 6. 权限与安全边界（接口层）

- 所有 Agent 输出走 `agent_outputs` 落库，可追溯
- 敏感自述（疲惫/压力）默认不入运营者视图；展示需 `consent_log` 同意
- 删除/纠正记忆：`memory_entries.deleted` 软删 + 停止影响后续
- 未配置模型时接口返回 503，不做假联调
