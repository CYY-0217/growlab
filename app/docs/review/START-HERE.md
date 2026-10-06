# 复审批次 · 起点（START HERE）

> 批次日期：2026-10-03。本轮仅**收集与验证**，未改正式产品代码、未部署、未重置数据库、未读取密钥/真实库内容。

## 一、本批实际完成了什么

| 任务 | 交付物 | 状态 |
|---|---|---|
| 1 审查设计 Skill | `skill-audit.md`、`skill-patch-proposal.md`（触发案例含在 audit 内） | ✅ 完成 |
| 2 两个视觉预览 | `previews/preview-a.html`、`preview-b.html`、`preview-shared.css`、`previews/README.md` | ✅ 完成 |
| 3 模板感/可用性审查 | `ux-audit.md` | ✅ 完成 |
| 4 跨模块流程验证 | `flow-tests/test_flows.py`、`flow-tests/RESULTS.md` | ✅ 完成（11 项 PASS） |
| 5 独立复审与汇总 | 本文件 + 文末自检 | ✅ 完成（自检，非独立审查） |

## 二、两个预览怎么打开
- 预览 A（标本编辑+单色图解）：`docs/review/previews/preview-a.html`
- 预览 B（标本编辑+记忆图谱）：`docs/review/previews/preview-b.html`
- 双击即可在浏览器打开；页面内顶部按钮切换「结果/空/加载/错误」四种状态。

## 三、已验证 / 失败 / 未验证

**已验证**
- Skill 已安装、已被 Claude Code 识别（出现在本会话可用 skill 列表）。
- 跨模块数据层流程 11 项断言全 PASS（临时隔离库，见 `flow-tests/RESULTS.md`）。
- 两个预览 HTML/CSS 文件存在、可读、`node --check` 无 JS 语法错误。

**失败**
- 无。

**未验证（如实）**
- 视觉渲染：本批环境**无视觉能力**，两个预览、探索首页改版、全产品页面均未截图查看。
- 浏览器流程：交接 UI 的「修改/取消/刷新恢复/失败保留输入/窄屏/键盘」，未跑真实浏览器。
- 真实模型联调：`scene_character/scene_compare/explore/scene_generate` 需 DeepSeek，本批未调用（不新增付费调用）。
- 新会话触发测试：Skill 是否在**新会话**正向触发/纯后端不触发，未执行。

## 四、正式产品最值得先改的三个问题
1. **评估徽章缺「模型判断」免责标注**（`ux-audit.md` B1）——三个 ✓✗ 易被当成客观评分。
2. **六页同质卡片矩阵**（`ux-audit.md` E1）——除探索外，自律/实验室/档案/萌宠/卡牌同骨架，模板感重。
3. **农场窄屏不塌列 + 无鉴权归属**（`ux-audit.md` B2/B3）——手机 3 列误触；接口横向越权（本阶段免登录可接受，需如实标注）。

## 五、需要你选择 / 授权的事项
1. 探索首页方向：选 A（单色图解）/ B（记忆图谱）/ 混合（本轮已在正式页按「混合」改了一版，是否保留）。
2. Skill 补丁（主规则与风格库分离）是否落地——本批只写了建议，未覆盖原 SKILL.md。
3. **参考图内容可读性**：本环境无视觉，风格归属「待补」；要真正「参考图驱动」，需你补每张图的文字描述，或换有视觉的模型。
4. 提交材料仍缺：指导教师姓名、学校申报表模板。

## 六、本批新增文件清单
```
docs/review/
├── START-HERE.md
├── skill-audit.md
├── skill-patch-proposal.md
├── ux-audit.md
├── previews/
│   ├── preview-a.html
│   ├── preview-b.html
│   ├── preview-shared.css
│   └── README.md
└── flow-tests/
    ├── test_flows.py
    └── RESULTS.md
```
**diff 摘要**：本批仅新增上述审查文件，**未修改正式产品代码**（`main.py`/`database.py`/`static/index.html` 未在本批改动）。

---

## 自检（非独立审查）

> 未能启动独立子 Agent 做只读复审，本批以**自检**代替，特此标注。

- 是否过度声明：未声称「视觉已通过」「浏览器已通过」「模型联调已通过」，均已明确列在「未验证」。
- 是否遗漏：B3（鉴权）、真实模型联调、浏览器流程均作为「未验证/待确认」保留，未编造。
- 产物真实性：以上文件均已实际落盘（见清单），`test_flows.py` 已实际运行并输出 11 项 PASS。
- 边界遵守：未读 .env/密钥、未连正式库、未部署、未装全局依赖、未绕过权限。
