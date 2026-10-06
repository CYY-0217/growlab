# 交接文档 · 个人学习服务运营 Agent（Learner Agent）

> **⚠ 定位已调整（2026-10-03 二轮）**：从“学习服务运营”收窄为
> **“考试周学习与身心状态协调 Agent”**，主场景 = **① 赶作业挤掉吃饭休息**。
> 详细设计见 **`DESIGN.md`**（数据模型新增、安全边界、知识卡、验收标准都在里面）。
> 本文档保留架构/API/进度部分；冲突时以 DESIGN.md 的产品方向为准。
>
> **写给接手的 AI 助手（GLM zcode / Claude Code / Codex）**：请通读本文档 + DESIGN.md 再动手。
> 本文档包含：竞赛背景、已锁定的用户决策、架构、已完成进度、API 契约、
> 剩余任务排期、验收清单、纪律红线。**不要重新决策已定项**，如需变更先问用户。

---

## 1. 项目背景（为什么做）

**赛事**：大学生 OPC 创新创业 AI Agent 赛道。
- **校内截止 2026-10-08**（全国报名到 10-15，但按 10-08 执行，不延期）
- 材料：申报书及承诺书、作品介绍 PDF、演示视频（≤10 分钟、500MB）
- 要求：可体验的产品，能展示 Agent 执行任务、调用工具、交付成果；
  **不能是纯聊天助手/静态网页/PPT**

**痛点**：一人难以持续服务多位学习者（目标拆解、每日跟进、中断恢复、周报交付）。
Agent 的价值 = 把人工运营的摩擦降到零。

**历史项目（均为本仓库资产）**：
| 项目 | 位置 | 状态 | 可复用资产 |
|---|---|---|---|
| 50-Day-Discipline | `../50-Day-Discipline/index.html` | 2026-06 停更的单文件打卡器 | UI 风格、打卡交互 |
| selfagent | `../selfagent/` | 2026-09 运行 6 天后停用（5/6 天数据缺口） | 量化方法论（W-Complete/E-Factor）、6 天真实失败数据（参赛叙事证据） |

selfagent 的失败教训 = 本产品的设计原则：
- **回传摩擦必须极低**（一句话即可，系统自动解析）
- **Agent 必须主动产出**，不能等用户来问
- **未知不结算**：没回传的目标不伪造数据

## 2. 已锁定的用户决策（不要重开）

| 决策项 | 用户选择 |
|---|---|
| 痛点方向 | **一人服务多位学习者**（不是自用自律工具） |
| 团队 | 单人（用户本人），朋友当真实用户 |
| 真实用户画像 | ①平衡学业与健康的朋友 ②每天游泳要调节时间的朋友 ③想法型（突发奇想让 AI 拆解、多阅读/多思考） |
| 使用模式 | **A. 代录模式**：朋友微信告知 → 运营者录入系统 → Agent 分析 |
| 模型 API | **DeepSeek**（¥200 预算，OpenAI 兼容接口） |
| 视频 | 录屏 + PPT 讲解，5-8 分钟（不拍满 10 分钟） |
| 历史数据 | 用户自己的 50 天打卡数据在**纸质本**上，可导入 |
| 技术栈 | Python FastAPI + SQLite + DeepSeek + 原生 JS 前端（复用 50day 风格） |
| 两项目关系 | **合并不二选一**：50day 当前端基底，selfagent 方法论当大脑 |

## 3. 产品定义

**核心闭环（验收就看这条）**：
```
朋友（微信/当面）→ 运营者录入一句话 → Agent 解析成结构化完成度
→ 对照 7 日记录给出调整建议 → 运营者确认 → 入库结算 W-Complete
→ 周报交付
```

**4 类 Agent 能力**：
1. `task-breakdown` 目标拆解：目标描述 → 带权重 W/耗时/频率的任务清单（JSON）
2. `daily-adjustment` 每日解析与调整：一句话回传 → C 值 + 偏差 + 调整建议（JSON）
3. `weekly-report` 周报：7 日记录 → W-Complete 分析 + 中断模式 + 下周唯一动作（Markdown）
4. `idea-deconstruction` 想法拆解：突发奇想 → 三轴分析（概率×时间×维度）（Markdown）

