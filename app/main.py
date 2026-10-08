"""个人学习服务运营 Agent — FastAPI 入口。

启动：uvicorn main:app --reload --port 8300
演示闭环：添加学习者 → 拆解目标 → 录入每日一句话回传 → Agent 解析+调整建议 →
确认入库 → 周报。
"""
import json
import os
import time
from datetime import date, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agent_engine
import database
import planning
from scenarios_seed import SCENARIOS
from cards_seed import CARDS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Learner Agent", docs_url="/docs")


@app.on_event("startup")
def _seed_scenarios():
    for sc in SCENARIOS:
        database.seed_scenario(sc)
    for card in CARDS:
        database.seed_card(card)
    # 若无用户，自动建一个默认学习者，打开即可用（不导入假种子数据）
    if not database.list_users():
        database.add_user("我", "balance", "默认学习者")


# ---------- 页面 ----------

@app.get("/")
def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")),
          name="static")


# ---------- schema ----------

class UserIn(BaseModel):
    name: str
    category: str = "balance"
    notes: str = ""


class GoalIn(BaseModel):
    title: str
    weight: int = 3
    standard_duration_min: int = 25
    weekly_frequency: int = 7
    category: str = ""


class BreakdownIn(BaseModel):
    goals_brief: str


class GoalBulkIn(BaseModel):
    tasks: list[dict]


class EntryIn(BaseModel):
    entry_date: str  # YYYY-MM-DD
    raw_text: str


class EntryConfirmIn(BaseModel):
    entry_date: str
    checkins: dict
    focus_min: int = 0
    note: str = ""
    agent_output_id: int | None = None
    approved: bool = True


class IdeaIn(BaseModel):
    user_id: int | None = None
    idea_text: str


class DecideIn(BaseModel):
    approved: bool


class PaperImportIn(BaseModel):
    """纸质 50 天数据导入：days 里 goal_title 会自动映射/创建到目标。"""
    days: list[dict]  # [{"date": "2026-08-01", "checks": {"背单词": 1, ...}, "raw": "..."}]


# ---------- config / users ----------

@app.get("/api/config")
def get_config():
    return {"configured": agent_engine.is_configured(),
            "model": agent_engine.MODEL}


@app.get("/api/users")
def api_list_users():
    users = database.list_users()
    for u in users:
        u["stats"] = database.user_stats(u["id"])
    return users


@app.post("/api/users")
def api_add_user(inp: UserIn):
    uid = database.add_user(inp.name, inp.category, inp.notes)
    return {"id": uid}


@app.get("/api/users/{uid}")
def api_get_user(uid: int):
    user = database.get_user(uid)
    if not user:
        raise HTTPException(404, "user not found")
    user["goals"] = database.list_goals(uid)
    user["entries"] = database.list_entries(uid, days=14)
    user["stats"] = database.user_stats(uid)
    user["agent_outputs"] = database.list_agent_outputs(uid, limit=10)
    return user


# ---------- goals ----------

@app.post("/api/users/{uid}/goals")
def api_add_goal(uid: int, inp: GoalIn):
    gid = database.add_goal(uid, inp.title, inp.weight,
                            inp.standard_duration_min, inp.weekly_frequency,
                            inp.category)
    return {"id": gid}


@app.post("/api/users/{uid}/breakdown")
def api_breakdown(uid: int, inp: BreakdownIn):
    """Agent 拆解目标 → 返回任务清单（不自动入库，待运营者确认）。"""
    user = database.get_user(uid)
    if not user:
        raise HTTPException(404, "user not found")
    if not agent_engine.is_configured():
        return JSONResponse({"error": "DEEPSEEK_API_KEY 未配置"}, 503)
    result = agent_engine.task_breakdown(user, inp.goals_brief)
    return result


@app.post("/api/users/{uid}/goals/bulk")
def api_add_goals_bulk(uid: int, inp: GoalBulkIn):
    """确认 Agent 拆解结果后批量入库。"""
    ids = []
    for t in inp.tasks:
        gid = database.add_goal(
            uid, t.get("title", "未命名"),
            int(t.get("weight", 3)),
            int(t.get("standard_duration_min", 25)),
            int(t.get("weekly_frequency", 7)),
            t.get("category", ""))
        ids.append(gid)
    return {"ids": ids}


