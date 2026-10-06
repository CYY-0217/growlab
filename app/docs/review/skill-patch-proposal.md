# 任务 1｜Skill 补丁建议（本轮不落地）

> 目标：把「主规则（常驻）」与「风格库（按需读取）」分离，降低触发判断负担，风格细节用到再读。

## 拆分方案

```
.claude/skills/growlab-art-direction/
├── SKILL.md          # 主规则（保留，精简）
└── references/
    ├── STYLES.md     # 风格库 A–G（从 SKILL.md 迁出，按需读）
    ├── INDEX.md      # 参考图索引（保留）
    └── images/       # 参考图（保留）
```

## 建议改动

### 1. SKILL.md 保留（主规则）
- frontmatter（name/description）不变
- 目标、输入与边界、全局设计原则、执行流程（6 步）、可访问性与性能、素材与版权、交付格式、验收清单

### 2. 迁出到 references/STYLES.md（按需读）
- 「风格库」整节（A Specimen Editorial ～ G Memory Atlas）
- 理由：风格库是「参考图转译」时才需要的词典；触发判断和流程无需整份载入。

### 3. SKILL.md 加一行指引
> 需要参考图驱动的具体风格时，先读 `references/STYLES.md` 与 `references/INDEX.md`。

## 收益
- 触发判断更快、常驻 token 更省。
- 风格库更新不影响主 Skill 触发。

## 风险
- 拆分会多一次「按需读文件」的动作；若 Skill 无法自动读 references/，需在 SKILL.md 里显式写清路径（本方案已写）。

## 落地条件
- 需用户确认后，再改 `.claude/skills/growlab-art-direction/` 下的文件（本批不覆盖原 Skill）。
