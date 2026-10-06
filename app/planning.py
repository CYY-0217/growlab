"""规划方向的规则逻辑：时间冲突检查 + 操作应用 / 撤销。

纯 Python 规则 + database 读写，不调模型（模型的候选调整在 agent_engine.adjust_conflict）。
"""
import json
from datetime import datetime

import database


def _to_min(hhmm: str) -> int | None:
    """HH:MM → 分钟。空/非法返回 None。"""
    if not hhmm:
        return None
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _weekday(date_str: str) -> int | None:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").weekday()  # 0=周一..6=周日
    except ValueError:
        return None


def check_conflicts(user_id: int, date: str, start_time: str, end_time: str,
                    ignore_item_id: int | None = None) -> list[dict]:
    """新时间槽与已有日程 / 休息时段的冲突。空列表=无冲突。"""
    conflicts = []
    s, e = _to_min(start_time), _to_min(end_time)
    if s is None or e is None or e <= s:
        return conflicts
    wd = _weekday(date)
    for item in database.list_schedule(user_id, date):
        if ignore_item_id and item["id"] == ignore_item_id:
            continue
        if item["status"] == "cancelled":
            continue
        is_, ie = _to_min(item["start_time"]), _to_min(item["end_time"])
        if is_ is None or ie is None:
            continue
        if s < ie and e > is_:
            conflicts.append({"type": "overlap", "item_id": item["id"],
                              "title": item["title"],
                              "start": item["start_time"], "end": item["end_time"]})
    for rw in database.list_rest_windows(user_id):
        days = [int(x) for x in (rw.get("days") or "0,1,2,3,4,5,6").split(",") if x.strip() != ""]
        if wd is not None and days and wd not in days:
            continue
        rs, re = _to_min(rw["start_time"]), _to_min(rw["end_time"])
        if rs is None or re is None:
            continue
        hit = False
        if re <= rs:  # 跨午夜：拆成 [rs,24:00) 与 [00:00,re) 两段
            hit = (s < 24 * 60 and e > rs) or (s < re and e > 0)
        else:
            hit = (s < re and e > rs)
        if hit:
            conflicts.append({"type": "rest", "label": rw.get("label") or "休息",
                              "start": rw["start_time"], "end": rw["end_time"]})
    return conflicts


def check_capacity(user_id: int, date: str, new_duration_min: int,
                   ignore_item_id: int | None = None) -> dict | None:
    """当日总计划时长 + 新增 是否超过可用时间（24h - 休息时段）。"""
    wd = _weekday(date)
    rest_total = 0
    for rw in database.list_rest_windows(user_id):
        days = [int(x) for x in (rw.get("days") or "").split(",") if x.strip() != ""]
        if wd is not None and days and wd not in days:
            continue
        rs, re = _to_min(rw["start_time"]), _to_min(rw["end_time"])
        if rs is None or re is None:
            continue
        if re <= rs:
            re += 24 * 60
        rest_total += re - rs
    available = 24 * 60 - rest_total
    scheduled = sum((it["duration_min"] or 0) for it in database.list_schedule(user_id, date)
                    if it["status"] != "cancelled" and (not ignore_item_id or it["id"] != ignore_item_id))
    if scheduled + (new_duration_min or 0) > available:
        return {"type": "capacity", "scheduled": scheduled,
                "available": available, "new": new_duration_min}
    return None


def _find_schedule(user_id: int, date: str, title: str) -> dict | None:
    for it in database.list_schedule(user_id, date):
        if it["title"] == title and it["status"] != "cancelled":
            return it
    return None


def _find_goal(user_id: int, goal_id, title: str) -> dict | None:
    if goal_id:
        for g in database.list_goals(user_id, active_only=False):
            if str(g["id"]) == str(goal_id):
                return g
    if title:
        for g in database.list_goals(user_id, active_only=False):
            if g["title"] == title:
                return g
    return None