# ---------- daily entries ----------

@app.post("/api/users/{uid}/entries")
def api_submit_entry(uid: int, inp: EntryIn):
    """录入一句话回传 → Agent 解析 + 调整建议（返回但未入库）。"""
    user = database.get_user(uid)
    if not user:
        raise HTTPException(404, "user not found")
    if not agent_engine.is_configured():
        return JSONResponse({"error": "DEEPSEEK_API_KEY 未配置"}, 503)
    result = agent_engine.daily_adjustment(user, inp.raw_text)
    result["entry_date"] = inp.entry_date
    return result


@app.post("/api/users/{uid}/entries/confirm")
def api_confirm_entry(uid: int, inp: EntryConfirmIn):
    """运营者确认后入库：写 checkins、结算 W-Complete、登记 Agent 决定。"""
    goals = database.list_goals(uid)
    entry_id = database.upsert_daily_entry(
        uid, inp.entry_date, raw_text="", checkins=inp.checkins,
        focus_min=inp.focus_min, note=inp.note)
    # 结算 W-Complete
    conn = database.get_conn()
    entry = conn.execute("SELECT * FROM daily_entries WHERE id=?",
                         (entry_id,)).fetchone()
    w = database.compute_w_complete(dict(entry), goals)
    conn.execute("UPDATE daily_entries SET w_complete=? WHERE id=?",
                 (w, entry_id))
    conn.commit()
    if inp.agent_output_id is not None:
        database.decide_agent_output(inp.agent_output_id, inp.approved)
    return {"id": entry_id, "w_complete": w}


# ---------- reports / idea ----------

@app.post("/api/users/{uid}/report")
def api_weekly_report(uid: int):
    user = database.get_user(uid)
    if not user:
        raise HTTPException(404, "user not found")
    if not agent_engine.is_configured():
        return JSONResponse({"error": "DEEPSEEK_API_KEY 未配置"}, 503)
    md = agent_engine.weekly_report(user)
    return {"report": md}


@app.post("/api/idea")
def api_idea(inp: IdeaIn):
    user = database.get_user(inp.user_id) if inp.user_id else None
    if not agent_engine.is_configured():
        return JSONResponse({"error": "DEEPSEEK_API_KEY 未配置"}, 503)
    md = agent_engine.idea_deconstruction(user, inp.idea_text)
    return {"analysis": md}


@app.post("/api/agent_outputs/{oid}/decide")
def api_decide_output(oid: int, inp: DecideIn):
    database.decide_agent_output(oid, inp.approved)
    return {"ok": True}


# ---------- 纸质数据导入 ----------

@app.post("/api/users/{uid}/import-paper")
def api_import_paper(uid: int, inp: PaperImportIn):
    """纸质 50 天历史数据导入。checks 的 key 是目标名（自动映射，缺失则创建）。
    无记录的日期不造数据，只在 date 范围内把缺失日登记为 gap。"""
    created = imported = gaps = 0
    title2goal = {g["title"]: g for g in database.list_goals(uid, active_only=False)}
    for day in inp.days:
        d = day.get("date")
        if not d:
            continue
        checks = {}
        for title, c in (day.get("checks") or {}).items():
            if title not in title2goal:
                gid = database.add_goal(uid, title)
                title2goal[title] = {"id": gid, "title": title, "weight": 3}
                created += 1
            checks[str(title2goal[title]["id"])] = float(c)
        if checks:
            database.upsert_daily_entry(uid, d, raw_text=day.get("raw", ""),
                                        checkins=checks)
            imported += 1
        else:
            database.mark_gap_days(uid, [d])
            gaps += 1
    # 结算导入日的 W-Complete
    conn = database.get_conn()
    goals = database.list_goals(uid, active_only=False)
    for day in inp.days:
        d = day.get("date")
        row = conn.execute(
            "SELECT * FROM daily_entries WHERE user_id=? AND entry_date=?",
            (uid, d)).fetchone()
        if row and row["settlement_status"] == "settled":
            w = database.compute_w_complete(dict(row), goals)
            conn.execute("UPDATE daily_entries SET w_complete=? WHERE id=?",
                         (w, row["id"]))
    conn.commit()
    return {"goals_created": created, "days_imported": imported, "days_gap": gaps}


