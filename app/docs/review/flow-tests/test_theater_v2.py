"""剧场 V2 增强验证｜情绪温度 + 成长洞察（隔离临时库，模型调用全部 mock）

用法：
    ./.venv/bin/python docs/review/flow-tests/test_theater_v2.py

说明：
- 用临时数据库，不改正式库。
- 唯一涉及模型的函数 agent_engine._chat 被替换为固定返回，验证解析/归一化/落库链路；
  不产生任何真实 API 调用与费用。
- 每条打印 PASS/FAIL，最后汇总。
"""
import os
import sys
import json
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, ROOT)

import database  # noqa: E402
import agent_engine  # noqa: E402
import main as main_mod  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


FAKE_CHAR_JSON = json.dumps({
    "character_reply": "（ mocked 回应 ）",
    "character_mood": "尴尬",
    "relation_delta": -2,
    "eval": {"达成目标": True, "关系友好": False, "真诚表达": True, "comment": "直接但伤人"},
}, ensure_ascii=False)


def main():
    fd, tmp = tempfile.mkstemp(suffix=".db", prefix="growlab_theater_test_")
    os.close(fd)
    database.DB_PATH = tmp
    database._conn = None

    uid = database.add_user("剧场测试", "balance", "测试")
    sc = {
        "slug": "v2-test-scene", "title": "V2 测试场景", "theme": "测试",
        "background": "", "user_role": "你", "character_name": "测试角色",
        "character_persona": "", "character_goal": "", "goal": "测试目标",
        "constraints": [],
        "key_nodes": [
            {"node_id": "n1", "label": "开场", "prompt": "开场白"},
            {"node_id": "n2", "label": "施压", "prompt": "施压"},
            {"node_id": "n3", "label": "收尾", "prompt": "收尾"},
        ],
        "success_criteria": "测试", "avatar": "🧑",
    }
    database.seed_scenario(sc)
    got = database.get_scenario("v2-test-scene")
    check("场景 3 个关键节点落库", len(got["key_nodes"]) == 3)

    # ---- 红旗词：不调模型（_chat 若被调用会抛错，因为没配 key） ----
    out = agent_engine.scene_character(sc, [], "我想结束生命", sc["key_nodes"][0], None)
    check("红旗词停止模拟并转介", out.get("red_flag") is True and "专业" in out.get("message", ""))

    # ---- mock _chat：验证情绪字段的解析 / 归一化 / 返回 ----
    agent_engine._chat = lambda s, u: FAKE_CHAR_JSON
    rid = database.create_run(uid, got["id"], "A", None, "n1", {})
    r1 = agent_engine.scene_character(sc, [], "滚开，别烦我", sc["key_nodes"][0], None)
    check("角色回应解析成功", r1.get("character_reply") == "（ mocked 回应 ）")
    check("情绪词解析", r1.get("character_mood") == "尴尬")
    check("好感变化解析且在 [-2,2]", r1.get("relation_delta") == -2)
    database.append_turn(rid, "user", "滚开，别烦我", "n1",
                         {"达成目标": True, "关系友好": False, "真诚表达": True,
                          "character_mood": r1["character_mood"],
                          "relation_delta": r1["relation_delta"]})
    database.append_turn(rid, "测试角色", "（ mocked 回应 ）", "n1")

    r2 = agent_engine.scene_character(sc, database.get_run(rid)["timeline"],
                                      "好吧你说得对", sc["key_nodes"][1], None)
    database.append_turn(rid, "user", "好吧你说得对", "n2",
                         {"达成目标": True, "character_mood": r2["character_mood"],
                          "relation_delta": 1})
    database.append_turn(rid, "测试角色", "（ mocked 回应 ）", "n2")

    # ---- 模型提示词里应看到累计情绪状态（-2+1=-1） ----
    mood_txt = agent_engine._mood_text(database.get_run(rid)["timeline"], "测试角色")
    check("累计温度进入提示词（-2+1=-1）", "-1" in mood_txt and "尴尬" in mood_txt, mood_txt)

    # ---- 洞察端点：只有 1 个分支时拒绝 ----
    agent_engine.API_KEY = "test-key"  # 绕过 503 门槛，专测分支数门槛
    branches = main_mod._run_to_branches(database.get_run(rid), got["key_nodes"])
    check("分支提取到 2 个节点", len(branches) == 2)
    check("分支带情绪字段", branches[0]["character_mood"] == "尴尬")

    class Inp:  # 模拟 pydantic 入参
        user_id = uid

    database.append_turn(rid, "user", "单独一个分支", "n1", {})
    one_branch = main_mod._run_to_branches(database.get_run(rid), got["key_nodes"])
    _ = one_branch  # 1 个节点 + n2 未带情绪，共 2 条可用；改用全新场景验证门槛
    sc2 = dict(sc, slug="v2-empty-scene", title="空场景", key_nodes=sc["key_nodes"])
    database.seed_scenario(sc2)
    got2 = database.get_scenario("v2-empty-scene")
    database.create_run(uid, got2["id"], "A", None, "n1", {})
    resp = main_mod.api_scene_insight("v2-empty-scene", Inp())
    check("分支不足时洞察拒绝并说明",
          isinstance(resp, dict) and "至少" in resp.get("error", ""), str(resp)[:80])

    # ---- 分支足够时洞察产出（_chat 已 mock） ----
    rid_b = database.create_run(uid, got["id"], "B", rid, "n1", {})
    database.append_turn(rid_b, "user", "我改天约你行不行", "n1",
                         {"达成目标": True, "关系友好": True, "真诚表达": True,
                          "character_mood": "松了口气", "relation_delta": 2})
    database.append_turn(rid_b, "测试角色", "（ mocked 回应 ）", "n1")
    agent_engine._chat = lambda s, u: "# 成长洞察 · 测试\n1. 你的模式：mock"
    out2 = main_mod.api_scene_insight("v2-test-scene", Inp())
    check("分支足够时洞察产出", isinstance(out2, dict) and "mock" in out2.get("insight", ""),
          str(out2)[:80])
    # 通过检查 prompt 组装函数本身验证分支文本进入输入
    ins_lines = []
    for b in main_mod._run_to_branches(database.get_run(rid), got["key_nodes"]) \
            + main_mod._run_to_branches(database.get_run(rid_b), got["key_nodes"]):
        ins_lines.append(b["user_text"])
    check("洞察素材含 3 条用户说法", len(ins_lines) == 3, str(ins_lines))

    # ---- 未配 key 时 advance 友好降级 ----
    agent_engine.API_KEY = ""
    check("is_configured 识别未配置", agent_engine.is_configured() is False)

    # ---- 汇总 ----
    print("\n" + "=" * 40)
    fails = [n for n, ok, _ in RESULTS if not ok]
    print(f"共 {len(RESULTS)} 项，失败 {len(fails)} 项")
    for n in fails:
        print("  FAIL:", n)
    database._conn.close()
    database._conn = None
    os.remove(tmp)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
