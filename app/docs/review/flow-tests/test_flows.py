"""任务 4｜跨模块流程 · 数据层验证（隔离临时库，无模型调用）

用法：从项目根运行
    ./.venv/bin/python docs/review/flow-tests/test_flows.py

说明：
- 用临时数据库，不改正式 learner_agent.db、不部署、不连真实模型。
- 涉及模型的环节（scene_character/scene_compare/explore 生成内容）本批不调用，
  只验证它们依赖的数据结构（scene_runs/events/experiments/cards 等）与交接状态机。
- 每条打印 PASS/FAIL，最后汇总。
"""
import os
import sys
import json
import tempfile

# 把项目根加入 sys.path，便于 import 同目录模块
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, ROOT)

import database  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


def main():
    # 1) 隔离：切到临时库，重置连接
    fd, tmp = tempfile.mkstemp(suffix=".db", prefix="growlab_test_")
    os.close(fd)
    database.DB_PATH = tmp
    database._conn = None
    print(f"临时库：{tmp}\n")

    # ---- 成长事件：draft → confirm ----
    uid = database.add_user("测试学习者", "balance", "测试")
    eid = database.create_event(uid, "explore", "测试事件", "测试摘要", "explore")
    ev = database.get_event(eid)
    check("创建事件为 draft", ev and ev["status"] == "draft", f"status={ev and ev['status']}")
    database.update_event(eid, summary="改后的摘要", status="confirmed")
    ev = database.get_event(eid)
    check("更新+确认后为 confirmed 且摘要已改",
          ev and ev["status"] == "confirmed" and ev["summary"] == "改后的摘要")

    # ---- 交接「取消/暂停」：draft 可列出、可删除 ----
    drafts = database.list_events(uid, include_confirmed=False)
    check("draft 列表不含已确认事件", all(e["status"] == "draft" for e in drafts))
    eid2 = database.create_event(uid, "experience", "草稿2", "草稿摘要")
    database.delete_event(eid2)
    check("删除草稿后不再出现", all(e["id"] != eid2 for e in database.list_events(uid)))

    # ---- 导演模式：run 带 director ----
    database.seed_scenario({
        "slug": "test-scene", "title": "测试场景", "theme": "测试",
        "background": "", "user_role": "你", "character_name": "测试角色",
        "character_persona": "", "character_goal": "", "goal": "",
        "constraints": [], "key_nodes": [{"node_id": "n1", "label": "开场", "prompt": "开场"}],
        "success_criteria": "", "avatar": "🧑",
    })
    sc = database.get_scenario("test-scene")
    rid = database.create_run(uid, sc["id"], "A", None, "n1",
                              {"focus": "守住边界", "intensity": "有压力", "feedback": "结束后再看"})
    run = database.get_run(rid)
    check("run 带 director", run["director"].get("focus") == "守住边界", str(run["director"]))

    # ---- 场景时间线 + 分支提取 ----
    database.append_turn(rid, "user", "我说第一句", "n1", {"达成目标": True})
    database.append_turn(rid, "测试角色", "角色回应", "n1")
    import main as main_mod
    branches = main_mod._run_to_branches(database.get_run(rid), sc["key_nodes"])
    check("分支提取到用户说法+角色回应", len(branches) == 1 and branches[0]["user_text"] == "我说第一句")

    # ---- 实验室：experiment 创建/复盘 ----
    exp = database.create_experiment(uid, "测试场景", "假设H", "动作A", "记录R", "2026-10-05")
    database.update_experiment(exp, outcome="验证成立", status="done")
    exps = database.list_experiments(uid)
    check("实验创建并 done", exps and exps[0]["status"] == "done" and exps[0]["outcome"] == "验证成立")

    # ---- 经验卡：收藏/编辑/删除 ----
    cid = database.create_experience_card(uid, "先问清对方担心什么", "拒绝邀约", "", "theater:test")
    database.update_experience_card(cid, conclusion="改后的结论")
    cards = database.list_experience_cards(uid)
    check("经验卡编辑生效", cards[0]["conclusion"] == "改后的结论")
    database.delete_experience_card(cid)
    check("经验卡删除", database.list_experience_cards(uid) == [])

    # ---- 自律：打卡 → 宠物奖励 + 农场额度 ----
    gid = database.add_goal(uid, "早睡", 4, 0, 7, "health")
    before = database.get_pet_state(uid)["exp"]
    database.discipline_check(uid, gid, True)
    after = database.get_pet_state(uid)["exp"]
    check("打卡给宠物加经验", after > before, f"{before} -> {after}")
    # 农场额度 = 3 + 今日打卡数
    f = database.farm_plant(uid)
    if "error" in f:
        check("农场种植（额度应>=4）", False, f.get("error"))
    else:
        check("农场种植成功（打卡解锁额度）", True, f"harvest={f['harvest']}")

    # ---- 汇总 ----
    print("\n" + "=" * 40)
    fails = [n for n, ok, _ in RESULTS if not ok]
    print(f"共 {len(RESULTS)} 项，失败 {len(fails)} 项")
    for n in fails:
        print("  FAIL:", n)
    # 清理临时库
    database._conn.close()
    database._conn = None
    os.remove(tmp)
    print(f"已清理临时库 {tmp}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