@app.get("/api/users/{uid}/history")
def api_history(uid: int, days: int = 60):
    """给演示视频用：历史 W-Complete 序列。"""
    entries = database.list_entries(uid, days=days)
    goals = database.list_goals(uid, active_only=False)
    return [{"date": e["entry_date"], "status": e["settlement_status"],
             "w": e["w_complete"]} for e in entries]


# ============================================================
#  情境剧场 · 个人实验室 · 探索 · 成长记忆
# ============================================================

class StartIn(BaseModel):
    user_id: int
    director: dict | None = None


class AdvanceIn(BaseModel):
    text: str


class CompareIn(BaseModel):
    user_id: int


class DirectorIn(BaseModel):
    director: dict


class ExperimentPlanIn(BaseModel):
    user_id: int
    compare_text: str


class ExperimentIn(BaseModel):
    user_id: int
    source_scene: str = ""
    hypothesis: str = ""
    action: str = ""
    record_what: str = ""
    review_date: str = ""


class ExperimentReviewIn(BaseModel):
    outcome: str


class ExploreIn(BaseModel):
    user_id: int
    feeling: str


class MemoryIn(BaseModel):
    user_id: int
    kind: str = "experience"
    content: str
    source_ref: str = ""


class MemoryEditIn(BaseModel):
    content: str


def _run_to_branches(run: dict, key_nodes: list) -> list[dict]:
    """从一次 run 的 timeline 提取每个关键节点的用户说法 + 角色反应 + 评估 + 情绪。"""
    tl = run.get("timeline", [])
    branches = []
    for node in key_nodes:
        user_text = None
        char_reply = None
        eval_meta = {}
        for i, t in enumerate(tl):
            if t.get("node_id") == node["node_id"] and t.get("speaker") == "user":
                user_text = t.get("text", "")
                eval_meta = t.get("eval", {})
                for j in range(i + 1, len(tl)):
                    if tl[j].get("speaker") != "user":
                        char_reply = tl[j].get("text", "")
                        break
                break
        if user_text is not None:
            branches.append({
                "label": f"分支{run['branch_label']}·{node['label']}",
                "node_label": node["label"],
                "user_text": user_text,
                "character_reply": char_reply or "",
                "character_mood": eval_meta.get("character_mood", ""),
                "eval": eval_meta,
            })
    return branches


# ---- 情境剧场 ----

@app.get("/api/scenarios")
def api_list_scenarios(user_id: int | None = None):
    scenes = database.list_scenarios()
    if user_id:
        for s in scenes:
            runs = database.list_runs(user_id, s["id"])
            s["run_count"] = len(runs)
            s["user_turns"] = sum(
                1 for r in runs for t in r["timeline"] if t.get("speaker") == "user")
    return scenes


@app.get("/api/scenarios/{sid}")
def api_get_scenario(sid: str):
    sc = database.get_scenario(sid)
    if not sc:
        raise HTTPException(404, "scenario not found")
    return sc


@app.post("/api/scenes/{sid}/start")
def api_scene_start(sid: str, inp: StartIn):
    sc = database.get_scenario(sid)
    if not sc:
        raise HTTPException(404, "scenario not found")
    first = sc["key_nodes"][0]["node_id"] if sc["key_nodes"] else ""
    director = inp.director or {}
    rid = database.create_run(inp.user_id, sc["id"], "A", None, first, director)
    return {"run_id": rid, "scenario": sc, "current_node_id": first,
            "director": director}