## 4. 架构与文件

```
personal/learner-agent/
├── main.py              # FastAPI 入口 + 全部路由（已完成）
├── database.py          # SQLite 模型 + CRUD（已完成）
├── agent_engine.py      # DeepSeek 调用封装 + 4 个能力函数（已完成）
├── prompts.py           # 4 类提示词（已完成，D2 需实测调优）
├── static/index.html    # 单页管理界面（D1 版已完成骨架，D2 打磨）
├── HANDOVER.md          # 本文档
├── requirements.txt     # fastapi / uvicorn / openai / python-dotenv
└── .env.example         # DEEPSEEK_API_KEY 模板（.env 不入库）
```

**启动**：
```bash
cd personal/learner-agent
# 已建好 .venv（Python 3.12.14，依赖已装）。若需重装：
#   ./.venv/bin/pip install -i https://pypi.org/simple -r requirements.txt
#   （注意：系统 pip 默认走清华镜像，会找不到 fastapi，必须显式加 -i 官方源）
cp .env.example .env   # 填入 DEEPSEEK_API_KEY
./.venv/bin/uvicorn main:app --reload --port 8300
# 浏览器打开 http://127.0.0.1:8300
```
系统 Python 是 3.9.6（太老），一律用 `.venv` 里的 3.12。

**数据库**：`learner_agent.db`（SQLite，首次运行自动建表）。
4 张表：`users` / `goals` / `daily_entries` / `agent_outputs`（Agent 全部输入输出落库可追溯）。

**数据模型要点**：
- `daily_entries.checkins` 是 JSON `{goal_id: C}`，C ∈ [0,1]，**未回传目标不出现**（未知不结算）
- `settlement_status`: `pending`（默认）/ `settled` / `gap`（无回传日）
- `w_complete` 为 NULL = 未结算，**禁止填 0 伪造**
- `agent_outputs.approved`: NULL 待确认 / 1 采纳 / 0 否决