def apply_op(user_id: int, op: dict) -> dict:
    """应用一个已确认的操作，写库并返回撤销快照。"""
    intent = op.get("intent")
    title = (op.get("goal_title") or "").strip()
    date = op.get("date") or ""
    st = op.get("start_time") or ""
    et = op.get("end_time") or ""
    dur = op.get("duration_min") or 0
    if not dur and st and et:
        sm, em = _to_min(st), _to_min(et)
        if sm is not None and em is not None and em > sm:
            dur = em - sm

    if intent == "add":
        if not title or not date:
            return {"not_found": "缺少标题或日期"}
        # 建一个目标（待办）→ 在自律里出现；有时间槽就再建日程并关联
        gid = database.add_goal(user_id, title, weight=3)
        sid = None
        if st or et:
            sid = database.add_schedule_item(user_id, title, date, st, et, dur, gid, "agent")
        return {"applied": {"goal_id": gid, "schedule_id": sid},
                "snapshot": {"type": "add", "goal_id": gid, "schedule_id": sid}}

    if intent == "status":
        ms = op.get("metrics") or []
        if not ms:
            return {"not_found": "没有可记录的维度"}
        ids = [database.add_metric(user_id, date, m["dimension"], m.get("value"),
                                   m.get("source", "self_report"), "actual") for m in ms]
        return {"applied": {"metric_ids": ids},
                "snapshot": {"type": "metrics_add", "ids": ids}}

    if intent == "cancel":
        it = _find_schedule(user_id, date, title) if (title and date) else None
        if it:
            database.update_schedule_item(it["id"], status="cancelled")
            return {"applied": {"schedule_id": it["id"]},
                    "snapshot": {"type": "schedule_status", "id": it["id"],
                                 "old_status": it["status"]}}
        g = _find_goal(user_id, op.get("goal_id"), title)
        if g:
            database.deactivate_goal(g["id"])
            return {"applied": {"goal_id": g["id"], "active": 0},
                    "snapshot": {"type": "goal_active", "id": g["id"],
                                 "old_active": g.get("active", 1)}}
        return {"not_found": "没找到要取消的目标/日程"}

    if intent == "complete":
        g = _find_goal(user_id, op.get("goal_id"), title)
        if not g:
            return {"not_found": "没找到要打卡的目标"}
        conn = database.get_conn()
        row = conn.execute("SELECT checkins FROM daily_entries WHERE user_id=? AND entry_date=?",
                           (user_id, date)).fetchone()
        old = json.loads(row["checkins"] or "{}") if row else {}
        new = dict(old)
        new[str(g["id"])] = 1.0
        database.upsert_daily_entry(user_id, date, checkins=new)
        return {"applied": {"goal_id": g["id"], "checked": True},
                "snapshot": {"type": "checkin", "date": date,
                             "goal_id": str(g["id"]), "old_value": old.get(str(g["id"]))}}

    if intent == "modify":
        it = _find_schedule(user_id, date, title) if (title and date) else None
        if it:
            old = {"title": it["title"], "start_time": it["start_time"],
                   "end_time": it["end_time"], "duration_min": it["duration_min"]}
            fields = {}
            if st:
                fields["start_time"] = st
            if et:
                fields["end_time"] = et
            if dur:
                fields["duration_min"] = dur
            if not fields:
                return {"not_found": "没有要改的内容"}
            database.update_schedule_item(it["id"], **fields)
            return {"applied": {"schedule_id": it["id"]},
                    "snapshot": {"type": "schedule_fields", "id": it["id"], "old": old}}
        return {"not_found": "没找到要修改的日程（首轮仅支持改日程时段）"}

    return {"unsupported": intent}


def revert_op(user_id: int, snapshot: dict) -> dict:
    """按快照撤销一次已应用的操作。"""
    t = snapshot.get("type")
    if t == "add" or t == "schedule_add":
        if snapshot.get("schedule_id"):
            database.delete_schedule_item(snapshot["schedule_id"])
        if snapshot.get("goal_id"):
            conn = database.get_conn()
            conn.execute("DELETE FROM goals WHERE id=?", (snapshot["goal_id"],))
            conn.commit()
    elif t == "schedule_status":
        database.update_schedule_item(snapshot["id"], status=snapshot["old_status"])
    elif t == "schedule_fields":
        database.update_schedule_item(snapshot["id"], **snapshot["old"])
    elif t == "metrics_add":
        conn = database.get_conn()
        for mid in snapshot["ids"]:
            conn.execute("DELETE FROM metrics WHERE id=?", (mid,))
        conn.commit()
    elif t == "goal_active":
        conn = database.get_conn()
        conn.execute("UPDATE goals SET active=? WHERE id=?",
                     (snapshot["old_active"], snapshot["id"]))
        conn.commit()
    elif t == "checkin":
        conn = database.get_conn()
        row = conn.execute("SELECT checkins FROM daily_entries WHERE user_id=? AND entry_date=?",
                           (user_id, snapshot["date"])).fetchone()
        if row:
            checks = json.loads(row["checkins"] or "{}")
            if snapshot["old_value"] is None:
                checks.pop(snapshot["goal_id"], None)
            else:
                checks[snapshot["goal_id"]] = snapshot["old_value"]
            database.upsert_daily_entry(user_id, snapshot["date"], checkins=checks)
    return {"ok": True}