@app.post("/api/scenes/run/{rid}/advance")
def api_scene_advance(rid: int, inp: AdvanceIn):
    if not agent_engine.is_configured():
        return JSONResponse({"error": "DEEPSEEK_API_KEY 未配置，无法开始对话模拟"}, 503)
    run = database.get_run(rid)
    if not run:
        raise HTTPException(404, "run not found")
    sc = database.get_scenario(run["scenario_id"])
    nodes = sc["key_nodes"]
    cur_idx = next((i for i, n in enumerate(nodes)
                    if n["node_id"] == run["node_id"]), 0)
    node = nodes[cur_idx]
    result = agent_engine.scene_character(sc, run["timeline"], inp.text, node,
                                          run["director"])
    if result.get("red_flag"):
        return {"red_flag": True, "message": result["message"]}
    eval_meta = result.get("eval", {})
    # 情绪/好感变化挂在本轮 meta 里落库，重演与洞察都能取到
    eval_meta["character_mood"] = result.get("character_mood", "")
    eval_meta["relation_delta"] = result.get("relation_delta", 0)
    database.append_turn(rid, "user", inp.text, node["node_id"], eval_meta)
    database.append_turn(rid, sc["character_name"],
                         result["character_reply"], node["node_id"])
    next_id = nodes[cur_idx + 1]["node_id"] if cur_idx + 1 < len(nodes) else None
    done = next_id is None
    database.update_run(rid, node_id=next_id or "",
                        status="completed" if done else "active")
    if done:
        database.pet_reward(run["user_id"], 20, "study", "在情境剧场完成了一次练习")
    return {"character_reply": result["character_reply"], "eval": result.get("eval", {}),
            "character_mood": result.get("character_mood", ""),
            "relation_delta": result.get("relation_delta", 0),
            "next_node_id": next_id, "done": done}


@app.post("/api/scenes/run/{rid}/replay")
def api_scene_replay(rid: int):
    run = database.get_run(rid)
    if not run:
        raise HTTPException(404, "run not found")
    sc = database.get_scenario(run["scenario_id"])
    existing = database.list_runs(run["user_id"], run["scenario_id"])
    label = chr(ord("A") + len(existing))  # A, B, C…
    first = sc["key_nodes"][0]["node_id"] if sc["key_nodes"] else ""
    new_rid = database.create_run(run["user_id"], run["scenario_id"],
                                  label, rid, first, run["director"])
    return {"run_id": new_rid, "branch_label": label, "current_node_id": first,
            "director": run["director"]}


@app.post("/api/scenes/run/{rid}/director")
def api_scene_director(rid: int, inp: DirectorIn):
    run = database.get_run(rid)
    if not run:
        raise HTTPException(404, "run not found")
    database.update_run(rid, director=json.dumps(inp.director, ensure_ascii=False))
    return {"ok": True, "director": inp.director}


@app.post("/api/scenes/{sid}/compare")
def api_scene_compare(sid: str, inp: CompareIn):
    sc = database.get_scenario(sid)
    if not sc:
        raise HTTPException(404, "scenario not found")
    runs = database.list_runs(inp.user_id, sc["id"])
    branches = []
    for r in runs:
        branches.extend(_run_to_branches(r, sc["key_nodes"]))
    if len(branches) < 2:
        return {"error": "至少两个分支才能对比，先完成一次再重演一次"}
    director = runs[-1]["director"] if runs else {}
    md = agent_engine.scene_compare(sc, branches, director)
    return {"compare": md, "branches": branches}


@app.post("/api/scenes/{sid}/insight")
def api_scene_insight(sid: str, inp: CompareIn):
    """成长洞察：通读本情境所有分支，指出跨场次的行为模式（理解自己）。"""
    if not agent_engine.is_configured():
        return JSONResponse({"error": "DEEPSEEK_API_KEY 未配置"}, 503)
    sc = database.get_scenario(sid)
    if not sc:
        raise HTTPException(404, "scenario not found")
    runs = database.list_runs(inp.user_id, sc["id"])
    branches = []
    for r in runs:
        branches.extend(_run_to_branches(r, sc["key_nodes"]))
    if len(branches) < 2:
        return {"error": "至少练过两个关键节点才有模式可看，先完成一次练习（或重演一个分支）"}
    md = agent_engine.scene_insight(sc, branches)
    return {"insight": md, "branches": len(branches)}


@app.post("/api/scenes/{sid}/experiment-plan")
def api_experiment_plan(sid: str, inp: ExperimentPlanIn):
    sc = database.get_scenario(sid)
    if not sc:
        raise HTTPException(404, "scenario not found")
    return agent_engine.experiment_plan(sc, inp.compare_text)


class CustomSceneIn(BaseModel):
    user_id: int
    title: str
    background: str
    character: str = ""
    goal: str
    constraints: str = ""


