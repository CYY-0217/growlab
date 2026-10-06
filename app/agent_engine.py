"""Agent 执行核心：调用 DeepSeek（OpenAI 兼容接口），返回解析结果。

关键设计：
- 每次调用的输入/输出都经 database.save_agent_output 落库，全程可追溯
- JSON 输出解析失败时降级为原始文本，不让一次模型失误卡死流程
- 未配置 API Key 时返回明确的"未配置"结果（不编造 Agent 已执行）
"""
import json
import os
from datetime import date, timedelta, datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import database
import prompts

API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

_client = None


def is_configured() -> bool:
    return bool(API_KEY)


def get_client():
    global _client
    if _client is None:
        if not API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置（复制 .env.example 为 .env 并填入密钥）")
        from openai import OpenAI
        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client


def _chat(system: str, user: str) -> str:
    resp = get_client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
        max_tokens=2000,
    )
    return resp.choices[0].message.content or ""


def _parse_json(text: str) -> dict | None:
    """宽容解析：剥离 markdown 代码块围栏后 json.loads。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        # 尝试截取第一个 { 到最后一个 }
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                return None
    return None


def _profile_text(user: dict) -> str:
    cat_names = {"self": "运营者本人（有 50 天自律打卡历史）",
                 "balance": "学业与身体健康平衡型学习者",
                 "swim": "每日游泳训练、需要时间调度的学习者",
                 "think": "习惯养成与思维提升型学习者"}
    return f"姓名：{user['name']}（{cat_names.get(user['category'], user['category'])}）\n备注：{user['notes'] or '无'}"


def _goals_text(goals: list[dict]) -> str:
    if not goals:
        return "（暂无目标）"
    lines = []
    for g in goals:
        lines.append(
            f"- id={g['id']} [{g['title']}] W={g['weight']} "
            f"标准耗时={g['standard_duration_min']}min 周频率={g['weekly_frequency']}次/周 "
            f"类别={g['category'] or '未分类'}")
    return "\n".join(lines)


# ---------- 对外 4 个能力 ----------

def task_breakdown(user: dict, goals_brief: str) -> dict:
    """目标拆解：返回 {tasks, schedule_advice, risks} 或降级结果。"""
    user_prompt = prompts.BREAKDOWN_USER.format(
        profile=_profile_text(user), goals_text=goals_brief)
    raw = _chat(prompts.BREAKDOWN_SYSTEM, user_prompt)
    parsed = _parse_json(raw)
    database.save_agent_output(user["id"], "breakdown", goals_brief, raw)
    if parsed and "tasks" in parsed:
        return parsed
    return {"tasks": [], "schedule_advice": "", "risks": [],
            "parse_error": True, "raw": raw}


def daily_adjustment(user: dict, raw_text: str) -> dict:
    """每日回传解析 + 调整建议。"""
    goals = database.list_goals(user["id"])
    entries = database.list_entries(user["id"], days=7)
    recent = [
        {"date": e["entry_date"], "status": e["settlement_status"],
         "checkins": json.loads(e["checkins"] or "{}"),
         "raw": e["raw_text"]}
        for e in entries
    ]
    user_prompt = prompts.ADJUST_USER.format(
        profile=_profile_text(user), goals_text=_goals_text(goals),
        recent_json=json.dumps(recent, ensure_ascii=False), raw_text=raw_text)
    raw = _chat(prompts.ADJUST_SYSTEM, user_prompt)
    parsed = _parse_json(raw)
    output_id = database.save_agent_output(user["id"], "adjustment", raw_text, raw)
    if parsed and "checkins" in parsed:
        parsed["agent_output_id"] = output_id
        return parsed
    return {"checkins": {}, "parsed_summary": raw, "deviation": "",
            "adjustment_needed": False, "adjustment": {},
            "intervention": "", "parse_error": True, "raw": raw,
            "agent_output_id": output_id}


def weekly_report(user: dict) -> str:
    """周报：markdown 文本。"""
    goals = database.list_goals(user["id"])
    entries = database.list_entries(user["id"], days=7)
    recent = [
        {"date": e["entry_date"], "status": e["settlement_status"],
         "checkins": json.loads(e["checkins"] or "{}"),
         "raw": e["raw_text"], "focus_min": e["focus_min"]}
        for e in entries
    ]
    series = {e["entry_date"]: database.compute_w_complete(e, goals) for e in entries}
    user_prompt = prompts.REPORT_USER.format(
        profile=_profile_text(user), goals_text=_goals_text(goals),
        recent_json=json.dumps(recent, ensure_ascii=False),
        w_complete_series=json.dumps(series, ensure_ascii=False),
        name=user["name"])
    raw = _chat(prompts.REPORT_SYSTEM, user_prompt)
    database.save_agent_output(user["id"], "report",
                               f"近7日 {len(entries)} 条记录", raw)
    return raw


def idea_deconstruction(user: dict | None, idea_text: str) -> str:
    """想法拆解：markdown 文本。"""
    profile = _profile_text(user) if user else "（匿名用户）"
    user_prompt = prompts.IDEA_USER.format(profile=profile, idea_text=idea_text)
    raw = _chat(prompts.IDEA_SYSTEM, user_prompt)
    database.save_agent_output(user["id"] if user else None, "idea",
                               idea_text, raw)
    return raw


# ---------- 安全护栏 ----------

_SELF_HARM = ["自杀", "自残", "想死", "不想活", "结束生命", "割腕", "跳楼",
              "活不下去", "伤害自己", "kill myself", "suicide", "self harm"]
_SEVERE_PHYSICAL = ["胸口剧痛", "剧烈胸痛", "呼吸困难", "晕倒", "晕过去",
                    "喘不上气", "意识模糊"]


def check_red_flags(text: str) -> str | None:
    """检测红旗词，命中返回转介话术，否则 None。只做转介，不做判断病情。"""
    t = (text or "").lower()
    if any(k in t for k in _SELF_HARM):
        return ("我注意到你可能正处于很痛苦的时刻。我不能替你判断，但强烈建议你现在"
                "联系身边可信任的人，或拨打心理援助热线寻求专业帮助；如情况紧急请拨打 120/110。"
                "这个情境练习可以先放一放，你更重要。")
    if any(k in t for k in _SEVERE_PHYSICAL):
        return ("听起来像是需要尽快就医的身体信号。建议你现在就联系校医院或就近的医疗机构，"
                "必要时拨打 120。这个练习随时可以暂停。")
    return None


# ---------- 情境剧场 ----------

def _timeline_text(timeline: list, character_name: str) -> str:
    if not timeline:
        return "（还没有对话）"
    lines = []
    for t in timeline:
        who = "你" if t.get("speaker") == "user" else t.get("speaker", character_name)
        lines.append(f"{who}：{t.get('text', '')}")
    return "\n".join(lines)


def scene_character(scenario: dict, timeline: list, user_text: str,
                    node: dict, director: dict | None = None) -> dict:
    """角色回应 + 隐藏评估。用户文本命中红旗词时返回转介，不调用模型。"""
    flag = check_red_flags(user_text)
    if flag:
        return {"red_flag": True, "message": flag, "eval": {}}
    director = director or {}
    constraints = scenario.get("constraints", []) or []
    constraints_text = "\n".join(f"- {c}" for c in constraints) or "（无）"
    focus = director.get("focus", "清楚表达")
    intensity = director.get("intensity", "普通")
    user_prompt = prompts.SCENE_CHARACTER_USER.format(
        title=scenario["title"], background=scenario["background"],
        character_name=scenario["character_name"],
        character_persona=scenario["character_persona"],
        character_goal=scenario["character_goal"],
        user_role=scenario["user_role"], goal=scenario["goal"],
        constraints_text=constraints_text,
        focus=focus, intensity=intensity,
        node_prompt=node.get("prompt", ""),
        timeline_text=_timeline_text(timeline, scenario["character_name"]),
        user_text=user_text)
    raw = _chat(prompts.SCENE_CHARACTER_SYSTEM, user_prompt)
    parsed = _parse_json(raw)
    database.save_agent_output(None, "scene_character", user_text, raw)
    if parsed and "character_reply" in parsed:
        return parsed
    return {"character_reply": raw, "eval": {}, "parse_error": True, "raw": raw}


def scene_compare(scenario: dict, branches: list[dict],
                  director: dict | None = None) -> str:
    """分支对比复盘：branches = [{label, user_text, character_reply, eval}]。"""
    lines = []
    for b in branches:
        ev = b.get("eval", {})
        lines.append(
            f"- 分支 {b.get('label', '')}：用户说「{b.get('user_text', '')}」"
            f"→ 角色回应「{b.get('character_reply', '')}」"
            f"→ 评估：达成目标={ev.get('达成目标')} 关系友好={ev.get('关系友好')} "
            f"真诚表达={ev.get('真诚表达')}（{ev.get('comment', '')}）")
    focus = (director or {}).get("focus", "清楚表达")
    user_prompt = prompts.SCENE_COMPARE_USER.format(
        title=scenario["title"], goal=scenario["goal"],
        success_criteria=scenario.get("success_criteria", ""),
        focus=focus,
        branches_text="\n".join(lines))
    raw = _chat(prompts.SCENE_COMPARE_SYSTEM, user_prompt)
    database.save_agent_output(None, "scene_compare",
                               scenario["title"], raw)
    return raw


def scene_generate(title: str, background: str, character: str,
                   goal: str, constraints: str) -> dict:
    """自创场景：把用户一句话场景设计成可练的对话（含两个关键节点）。"""
    user_prompt = prompts.SCENE_GENERATE_USER.format(
        title=title, background=background, character=character or "（你来设计）",
        goal=goal, constraints=constraints or "（无）")
    raw = _chat(prompts.SCENE_GENERATE_SYSTEM, user_prompt)
    parsed = _parse_json(raw)
    database.save_agent_output(None, "scene_generate",
                               title, raw)
    if parsed and parsed.get("key_nodes"):
        parsed.setdefault("character_name", character or "对方")
        parsed.setdefault("character_persona", "")
        parsed.setdefault("character_goal", "")
        return parsed
    # 降级：给一个基本可玩的结构
    return {
        "character_name": character or "对方",
        "character_persona": "",
        "character_goal": "",
        "key_nodes": [
            {"node_id": "n1", "label": "开场",
             "prompt": "（对方开口，说出这个场景的第一句话）"},
            {"node_id": "n2", "label": "关键反应",
             "prompt": "（对方对你刚才的话做出反应）"},
        ],
        "parse_error": True,
    }


# ---------- 个人实验室 ----------

def experiment_plan(scenario: dict, compare_text: str) -> dict:
    user_prompt = prompts.EXPERIMENT_PLAN_USER.format(
        scene_title=scenario["title"], goal=scenario["goal"],
        compare_text=compare_text)
    raw = _chat(prompts.EXPERIMENT_PLAN_SYSTEM, user_prompt)
    parsed = _parse_json(raw)
    database.save_agent_output(None, "experiment_plan",
                               scenario["title"], raw)
    if parsed and "hypothesis" in parsed:
        return parsed
    return {"hypothesis": "", "action": "", "record_what": "",
            "review_date": "", "parse_error": True, "raw": raw}


def experiment_review(exp: dict) -> str:
    user_prompt = prompts.EXPERIMENT_REVIEW_USER.format(
        hypothesis=exp.get("hypothesis", ""), action=exp.get("action", ""),
        record_what=exp.get("record_what", ""), outcome=exp.get("outcome", ""))
    raw = _chat(prompts.EXPERIMENT_REVIEW_SYSTEM, user_prompt)
    database.save_agent_output(None, "experiment_review",
                               exp.get("hypothesis", ""), raw)
    return raw


# ---------- 探索空间 ----------

def explore(user: dict, feeling: str) -> dict:
    user_prompt = prompts.EXPLORE_USER.format(feeling=feeling)
    raw = _chat(prompts.EXPLORE_SYSTEM, user_prompt)
    parsed = _parse_json(raw)
    database.save_agent_output(user["id"], "explore", feeling, raw)
    if parsed and "directions" in parsed:
        return parsed
    return {"directions": [], "first_experiment": "", "note": "",
            "parse_error": True, "raw": raw}


# ---------- 规划方向：意图解析 ----------

_CN_WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_INTENT_KINDS = {"add", "modify", "cancel", "complete", "status"}
_DIMENSIONS = {"sleep", "energy", "focus", "stress"}


def _date_ref_text() -> str:
    """给模型一个「今天 + 未来 14 天」的日期参照表，让相对日期能落成绝对日期。"""
    today = date.today()
    lines = [f"今天是 {today.isoformat()}（{_CN_WEEK[today.weekday()]}）"]
    for i in range(1, 15):
        d = today + timedelta(days=i)
        lines.append(f"{i}天后 = {d.isoformat()}（{_CN_WEEK[d.weekday()]}）")
    return "\n".join(lines)


def _normalize_intent_op(op: dict) -> dict:
    """归一化模型输出的操作：意图白名单、日期兜底、metrics 维度过滤。"""
    op = op or {}
    intent = op.get("intent", "add")
    if intent not in _INTENT_KINDS:
        intent = "add"
    op["intent"] = intent
    op["goal_title"] = (op.get("goal_title") or "").strip()
    # 日期：非法/空 → 今天（complete 允许补历史，但仍以模型给的为准；这里只兜底格式）
    d = (op.get("date") or "").strip()
    try:
        datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        d = date.today().isoformat()
    op["date"] = d
    # metrics 维度白名单过滤；value 允许 null（未知），保留 0（明确为零）
    ms = []
    for m in (op.get("metrics") or []):
        if not isinstance(m, dict):
            continue
        dim = m.get("dimension")
        if dim not in _DIMENSIONS:
            continue
        ms.append({"dimension": dim, "value": m.get("value"),
                   "source": m.get("source", "self_report")})
    op["metrics"] = ms
    return op


def parse_intent(user: dict, text: str) -> dict:
    """文字 → 一组待确认操作（pending_ops）。只预览，不写业务数据。"""
    goals = database.list_goals(user["id"])
    sched = database.list_schedule(user["id"], date.today().isoformat())
    schedule_text = "\n".join(
        f"- [{s['title']}] {s['start_time'] or '?'}-{s['end_time'] or '?'}"
        for s in sched) or "（今天暂无日程）"
    user_prompt = prompts.INTENT_USER.format(
        date_ref=_date_ref_text(), goals_text=_goals_text(goals),
        schedule_text=schedule_text, text=text)
    raw = _chat(prompts.INTENT_SYSTEM, user_prompt)
    parsed = _parse_json(raw)
    output_id = database.save_agent_output(user["id"], "intent", text, raw)
    ops = []
    for op in (parsed or {}).get("ops", []):
        op = _normalize_intent_op(op)
        pid = database.create_pending_op(user["id"], op.get("intent", "add"),
                                        op, agent_output_id=output_id)
        op["pending_op_id"] = pid
        ops.append(op)
    return {"ops": ops,
            "ambiguous": (parsed or {}).get("ambiguous", ""),
            "parse_error": parsed is None,
            "raw": raw if parsed is None else ""}


def adjust_conflict(user_id: int, op: dict) -> dict:
    """日程有冲突时，让模型给候选替代时段。只建议，不写库。"""
    user = database.get_user(user_id)
    if not user:
        return {"error": "user not found"}
    date = op.get("date", "")
    sched = database.list_schedule(user_id, date)
    schedule_text = "\n".join(
        f"- [{s['title']}] {s['start_time'] or '?'}-{s['end_time'] or '?'}"
        for s in sched if s["status"] != "cancelled") or "（无）"
    rest = database.list_rest_windows(user_id)
    rest_text = "\n".join(
        f"- {r['label'] or '休息'} {r['start_time']}-{r['end_time']}" for r in rest) or "（无）"
    op_text = (f"{op.get('goal_title', '')} {date} "
               f"{op.get('start_time', '')}-{op.get('end_time', '')}")
    user_prompt = prompts.ADJUST_USER.format(
        op_text=op_text, schedule_text=schedule_text, rest_text=rest_text)
    raw = _chat(prompts.ADJUST_SYSTEM, user_prompt)
    parsed = _parse_json(raw)
    database.save_agent_output(user_id, "adjust", op_text, raw)
    if parsed and "candidates" in parsed:
        return parsed
    return {"candidates": [], "note": "", "parse_error": True, "raw": raw}