## 5. API 契约（已完成实现）

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/config` | 是否已配置 key、模型名 |
| GET/POST | `/api/users` | 列出（含统计）/ 新增学习者 |
| GET | `/api/users/{id}` | 详情：goals + 近14日 + stats + 近10条 agent 输出 |
| POST | `/api/users/{id}/goals` | 手工加单条目标 |
| POST | `/api/users/{id}/breakdown` | **Agent 拆解** `{goals_brief}` → tasks JSON |
| POST | `/api/users/{id}/goals/bulk` | 确认后批量入库 `{tasks:[...]}` |
| POST | `/api/users/{id}/entries` | **提交回传** `{entry_date, raw_text}` → Agent 解析 |
| POST | `/api/users/{id}/entries/confirm` | **确认入库** `{entry_date, checkins, agent_output_id?, approved}` |
| POST | `/api/users/{id}/report` | **周报**（Markdown） |
| POST | `/api/idea` | **想法拆解** `{user_id?, idea_text}` |
| POST | `/api/users/{id}/import-paper` | 纸质 50 天数据导入 `{days:[{date, checks:{目标名:C}, raw}]}` |
| GET | `/api/users/{id}/history?days=60` | W-Complete 序列（演示用） |
| POST | `/api/agent_outputs/{id}/decide` | `{approved}` |

注意：`api_submit_entry` 只解析不入库；**入库必须走 confirm**（改计划前有确认，改后有据可查）。

## 6. 进度与剩余任务（时间倒排）

**D1（10-03，已完成）**：后端骨架全部文件已写。
**⚠ 未验证**：Bash 工具当时被限流，依赖安装与运行验证可能未执行——接手者先做第 7 节验证。

| 天 | 日期 | 任务 |
|---|---|---|
| D2 | 10-04 | ① 跑通验证 ② 前端打磨（对齐 50day 视觉：日历热力图、阶段条）③ 4 类提示词实测调优（重点：JSON 输出稳定性、解析一句话回传的准确率）|
| D3 | 10-05 | 录入 3 位朋友（微信要来目标描述）+ 用户自己纸质 50 天数据导入 + 全流程真实跑一遍 |
| D4 | 10-06 | 朋友递 1-2 天真实进展 → 验证 Agent 输出合理性 → 修复 → 沉淀演示素材 |
| D5 | 10-07 | 录屏（结构见下）+ 申报书 + 作品 PDF |

**演示视频结构（5-8 分钟）**：
1. 问题引入（1min）：50 天纸质打卡本 + 服务朋友的需求
2. Agent 闭环（2min）：朋友目标 → 拆解 → 录入回传 → 调整建议 → 确认 → 周报
3. 中断恢复（1.5min）：漏打卡 3 天后回传 → Agent 检测中断 → 调整计划
4. 想法拆解（1.5min）：粘贴突发奇想 → 三轴结构化输出
5. 纸质数据导入 + 模式分析（1min）
6. 总结（1min）

## 7. 接手后第一步：验证清单

```bash
cd personal/learner-agent
python3 -c "import fastapi, uvicorn, openai, dotenv; print('deps ok')"  # 缺就 pip install -r requirements.txt
uvicorn main:app --port 8300 &
curl http://127.0.0.1:8300/api/config          # 应返回 configured:false（未配 key）
cp .env.example .env && $EDITOR .env           # 用户填 key
curl -X POST http://127.0.0.1:8300/api/users -H 'Content-Type: application/json' -d '{"name":"测试","category":"balance"}'
```
然后浏览器走一遍闭环：添加学习者 → 拆解 → 录入回传 → 确认 → 周报。

**提示词实测重点**（D2 核心）：
- `daily-adjustment` 对模糊回传（"今天课多没怎么学"）应返回低 C 值而非编造
- `task-breakdown` 的 JSON 必须可解析（agent_engine._parse_json 有降级，但成功率要 >90%）
- 周报对 n=1 有效日的处理：如实说样本不足，不编曲线

## 8. 纪律红线（写代码与材料时都要遵守）

1. **未知不结算**：任何没回传的数据不填 0/1，状态标 gap
2. **Agent 输出全部落库**（agent_outputs），参赛材料的证据链靠它
3. **改动前有确认**：confirm 接口是闭环的必经环节，不要做成自动采纳
4. **短期测试如实标注**：材料里写"5 天真实试用"，不宣称验证了长期效果
5. **API key 只放 .env**，绝不入 git / 前端
6. 测试数据、演示数据、真实数据分开标注（数据库可用 notes 字段区分）

## 9. 已知问题 / 注意

- **D1 已验证通过**：后端可启动，`/api/config`、`/api/users` 增查、首页均 200；
  openai 3.24.0 的 `chat.completions.create` 兼容 DeepSeek。
- ~~agent_output_id 未透传~~ ✅ 已修：`daily_adjustment` 返回 `agent_output_id`，
  前端 `confirmEntry` 用全局 `lastAdjustment` 回传，审批证据链已接通。
- ~~confirmBreakdown 把 tasks 塞进 onclick~~ ✅ 已修：改用全局 `lastBreakdown`。
- DeepSeek 模型名用户口头说 "v4 flash"，实际用 `.env` 的 `DEEPSEEK_MODEL` 配置，
  默认 `deepseek-chat`；让用户在 platform.deepseek.com 确认可用模型名（配 key 后 `configured` 变 true）
- 数据库里 D1 冒烟测试留下了一条 `id=1 name="测试"` 的用户，D3 录真实数据前删掉
  （`sqlite3 learner_agent.db "DELETE FROM users WHERE name='测试'"`）

## 10. 用户信息

- 岭南学院 AI 方向学生（数学专业背景），单人参赛，时间紧
- 可用资产：3 位朋友当真实用户、DeepSeek ¥200、纸质 50 天打卡本
- 用户会把本项目的后续实现可能交给 GLM zcode —— 一切以本文档为准，冲突时问用户