@app.post("/api/scenes/custom")
def api_custom_scene(inp: CustomSceneIn):
    """自创场景：AI 把一句话场景设计成可练的对话，落库后可直接开玩。"""
    if not agent_engine.is_configured():
        return JSONResponse({"error": "DEEPSEEK_API_KEY 未配置"}, 503)
    gen = agent_engine.scene_generate(inp.title, inp.background, inp.character,
                                      inp.goal, inp.constraints)
    constraints = [c.strip() for c in inp.constraints.split("；") if c.strip()]
    constraints = constraints or [c.strip() for c in inp.constraints.split(";") if c.strip()]
    sc = {
        "slug": f"custom-{int(time.time())}",
        "title": inp.title,
        "theme": "自定义",
        "background": inp.background,
        "user_role": "你",
        "character_name": gen["character_name"],
        "avatar": "🧑",
        "character_persona": gen["character_persona"],
        "character_goal": gen["character_goal"],
        "goal": inp.goal,
        "constraints": constraints,
        "key_nodes": gen["key_nodes"],
        "success_criteria": inp.goal,
    }
    database.seed_scenario(sc)
    return database.get_scenario(sc["slug"])


# ---- 个人实验室 ----

@app.post("/api/experiments")
def api_create_experiment(inp: ExperimentIn):
    eid = database.create_experiment(inp.user_id, inp.source_scene,
                                     inp.hypothesis, inp.action,
                                     inp.record_what, inp.review_date)
    database.pet_reward(inp.user_id, 5, "lab", "开了一个现实小实验")
    return {"id": eid}


@app.get("/api/experiments")
def api_list_experiments(user_id: int):
    return database.list_experiments(user_id)


@app.post("/api/experiments/{eid}/review")
def api_review_experiment(eid: int, inp: ExperimentReviewIn):
    conn = database.get_conn()
    row = conn.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
    if not row:
        raise HTTPException(404, "experiment not found")
    exp = dict(row)
    database.update_experiment(eid, outcome=inp.outcome, status="done")
    exp["outcome"] = inp.outcome
    md = agent_engine.experiment_review(exp)
    database.pet_reward(exp["user_id"], 15, "lab", "完成了一次现实小实验复盘")
    return {"review": md}


# ---- 探索空间 ----

@app.post("/api/explore")
def api_explore(inp: ExploreIn):
    user = database.get_user(inp.user_id)
    if not user:
        raise HTTPException(404, "user not found")
    if not agent_engine.is_configured():
        return JSONResponse({"error": "DEEPSEEK_API_KEY 未配置"}, 503)
    result = agent_engine.explore(user, inp.feeling)
    database.add_exploration(inp.user_id, inp.feeling,
                             result.get("directions", []))
    database.pet_reward(inp.user_id, 5, "explore", "探索了一个新方向")
    return result


# ---- 成长记忆 ----

@app.get("/api/memory")
def api_list_memory(user_id: int):
    return database.list_memory(user_id)


@app.post("/api/memory")
def api_add_memory(inp: MemoryIn):
    mid = database.add_memory(inp.user_id, inp.kind, inp.content, inp.source_ref)
    database.pet_reward(inp.user_id, 3, "note", "记下一条成长记忆")
    return {"id": mid}


@app.post("/api/memory/{mid}/edit")
def api_edit_memory(mid: int, inp: MemoryEditIn):
    database.edit_memory(mid, inp.content)
    return {"ok": True}


@app.post("/api/memory/{mid}/delete")
def api_delete_memory(mid: int):
    database.delete_memory(mid)
    return {"ok": True}


# ---- 成长宠物 ----

class PetUpdateIn(BaseModel):
    name: str = ""
    species: str = ""


@app.get("/api/users/{uid}/pet")
def api_get_pet(uid: int):
    user = database.get_user(uid)
    if not user:
        raise HTTPException(404, "user not found")
    return database.get_pet_state(uid)


@app.post("/api/users/{uid}/pet/feed")
def api_pet_feed(uid: int):
    return database.pet_feed(uid)


@app.post("/api/users/{uid}/pet/sleep")
def api_pet_sleep(uid: int):
    return database.pet_sleep(uid)


@app.post("/api/users/{uid}/pet/play")
def api_pet_play(uid: int):
    return database.pet_play(uid)


@app.post("/api/users/{uid}/pet/update")
def api_pet_update(uid: int, inp: PetUpdateIn):
    return database.update_pet(uid, inp.name or None, inp.species or None)


# ---- 成长卡牌 ----

@app.get("/api/cards")
def api_list_cards(user_id: int):
    return {"cards": database.list_cards(user_id),
            "draw_available": database.card_draw_available(user_id)}


@app.post("/api/cards/draw")
def api_draw_card(inp: StartIn):
    return database.draw_card(inp.user_id)


# ---- 自律（每日 todo / 打卡） ----

class CheckIn(BaseModel):
    goal_id: int
    checked: bool


class FocusIn(BaseModel):
    minutes: int


class NoteIn(BaseModel):
    note: str


@app.get("/api/users/{uid}/discipline")
def api_discipline(uid: int):
    user = database.get_user(uid)
    if not user:
        raise HTTPException(404, "user not found")
    return database.discipline_state(uid)


@app.post("/api/users/{uid}/discipline/check")
def api_discipline_check(uid: int, inp: CheckIn):
    return database.discipline_check(uid, inp.goal_id, inp.checked)


@app.post("/api/users/{uid}/discipline/focus")
def api_discipline_focus(uid: int, inp: FocusIn):
    return database.discipline_focus(uid, inp.minutes)


@app.post("/api/users/{uid}/discipline/note")
def api_discipline_note(uid: int, inp: NoteIn):
    return database.discipline_note(uid, inp.note)


# ---- 成长事件（跨空间交接） ----

class EventIn(BaseModel):
    user_id: int
    kind: str = ""
    title: str = ""
    summary: str = ""
    source_ref: str = ""
    status: str = "draft"


class EventUpdateIn(BaseModel):
    title: str = ""
    summary: str = ""
    status: str = ""


@app.get("/api/users/{uid}/events")
def api_list_events(uid: int):
    return database.list_events(uid)


@app.post("/api/events")
def api_create_event(inp: EventIn):
    eid = database.create_event(inp.user_id, inp.kind, inp.title,
                                inp.summary, inp.source_ref)
    if inp.status and inp.status != "draft":
        database.update_event(eid, status=inp.status)
    return {"id": eid}


@app.post("/api/events/{eid}/update")
def api_update_event(eid: int, inp: EventUpdateIn):
    fields = {}
    if inp.title:
        fields["title"] = inp.title
    if inp.summary:
        fields["summary"] = inp.summary
    if inp.status:
        fields["status"] = inp.status
    database.update_event(eid, **fields)
    return {"ok": True}


# ---- 经验卡 ----

class ExperienceCardIn(BaseModel):
    user_id: int
    conclusion: str
    situation: str = ""
    limitation: str = ""
    source_ref: str = ""


class ExperienceCardEditIn(BaseModel):
    conclusion: str = ""
    situation: str = ""
    limitation: str = ""


@app.get("/api/experience-cards")
def api_list_experience_cards(user_id: int):
    return database.list_experience_cards(user_id)


@app.post("/api/experience-cards")
def api_create_experience_card(inp: ExperienceCardIn):
    cid = database.create_experience_card(inp.user_id, inp.conclusion,
                                          inp.situation, inp.limitation,
                                          inp.source_ref)
    return {"id": cid}


@app.post("/api/experience-cards/{cid}/update")
def api_update_experience_card(cid: int, inp: ExperienceCardEditIn):
    fields = {}
    if inp.conclusion:
        fields["conclusion"] = inp.conclusion
    if inp.situation:
        fields["situation"] = inp.situation
    if inp.limitation:
        fields["limitation"] = inp.limitation
    database.update_experience_card(cid, **fields)
    return {"ok": True}


@app.post("/api/experience-cards/{cid}/delete")
def api_delete_experience_card(cid: int):
    database.delete_experience_card(cid)
    return {"ok": True}


# ---- 萌宠农场 ----

class FarmPlantIn(BaseModel):
    user_id: int


class FarmHarvestIn(BaseModel):
    user_id: int
    plot_index: int


class FarmStealIn(BaseModel):
    victim_user_id: int
    plot_index: int
    thief_user_id: int


@app.get("/api/farms")
def api_get_farm(user_id: int):
    return database.get_farm(user_id)


@app.get("/api/farms/community")
def api_farm_community():
    return database.farm_community()


@app.post("/api/farms/plant")
def api_farm_plant(inp: FarmPlantIn):
    return database.farm_plant(inp.user_id)


@app.post("/api/farms/harvest")
def api_farm_harvest(inp: FarmHarvestIn):
    return database.farm_harvest(inp.user_id, inp.plot_index)


@app.post("/api/farms/steal")
def api_farm_steal(inp: FarmStealIn):
    return database.farm_steal(inp.victim_user_id, inp.plot_index, inp.thief_user_id)


@app.post("/api/events/{eid}/delete")
def api_delete_event(eid: int):
    database.delete_event(eid)
    return {"ok": True}


@app.post("/api/scenes/{sid}/delete")
def api_delete_scenario(sid: str):
    if not database.delete_scenario(sid):
        return JSONResponse({"error": "只能删除自创场景"}, 400)
    return {"ok": True}


# ============================================================
#  规划方向：学业与身心平衡（文字驱动 · 闭环）
# ============================================================

class ParseIn(BaseModel):
    text: str


class ScheduleIn(BaseModel):
    title: str
    date: str
    start_time: str = ""
    end_time: str = ""
    duration_min: int = 0


class MetricIn(BaseModel):
    date: str
    dimension: str
    value: float | None = None
    source: str = "self_report"


class RestIn(BaseModel):
    start_time: str
    end_time: str
    label: str = ""
    days: str = "0,1,2,3,4,5,6"


@app.post("/api/users/{uid}/parse-intent")
def api_parse_intent(uid: int, inp: ParseIn):
    user = database.get_user(uid)
    if not user:
        raise HTTPException(404, "user not found")
    if not agent_engine.is_configured():
        return JSONResponse({"error": "DEEPSEEK_API_KEY 未配置"}, 503)
    return agent_engine.parse_intent(user, inp.text)


@app.post("/api/ops/{oid}/confirm")
def api_confirm_op(oid: int):
    op = database.get_pending_op(oid)
    if not op:
        raise HTTPException(404, "op not found")
    if op["status"] != "pending":
        return {"error": "该操作已处理（状态：" + op["status"] + "）"}
    result = planning.apply_op(op["user_id"], op["payload"])
    if result.get("unsupported") or result.get("not_found"):
        return {"error": result.get("not_found") or ("暂不支持：" + result["unsupported"])}
    database.set_pending_op(oid, "applied", before_snapshot=result["snapshot"])
    p = op["payload"]
    conflicts = []
    capacity = None
    if p.get("intent") in ("add", "modify"):
        conflicts = planning.check_conflicts(op["user_id"], p.get("date", ""),
                                             p.get("start_time", ""), p.get("end_time", ""))
        capacity = planning.check_capacity(op["user_id"], p.get("date", ""), 0)
    return {"ok": True, "applied": result["applied"],
            "conflicts": conflicts, "capacity": capacity}


@app.post("/api/ops/{oid}/cancel")
def api_cancel_op(oid: int):
    op = database.get_pending_op(oid)
    if not op:
        raise HTTPException(404, "op not found")
    if op["status"] != "pending":
        return {"error": "该操作已处理"}
    database.set_pending_op(oid, "cancelled")
    return {"ok": True}


@app.post("/api/ops/{oid}/revert")
def api_revert_op(oid: int):
    op = database.get_pending_op(oid)
    if not op:
        raise HTTPException(404, "op not found")
    if op["status"] != "applied":
        return {"error": "该操作未应用，无法撤销"}
    if not op["before_snapshot"]:
        return {"error": "无可撤销快照"}
    planning.revert_op(op["user_id"], op["before_snapshot"])
    database.set_pending_op(oid, "reverted")
    return {"ok": True}


@app.post("/api/ops/{oid}/adjust")
def api_adjust_op(oid: int):
    op = database.get_pending_op(oid)
    if not op:
        raise HTTPException(404, "op not found")
    if not agent_engine.is_configured():
        return JSONResponse({"error": "DEEPSEEK_API_KEY 未配置"}, 503)
    return agent_engine.adjust_conflict(op["user_id"], op["payload"])


@app.get("/api/users/{uid}/schedule")
def api_get_schedule(uid: int, date: str | None = None):
    return database.list_schedule(uid, date)


@app.post("/api/users/{uid}/schedule")
def api_add_schedule(uid: int, inp: ScheduleIn):
    sid = database.add_schedule_item(uid, inp.title, inp.date, inp.start_time,
                                     inp.end_time, inp.duration_min, None, "user")
    return {"id": sid}


@app.delete("/api/schedule/{sid}")
def api_delete_schedule(sid: int):
    database.delete_schedule_item(sid)
    return {"ok": True}


@app.post("/api/users/{uid}/conflict")
def api_check_conflict(uid: int, inp: ScheduleIn):
    conflicts = planning.check_conflicts(uid, inp.date, inp.start_time, inp.end_time)
    capacity = planning.check_capacity(uid, inp.date, inp.duration_min)
    return {"conflicts": conflicts, "capacity": capacity}


@app.get("/api/users/{uid}/metrics")
def api_get_metrics(uid: int, date: str | None = None, dimension: str | None = None):
    return database.list_metrics(uid, date, dimension)


@app.post("/api/users/{uid}/metrics")
def api_add_metric(uid: int, inp: MetricIn):
    mid = database.add_metric(uid, inp.date, inp.dimension, inp.value, inp.source, "actual")
    return {"id": mid}


@app.get("/api/users/{uid}/rest-windows")
def api_get_rest(uid: int):
    return database.list_rest_windows(uid)


@app.post("/api/users/{uid}/rest-windows")
def api_add_rest(uid: int, inp: RestIn):
    rid = database.add_rest_window(uid, inp.start_time, inp.end_time, inp.label, inp.days)
    return {"id": rid}


class AutoPlanIn(BaseModel):
    content: str


class AutoPlanApplyIn(BaseModel):
    schedule: list
    todos: list
    tags: str = ""


@app.post("/api/users/{uid}/auto-plan")
def api_auto_plan(uid: int, inp: AutoPlanIn):
    user = database.get_user(uid)
    if not user:
        raise HTTPException(404, "user not found")
    if not agent_engine.is_configured():
        return JSONResponse({"error": "DEEPSEEK_API_KEY 未配置"}, 503)
    return agent_engine.auto_plan(user, inp.content)


@app.post("/api/users/{uid}/auto-plan/apply")
def api_auto_plan_apply(uid: int, inp: AutoPlanApplyIn):
    result = planning.apply_auto_plan(uid, inp.schedule, inp.todos, inp.tags)
    return {"ok": True, **result}


class TagIn(BaseModel):
    tags: str


class ReviewIn(BaseModel):
    days: int = 7


@app.get("/api/users/{uid}/timeline")
def api_timeline(uid: int, days: int = 14):
    """时间线：过去 N 天的计划 vs 实际。"""
    out = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        sched = database.list_schedule(uid, d)
        row = database.get_conn().execute(
            "SELECT focus_min FROM daily_entries WHERE user_id=? AND entry_date=?",
            (uid, d)).fetchone()
        focus = (row["focus_min"] or 0) if row else 0
        done = sum(1 for s in sched if s["status"] == "done")
        out.append({"date": d, "planned": len(sched), "done": done,
                    "focus_min": focus, "items": sched})
    return out


@app.post("/api/goals/{gid}/tags")
def api_set_goal_tags(gid: int, inp: TagIn):
    database.set_goal_tags(gid, inp.tags)
    return {"ok": True}


@app.post("/api/schedule/{sid}/tags")
def api_set_schedule_tags(sid: int, inp: TagIn):
    database.set_schedule_tags(sid, inp.tags)
    return {"ok": True}


@app.post("/api/users/{uid}/review")
def api_review(uid: int, inp: ReviewIn):
    user = database.get_user(uid)
    if not user:
        raise HTTPException(404, "user not found")
    if not agent_engine.is_configured():
        return JSONResponse({"error": "DEEPSEEK_API_KEY 未配置"}, 503)
    return {"review": agent_engine.review(user, inp.days)}
