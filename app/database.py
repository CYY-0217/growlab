"""SQLite 数据层：表结构 + CRUD。

设计原则（源自 selfagent 的 6 天运营教训）：
- Agent 的每次输入/输出必须落库可追溯（agent_outputs 表）
- "未知不结算"：当日无回传时 settlement_status='gap'，不伪造数据
- 所有时间戳可回放，演示时可展示真实闭环证据链
"""
import sqlite3
import json
import os
import random
from datetime import date, datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "learner_agent.db")

_conn = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        # check_same_thread=False：FastAPI 的同步端点跑在线程池里，每个请求可能在不同线程
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        init_db(_conn)
    return _conn


def init_db(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT 'balance',  -- self/balance/swim/think
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        weight INTEGER NOT NULL DEFAULT 3,        -- W 权重 1-5
        standard_duration_min INTEGER DEFAULT 25, -- 标准耗时（分钟）
        weekly_frequency INTEGER DEFAULT 7,       -- 每周次数
        category TEXT DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1,        -- 0=已停用/调整替换
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS daily_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        entry_date TEXT NOT NULL,                 -- YYYY-MM-DD
        raw_text TEXT DEFAULT '',                 -- 用户一句话回传原文
        checkins TEXT NOT NULL DEFAULT '{}',      -- JSON {goal_id: C(0~1)}
        focus_min INTEGER DEFAULT 0,
        note TEXT DEFAULT '',
        settlement_status TEXT NOT NULL DEFAULT 'pending', -- pending/settled/gap
        w_complete REAL,                          -- 结算后写入，未知不填
        created_at TEXT NOT NULL,
        UNIQUE(user_id, entry_date)
    );

    CREATE TABLE IF NOT EXISTS agent_outputs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER REFERENCES users(id),     -- idea 类可为 NULL
        output_type TEXT NOT NULL,                -- breakdown/adjustment/report/idea
        input_text TEXT NOT NULL DEFAULT '',
        output_text TEXT NOT NULL DEFAULT '',
        approved INTEGER,                         -- NULL=待确认, 1=已采纳, 0=已否决
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS scenarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        theme TEXT DEFAULT '',
        background TEXT DEFAULT '',
        user_role TEXT DEFAULT '',
        character_name TEXT DEFAULT '',
        character_persona TEXT DEFAULT '',
        character_goal TEXT DEFAULT '',
        goal TEXT DEFAULT '',
        avatar TEXT DEFAULT '🧑',                 -- 角色头像 emoji
        constraints TEXT NOT NULL DEFAULT '[]',   -- JSON array
        key_nodes TEXT NOT NULL DEFAULT '[]',     -- JSON array {node_id,label,prompt}
        success_criteria TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS scene_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
        branch_label TEXT DEFAULT 'A',            -- A/B/... 分支标识
        parent_run_id INTEGER,                    -- 重演时指向被重演的那次 run
        node_id TEXT DEFAULT '',                  -- 当前关键节点
        status TEXT NOT NULL DEFAULT 'active',    -- active/completed
        timeline TEXT NOT NULL DEFAULT '[]',      -- JSON [{speaker,text,node_id,eval}]
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS experiments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        source_scene TEXT DEFAULT '',
        hypothesis TEXT DEFAULT '',
        action TEXT DEFAULT '',
        record_what TEXT DEFAULT '',
        review_date TEXT DEFAULT '',
        outcome TEXT DEFAULT '',
        expected_vs_actual TEXT DEFAULT '',
        keep_or_drop TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'planned',   -- planned/done/abandoned
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS memory_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind TEXT DEFAULT 'experience',           -- preference/assumption/experience/artifact
        content TEXT NOT NULL DEFAULT '',
        source_ref TEXT DEFAULT '',
        editable INTEGER DEFAULT 1,
        deleted INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS explorations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        feeling TEXT DEFAULT '',
        directions TEXT NOT NULL DEFAULT '[]',    -- JSON
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS pets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL DEFAULT '小豆',
        species TEXT NOT NULL DEFAULT '🐱',       -- 宠物 emoji（可换皮肤）
        exp INTEGER NOT NULL DEFAULT 0,           -- 经验（level = exp//100 + 1）
        satiety INTEGER NOT NULL DEFAULT 80,      -- 饱食度 0-100
        energy INTEGER NOT NULL DEFAULT 80,       -- 精力 0-100
        mood INTEGER NOT NULL DEFAULT 70,         -- 心情 0-100
        last_feed_at TEXT NOT NULL,               -- 最近喂食（据此衰减饱食）
        last_sleep_at TEXT NOT NULL,
        last_play_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS pet_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pet_id INTEGER NOT NULL REFERENCES pets(id) ON DELETE CASCADE,
        kind TEXT NOT NULL DEFAULT '',            -- study/feed/sleep/play/explore/lab/note
        note TEXT DEFAULT '',
        exp INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,                -- '0'..'15'
        name TEXT NOT NULL,
        keywords TEXT DEFAULT '',
        meaning TEXT DEFAULT '',
        img TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS user_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        card_code TEXT NOT NULL,
        drawn_at TEXT NOT NULL,
        UNIQUE(user_id, card_code)
    );

    CREATE TABLE IF NOT EXISTS growth_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind TEXT NOT NULL DEFAULT '',          -- explore/practice/experiment/experience
        title TEXT DEFAULT '',
        summary TEXT DEFAULT '',                -- 交接给下游的可编辑摘要（唯一传递物）
        source_ref TEXT DEFAULT '',             -- 来源标识，如 theater:run:12
        status TEXT NOT NULL DEFAULT 'draft',   -- draft/confirmed
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS experience_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        conclusion TEXT NOT NULL DEFAULT '',    -- 用户认可的结论
        situation TEXT DEFAULT '',              -- 适用情境
        limitation TEXT DEFAULT '',             -- 限制
        source_ref TEXT DEFAULT '',             -- 来源事件
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS farms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        plots TEXT NOT NULL DEFAULT '[null,null,null,null,null,null]',  -- 6 块地 [{crop,planted_at}|null]
        harvest INTEGER NOT NULL DEFAULT 0,     -- 累计收成
        plants_today INTEGER NOT NULL DEFAULT 0,
        last_plant_date TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );

    -- ===== 规划方向：学业与身心平衡（文字驱动） =====

    CREATE TABLE IF NOT EXISTS schedule_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        date TEXT NOT NULL,                   -- YYYY-MM-DD（首轮按天）
        start_time TEXT DEFAULT '',           -- HH:MM，空=不指定时段
        end_time TEXT DEFAULT '',
        duration_min INTEGER DEFAULT 0,       -- 预估时长（分钟）
        goal_id INTEGER REFERENCES goals(id), -- 可关联目标（可空）
        status TEXT NOT NULL DEFAULT 'planned', -- planned/done/cancelled
        source TEXT DEFAULT 'agent',          -- agent/user
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS rest_windows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        label TEXT DEFAULT '',
        start_time TEXT NOT NULL,             -- HH:MM
        end_time TEXT NOT NULL,
        days TEXT DEFAULT '0,1,2,3,4,5,6',    -- 生效星期 0=周一..6=周日
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS pending_ops (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,                   -- add/modify/cancel/complete/status
        payload TEXT NOT NULL DEFAULT '{}',   -- JSON 操作内容
        before_snapshot TEXT DEFAULT '',      -- JSON 撤销快照
        status TEXT NOT NULL DEFAULT 'pending', -- pending/confirmed/applied/cancelled/reverted
        agent_output_id INTEGER,
        created_at TEXT NOT NULL,
        applied_at TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        date TEXT NOT NULL,                   -- YYYY-MM-DD
        dimension TEXT NOT NULL,              -- sleep/energy/focus/stress
        value REAL,                           -- NULL=未知，0=明确为零
        source TEXT NOT NULL DEFAULT 'self_report', -- self_report/device
        kind TEXT NOT NULL DEFAULT 'actual',  -- plan/actual
        note TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );
    """)
    conn.commit()
    # 迁移：旧库补 avatar 列
    cols = [r[1] for r in conn.execute("PRAGMA table_info(scenarios)")]
    if "avatar" not in cols:
        conn.execute("ALTER TABLE scenarios ADD COLUMN avatar TEXT DEFAULT '🧑'")
        conn.commit()
    # 迁移：scene_runs 补 director 列
    cols2 = [r[1] for r in conn.execute("PRAGMA table_info(scene_runs)")]
    if "director" not in cols2:
        conn.execute("ALTER TABLE scene_runs ADD COLUMN director TEXT DEFAULT '{}'")
        conn.commit()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------- users ----------

def add_user(name: str, category: str = "balance", notes: str = "") -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO users(name, category, notes, created_at) VALUES(?,?,?,?)",
        (name, category, notes, now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def list_users() -> list[dict]:
    return [dict(r) for r in get_conn().execute("SELECT * FROM users ORDER BY id")]


def get_user(user_id: int) -> dict | None:
    r = get_conn().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(r) if r else None


# ---------- goals ----------

def add_goal(user_id: int, title: str, weight: int = 3,
             standard_duration_min: int = 25, weekly_frequency: int = 7,
             category: str = "") -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO goals(user_id, title, weight, standard_duration_min,
           weekly_frequency, category, created_at) VALUES(?,?,?,?,?,?,?)""",
        (user_id, title, weight, standard_duration_min, weekly_frequency,
         category, now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def list_goals(user_id: int, active_only: bool = True) -> list[dict]:
    q = "SELECT * FROM goals WHERE user_id=?"
    if active_only:
        q += " AND active=1"
    return [dict(r) for r in get_conn().execute(q + " ORDER BY id", (user_id,))]


def deactivate_goal(goal_id: int):
    conn = get_conn()
    conn.execute("UPDATE goals SET active=0 WHERE id=?", (goal_id,))
    conn.commit()


# ---------- daily entries ----------

def upsert_daily_entry(user_id: int, entry_date: str, raw_text: str = "",
                       checkins: dict | None = None, focus_min: int = 0,
                       note: str = "") -> int:
    conn = get_conn()
    conn.execute(
        """INSERT INTO daily_entries(user_id, entry_date, raw_text, checkins,
           focus_min, note, settlement_status, created_at)
           VALUES(?,?,?,?,?,?, 'settled', ?)
           ON CONFLICT(user_id, entry_date) DO UPDATE SET
             raw_text=excluded.raw_text,
             checkins=excluded.checkins,
             focus_min=excluded.focus_min,
             note=excluded.note,
             settlement_status='settled'""",
        (user_id, entry_date, raw_text, json.dumps(checkins or {}), focus_min,
         note, now_iso()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM daily_entries WHERE user_id=? AND entry_date=?",
        (user_id, entry_date),
    ).fetchone()
    return row["id"]


def mark_gap_days(user_id: int, dates: list[str]):
    """把无回传的日期登记为 gap（不结算，不伪造数据）。"""
    conn = get_conn()
    for d in dates:
        conn.execute(
            """INSERT OR IGNORE INTO daily_entries
               (user_id, entry_date, raw_text, checkins, settlement_status, created_at)
               VALUES(?,?,?,?, 'gap', ?)""",
            (user_id, d, "", "{}", now_iso()),
        )
    conn.commit()


def list_entries(user_id: int, days: int = 14, end_date: str | None = None) -> list[dict]:
    """近 N 天日志，按日期升序。空缺日期不补造（gap 由 mark_gap_days 显式登记）。"""
    if end_date is None:
        end_date = date.today().isoformat()
    rows = get_conn().execute(
        """SELECT * FROM daily_entries WHERE user_id=? AND entry_date<=?
           ORDER BY entry_date DESC LIMIT ?""",
        (user_id, end_date, days),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def compute_w_complete(entry: dict, goals: list[dict]) -> float | None:
    """W-Complete = Σ(W×C) / ΣW。checkins 里缺的目标视为'未知'，
    按 selfagent §9 红线：未知不填 0 —— 该目标权重计入分母吗？
    采用保守口径：未回传的目标不计入分母（只结算已知部分），
    若全部未知返回 None（数据缺口日）。"""
    try:
        checks = json.loads(entry["checkins"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    sw = sc = 0.0
    for g in goals:
        gid = str(g["id"])
        if gid in checks and checks[gid] is not None:
            sw += g["weight"]
            sc += g["weight"] * max(0.0, min(1.0, float(checks[gid])))
    return round(sc / sw, 3) if sw > 0 else None


# ---------- agent outputs ----------

def save_agent_output(user_id: int | None, output_type: str, input_text: str,
                      output_text: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO agent_outputs(user_id, output_type, input_text,
           output_text, created_at) VALUES(?,?,?,?,?)""",
        (user_id, output_type, input_text, output_text, now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def decide_agent_output(output_id: int, approved: bool):
    conn = get_conn()
    conn.execute("UPDATE agent_outputs SET approved=? WHERE id=?",
                 (1 if approved else 0, output_id))
    conn.commit()


def list_agent_outputs(user_id: int | None = None, limit: int = 20) -> list[dict]:
    if user_id is None:
        rows = get_conn().execute(
            "SELECT * FROM agent_outputs ORDER BY id DESC LIMIT ?", (limit,))
    else:
        rows = get_conn().execute(
            "SELECT * FROM agent_outputs WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit))
    return [dict(r) for r in rows]


# ---------- stats ----------

def user_stats(user_id: int) -> dict:
    """给看板用的简要统计：近 7 天有效日、gap 日、平均 W-Complete。"""
    goals = list_goals(user_id)
    entries = list_entries(user_id, days=7)
    settled = [e for e in entries if e["settlement_status"] == "settled"]
    gaps = [e for e in entries if e["settlement_status"] == "gap"]
    ws = [compute_w_complete(e, goals) for e in settled]
    ws = [w for w in ws if w is not None]
    return {
        "days_settled": len(settled),
        "days_gap": len(gaps),
        "avg_w_complete": round(sum(ws) / len(ws), 3) if ws else None,
    }


# ---------- scenarios ----------

def seed_scenario(sc: dict):
    """幂等写入场景（按 slug）。key_nodes/constraints 是 list，转 JSON 存。"""
    conn = get_conn()
    exists = conn.execute("SELECT id FROM scenarios WHERE slug=?",
                          (sc["slug"],)).fetchone()
    vals = (
        sc["title"], sc.get("theme", ""), sc.get("background", ""),
        sc.get("user_role", ""), sc.get("character_name", ""),
        sc.get("character_persona", ""), sc.get("character_goal", ""),
        sc.get("goal", ""), sc.get("avatar", "🧑"),
        json.dumps(sc.get("constraints", []), ensure_ascii=False),
        json.dumps(sc.get("key_nodes", []), ensure_ascii=False),
        sc.get("success_criteria", ""),
    )
    if exists:
        conn.execute(
            """UPDATE scenarios SET title=?,theme=?,background=?,user_role=?,
               character_name=?,character_persona=?,character_goal=?,goal=?,
               avatar=?,constraints=?,key_nodes=?,success_criteria=? WHERE slug=?""",
            (*vals, sc["slug"]))
    else:
        conn.execute(
            """INSERT INTO scenarios(slug,title,theme,background,user_role,
               character_name,character_persona,character_goal,goal,avatar,constraints,
               key_nodes,success_criteria,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sc["slug"], *vals, now_iso()))
    conn.commit()


def list_scenarios() -> list[dict]:
    rows = get_conn().execute("SELECT * FROM scenarios ORDER BY id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["constraints"] = json.loads(d["constraints"] or "[]")
        d["key_nodes"] = json.loads(d["key_nodes"] or "[]")
        out.append(d)
    return out


def get_scenario(sid) -> dict | None:
    conn = get_conn()
    r = conn.execute("SELECT * FROM scenarios WHERE id=? OR slug=?",
                     (sid, sid)).fetchone() if isinstance(sid, (int, str)) else None
    if not r:
        return None
    d = dict(r)
    d["constraints"] = json.loads(d["constraints"] or "[]")
    d["key_nodes"] = json.loads(d["key_nodes"] or "[]")
    return d


# ---------- scene_runs ----------

def create_run(user_id: int, scenario_id: int, branch_label: str = "A",
               parent_run_id: int | None = None, node_id: str = "",
               director: dict | None = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO scene_runs(user_id,scenario_id,branch_label,parent_run_id,
           node_id,director,status,created_at) VALUES(?,?,?,?,?,?,'active',?)""",
        (user_id, scenario_id, branch_label, parent_run_id, node_id,
         json.dumps(director or {}, ensure_ascii=False), now_iso()))
    conn.commit()
    return cur.lastrowid


def get_run(run_id: int) -> dict | None:
    r = get_conn().execute("SELECT * FROM scene_runs WHERE id=?",
                           (run_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["timeline"] = json.loads(d["timeline"] or "[]")
    d["director"] = json.loads(d.get("director") or "{}")
    return d


def append_turn(run_id: int, speaker: str, text: str, node_id: str = "",
                eval_meta: dict | None = None):
    """追加一轮对话到 timeline。"""
    run = get_run(run_id)
    if run is None:
        return
    tl = run["timeline"]
    tl.append({"speaker": speaker, "text": text, "node_id": node_id,
               "eval": eval_meta or {}})
    get_conn().execute("UPDATE scene_runs SET timeline=? WHERE id=?",
                       (json.dumps(tl, ensure_ascii=False), run_id))
    get_conn().commit()


def update_run(run_id: int, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [run_id]
    get_conn().execute(f"UPDATE scene_runs SET {cols} WHERE id=?", vals)
    get_conn().commit()


def list_runs(user_id: int, scenario_id: int) -> list[dict]:
    rows = get_conn().execute(
        "SELECT * FROM scene_runs WHERE user_id=? AND scenario_id=? ORDER BY id",
        (user_id, scenario_id)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["timeline"] = json.loads(d["timeline"] or "[]")
        d["director"] = json.loads(d.get("director") or "{}")
        out.append(d)
    return out


# ---------- experiments ----------

def create_experiment(user_id: int, source_scene: str = "", hypothesis: str = "",
                      action: str = "", record_what: str = "", review_date: str = "") -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO experiments(user_id,source_scene,hypothesis,action,record_what,
           review_date,status,created_at) VALUES(?,?,?,?,?,?,'planned',?)""",
        (user_id, source_scene, hypothesis, action, record_what, review_date, now_iso()))
    conn.commit()
    return cur.lastrowid


def list_experiments(user_id: int) -> list[dict]:
    return [dict(r) for r in get_conn().execute(
        "SELECT * FROM experiments WHERE user_id=? ORDER BY id DESC", (user_id,))]


def update_experiment(exp_id: int, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    get_conn().execute(f"UPDATE experiments SET {cols} WHERE id=?",
                       list(fields.values()) + [exp_id])
    get_conn().commit()


# ---------- memory_entries ----------

def add_memory(user_id: int, kind: str, content: str, source_ref: str = "") -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO memory_entries(user_id,kind,content,source_ref,created_at) "
        "VALUES(?,?,?,?,?)", (user_id, kind, content, source_ref, now_iso()))
    conn.commit()
    return cur.lastrowid


def list_memory(user_id: int, include_deleted: bool = False) -> list[dict]:
    q = "SELECT * FROM memory_entries WHERE user_id=?"
    if not include_deleted:
        q += " AND deleted=0"
    return [dict(r) for r in get_conn().execute(q + " ORDER BY id DESC", (user_id,))]


def edit_memory(mid: int, content: str):
    get_conn().execute("UPDATE memory_entries SET content=? WHERE id=?",
                       (content, mid))
    get_conn().commit()


def delete_memory(mid: int):
    """软删除：停止影响后续，但保留出处。"""
    get_conn().execute("UPDATE memory_entries SET deleted=1 WHERE id=?", (mid,))
    get_conn().commit()


# ---------- explorations ----------

def add_exploration(user_id: int, feeling: str, directions: list) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO explorations(user_id,feeling,directions,created_at) VALUES(?,?,?,?)",
        (user_id, feeling, json.dumps(directions, ensure_ascii=False), now_iso()))
    conn.commit()
    return cur.lastrowid


def list_explorations(user_id: int) -> list[dict]:
    rows = get_conn().execute(
        "SELECT * FROM explorations WHERE user_id=? ORDER BY id DESC", (user_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["directions"] = json.loads(d["directions"] or "[]")
        out.append(d)
    return out


# ---------- 宠物（成长伙伴） ----------

def _hours_since(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, (datetime.now() - dt).total_seconds() / 3600)


def _decayed(p: dict) -> tuple[int, int, int]:
    """按各自最近一次照料时间衰减后的 (饱食, 精力, 心情)。不落库，只用于展示/结算。"""
    s = max(0, int(p["satiety"] - _hours_since(p["last_feed_at"]) * 2.0))
    e = max(0, int(p["energy"] - _hours_since(p["last_sleep_at"]) * 1.5))
    m = max(0, int(p["mood"] - _hours_since(p["last_play_at"]) * 1.0))
    if s < 20:
        m = max(0, m - 12)   # 饿肚子会闹脾气
    if e < 20:
        m = max(0, m - 12)   # 太困也会低落
    return s, e, m


def _stage(level: int) -> str:
    if level <= 1:
        return "幼崽"
    if level <= 3:
        return "成长期"
    if level <= 5:
        return "默契伙伴"
    return "灵魂搭档"


def _status(s: int, e: int, m: int) -> tuple[str, str]:
    if s < 20:
        return "饿了", "肚子咕咕叫…想吃饭了 🍎"
    if e < 20:
        return "困了", "眼皮打架…想睡觉了 😴"
    if m < 30:
        return "无聊", "有点孤单，陪我玩会儿吧 🎾"
    return "元气", "今天也一起加油吧 ✨"


def get_or_create_pet(user_id: int) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM pets WHERE user_id=?", (user_id,)).fetchone()
    if row:
        return dict(row)
    now = now_iso()
    conn.execute(
        """INSERT INTO pets(user_id,name,species,exp,satiety,energy,mood,
           last_feed_at,last_sleep_at,last_play_at,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, "小豆", "🐱", 0, 80, 80, 70, now, now, now, now))
    conn.commit()
    row = conn.execute("SELECT * FROM pets WHERE user_id=?", (user_id,)).fetchone()
    return dict(row)


def _set_pet(pet_id: int, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    get_conn().execute(f"UPDATE pets SET {cols} WHERE id=?",
                       list(fields.values()) + [pet_id])
    get_conn().commit()


def _add_event(pet_id: int, kind: str, note: str, exp: int = 0):
    get_conn().execute(
        "INSERT INTO pet_events(pet_id,kind,note,exp,created_at) VALUES(?,?,?,?,?)",
        (pet_id, kind, note, exp, now_iso()))
    get_conn().commit()


def get_pet_state(user_id: int) -> dict:
    p = get_or_create_pet(user_id)
    s, e, m = _decayed(p)
    level = p["exp"] // 100 + 1
    status, status_text = _status(s, e, m)
    events = [dict(r) for r in get_conn().execute(
        "SELECT * FROM pet_events WHERE pet_id=? ORDER BY id DESC LIMIT 8",
        (p["id"],))]
    return {
        "id": p["id"], "name": p["name"], "species": p["species"],
        "exp": p["exp"], "level": level, "stage": _stage(level),
        "satiety": s, "energy": e, "mood": m,
        "status": status, "status_text": status_text,
        "exp_to_next": max(0, level * 100 - p["exp"]),
        "events": events,
    }


def pet_feed(user_id: int) -> dict:
    p = get_or_create_pet(user_id)
    s, e, m = _decayed(p)
    s = min(100, s + 30); m = min(100, m + 6)
    _set_pet(p["id"], satiety=s, energy=e, mood=m, last_feed_at=now_iso())
    _add_event(p["id"], "feed", "吃饱啦，打了个嗝 🍎", exp=2)
    return get_pet_state(user_id)


def pet_sleep(user_id: int) -> dict:
    p = get_or_create_pet(user_id)
    s, e, m = _decayed(p)
    e = min(100, e + 70); m = min(100, m + 8); s = max(0, s - 8)
    _set_pet(p["id"], satiety=s, energy=e, mood=m, last_sleep_at=now_iso())
    _add_event(p["id"], "sleep", "美美睡了一觉，恢复元气 😴", exp=2)
    return get_pet_state(user_id)


def pet_play(user_id: int) -> dict:
    p = get_or_create_pet(user_id)
    s, e, m = _decayed(p)
    m = min(100, m + 28); e = max(0, e - 10); s = max(0, s - 6)
    _set_pet(p["id"], satiety=s, energy=e, mood=m, last_play_at=now_iso())
    _add_event(p["id"], "play", "陪你玩了一会儿，超开心 🎾", exp=2)
    return get_pet_state(user_id)


def update_pet(user_id: int, name: str | None = None, species: str | None = None) -> dict:
    p = get_or_create_pet(user_id)
    fields = {}
    if name:
        fields["name"] = name
    if species:
        fields["species"] = species
    if fields:
        _set_pet(p["id"], **fields)
    return get_pet_state(user_id)


def pet_reward(user_id: int, exp: int, kind: str, note: str = "") -> dict:
    """学习闭环里的真实动作给宠物加经验（一起上学/一起练习）。"""
    p = get_or_create_pet(user_id)
    s, e, m = _decayed(p)
    m = min(100, m + 3)
    _set_pet(p["id"], exp=p["exp"] + exp, mood=m)
    _add_event(p["id"], kind, note, exp=exp)
    return get_pet_state(user_id)


# ---------- 成长卡牌 ----------

def seed_card(card: dict):
    img = card.get("img") or f"/static/cards/card-{int(card['code']):02d}.jpg"
    conn = get_conn()
    conn.execute(
        """INSERT INTO cards(code,name,keywords,meaning,img)
           VALUES(?,?,?,?,?)
           ON CONFLICT(code) DO UPDATE SET
             name=excluded.name, keywords=excluded.keywords,
             meaning=excluded.meaning, img=excluded.img""",
        (card["code"], card["name"], card.get("keywords", ""),
         card.get("meaning", ""), img))
    conn.commit()


def list_cards(user_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM cards ORDER BY CAST(code AS INTEGER)").fetchall()
    collected = {r["card_code"] for r in conn.execute(
        "SELECT card_code FROM user_cards WHERE user_id=?", (user_id,))}
    out = []
    for r in rows:
        d = dict(r)
        d["collected"] = d["code"] in collected
        out.append(d)
    return out


def _draw_earned(user_id: int) -> int:
    """抽卡次数 = 真实学习行动（study/lab/explore/note）次数。"""
    row = get_conn().execute(
        """SELECT COUNT(*) AS n FROM pet_events pe
           JOIN pets p ON pe.pet_id = p.id
           WHERE p.user_id=? AND pe.kind IN ('study','lab','explore','note')""",
        (user_id,)).fetchone()
    return row["n"] if row else 0


def card_draw_available(user_id: int) -> int:
    spent = get_conn().execute(
        "SELECT COUNT(*) AS n FROM user_cards WHERE user_id=?", (user_id,)).fetchone()["n"]
    return max(0, _draw_earned(user_id) - spent)


def draw_card(user_id: int) -> dict:
    avail = card_draw_available(user_id)
    if avail <= 0:
        return {"error": "还没有抽卡次数，先去完成一次情境练习/实验/探索吧"}
    conn = get_conn()
    collected = {r["card_code"] for r in conn.execute(
        "SELECT card_code FROM user_cards WHERE user_id=?", (user_id,))}
    pool = [dict(r) for r in conn.execute(
        "SELECT * FROM cards ORDER BY CAST(code AS INTEGER)") if dict(r)["code"] not in collected]
    if not pool:
        return {"error": "16 张牌已集齐！"}
    card = random.choice(pool)
    conn.execute("INSERT OR IGNORE INTO user_cards(user_id,card_code,drawn_at) VALUES(?,?,?)",
                 (user_id, card["code"], now_iso()))
    conn.commit()
    card["collected"] = True
    return {"card": card, "draw_available": avail - 1,
            "total": _draw_earned(user_id), "collected_count": len(collected) + 1}


# ---------- 自律（每日 todo / 打卡） ----------

def _checkin_count(checkins_json: str) -> int:
    try:
        c = json.loads(checkins_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return 0
    return sum(1 for v in c.values() if v and float(v) > 0)


def today_entry(user_id: int) -> dict:
    """今日 daily_entry，没有就建一个空的（settled 空态）。"""
    conn = get_conn()
    d = date.today().isoformat()
    row = conn.execute("SELECT * FROM daily_entries WHERE user_id=? AND entry_date=?",
                       (user_id, d)).fetchone()
    if row:
        return dict(row)
    cur = conn.execute(
        """INSERT INTO daily_entries(user_id,entry_date,raw_text,checkins,focus_min,
           note,settlement_status,created_at) VALUES(?,?,'','{}',0,'','settled',?)""",
        (user_id, d, now_iso()))
    conn.commit()
    return dict(conn.execute("SELECT * FROM daily_entries WHERE id=?",
                             (cur.lastrowid,)).fetchone())


def discipline_state(user_id: int) -> dict:
    """自律看板数据：目标清单 + 今日打卡 + 近 30 天 + 统计。"""
    goals = list_goals(user_id)
    today = today_entry(user_id)
    checks = json.loads(today["checkins"] or "{}")
    conn = get_conn()
    rows = conn.execute(
        """SELECT entry_date, checkins, focus_min FROM daily_entries
           WHERE user_id=? AND entry_date>=?""",
        (user_id, (date.today() - timedelta(days=29)).isoformat())).fetchall()
    by_date = {r["entry_date"]: r for r in rows}
    history = []
    d0 = date.today() - timedelta(days=29)
    for i in range(30):
        d = (d0 + timedelta(days=i)).isoformat()
        r = by_date.get(d)
        if r:
            history.append({"date": d, "checked": _checkin_count(r["checkins"]),
                            "focus_min": r["focus_min"] or 0})
        else:
            history.append({"date": d, "checked": 0, "focus_min": 0})
    all_rows = conn.execute(
        "SELECT checkins, focus_min FROM daily_entries WHERE user_id=?",
        (user_id,)).fetchall()
    checked_days = sum(1 for r in all_rows if _checkin_count(r["checkins"]) > 0)
    total_focus = sum(r["focus_min"] or 0 for r in all_rows)
    # streak：从今天（或昨天，若今天还没打卡）往回数连续打卡日
    streak = 0
    d = date.today()
    if _checkin_count(today["checkins"]) == 0:
        d -= timedelta(days=1)
    while True:
        row = conn.execute(
            "SELECT checkins FROM daily_entries WHERE user_id=? AND entry_date=?",
            (user_id, d.isoformat())).fetchone()
        if row and _checkin_count(row["checkins"]) > 0:
            streak += 1
            d -= timedelta(days=1)
        else:
            break
    future = []
    for i in range(14):
        d = (date.today() + timedelta(days=i)).isoformat()
        items = list_schedule(user_id, d)
        future.append({"date": d,
                       "count": sum(1 for s in items if s["status"] != "cancelled")})
    return {
        "goals": goals,
        "today": {"checkins": checks, "focus_min": today["focus_min"] or 0,
                  "note": today["note"] or ""},
        "history": history,
        "future": future,
        "stats": {"streak": streak, "checked_days": checked_days,
                  "total_focus": total_focus},
    }


def discipline_check(user_id: int, goal_id: int, checked: bool) -> dict:
    """切换某目标今日打卡。新打卡给宠物 study 奖励。"""
    if goal_id not in {g["id"] for g in list_goals(user_id)}:
        return discipline_state(user_id)  # 目标不属于该用户，忽略
    e = today_entry(user_id)
    checks = json.loads(e["checkins"] or "{}")
    key = str(goal_id)
    was = checks.get(key, 0) and float(checks.get(key, 0)) > 0
    if checked and not was:
        checks[key] = 1.0
    elif not checked:
        checks.pop(key, None)
    upsert_daily_entry(user_id, date.today().isoformat(), checkins=checks,
                       focus_min=e["focus_min"] or 0, note=e["note"] or "")
    # 反向联动：打卡/取消 → 同步今日关联日程状态
    conn = get_conn()
    conn.execute(
        "UPDATE schedule_items SET status=? WHERE user_id=? AND goal_id=? "
        "AND date=? AND status != 'cancelled'",
        ("done" if checked else "planned", user_id, goal_id, date.today().isoformat()))
    conn.commit()
    if checked and not was:
        pet_reward(user_id, 10, "study", "自律打卡：完成一个今日目标")
    return discipline_state(user_id)


def discipline_focus(user_id: int, minutes: int) -> dict:
    e = today_entry(user_id)
    new_min = (e["focus_min"] or 0) + max(0, int(minutes))
    upsert_daily_entry(user_id, date.today().isoformat(),
                       checkins=json.loads(e["checkins"] or "{}"),
                       focus_min=new_min, note=e["note"] or "")
    return discipline_state(user_id)


def discipline_note(user_id: int, note: str) -> dict:
    e = today_entry(user_id)
    upsert_daily_entry(user_id, date.today().isoformat(),
                       checkins=json.loads(e["checkins"] or "{}"),
                       focus_min=e["focus_min"] or 0, note=note)
    return discipline_state(user_id)


# ---------- 成长事件（跨空间交接） ----------

def create_event(user_id: int, kind: str, title: str = "", summary: str = "",
                 source_ref: str = "") -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO growth_events(user_id,kind,title,summary,source_ref,status,created_at)
           VALUES(?,?,?,?,?,'draft',?)""",
        (user_id, kind, title, summary, source_ref, now_iso()))
    conn.commit()
    return cur.lastrowid


def list_events(user_id: int, include_confirmed: bool = True) -> list[dict]:
    q = "SELECT * FROM growth_events WHERE user_id=?"
    if not include_confirmed:
        q += " AND status='draft'"
    return [dict(r) for r in get_conn().execute(q + " ORDER BY id DESC", (user_id,))]


def get_event(event_id: int) -> dict | None:
    r = get_conn().execute("SELECT * FROM growth_events WHERE id=?",
                           (event_id,)).fetchone()
    return dict(r) if r else None


def update_event(event_id: int, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    get_conn().execute(f"UPDATE growth_events SET {cols} WHERE id=?",
                       list(fields.values()) + [event_id])
    get_conn().commit()


# ---------- 经验卡 ----------

def list_experience_cards(user_id: int) -> list[dict]:
    return [dict(r) for r in get_conn().execute(
        "SELECT * FROM experience_cards WHERE user_id=? ORDER BY id DESC", (user_id,))]


def create_experience_card(user_id: int, conclusion: str, situation: str = "",
                           limitation: str = "", source_ref: str = "") -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO experience_cards(user_id,conclusion,situation,limitation,
           source_ref,created_at) VALUES(?,?,?,?,?,?)""",
        (user_id, conclusion, situation, limitation, source_ref, now_iso()))
    conn.commit()
    return cur.lastrowid


def update_experience_card(card_id: int, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    get_conn().execute(f"UPDATE experience_cards SET {cols} WHERE id=?",
                       list(fields.values()) + [card_id])
    get_conn().commit()


def delete_experience_card(card_id: int):
    get_conn().execute("DELETE FROM experience_cards WHERE id=?", (card_id,))
    get_conn().commit()


# ---------- 萌宠农场（自律打卡 → 收菜；偷懒 → 枯萎/被偷） ----------

CROPS = ['🥕', '🌽', '🍅', '🍓', '🌾', '🍇']
PLOT_N = 6


def _minutes_since(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, (datetime.now() - dt).total_seconds() / 60)


def _crop_stage(planted_iso: str) -> str:
    """种子→发芽→成熟→枯萎（演示用分钟级，上线可改小时）。"""
    m = _minutes_since(planted_iso)
    if m < 2:
        return "seed"
    if m < 5:
        return "sprout"
    if m < 25:
        return "ripe"
    return "wilted"


def _raw_plots(user_id: int) -> list:
    row = get_conn().execute("SELECT plots FROM farms WHERE user_id=?",
                             (user_id,)).fetchone()
    try:
        return json.loads(row["plots"] or "[]")
    except (json.JSONDecodeError, TypeError):
        return [None] * PLOT_N


def get_farm(user_id: int) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM farms WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO farms(user_id,plots,harvest,plants_today,last_plant_date,created_at) "
            "VALUES(?,?,0,0,'',?)",
            (user_id, json.dumps([None] * PLOT_N), now_iso()))
        conn.commit()
        row = conn.execute("SELECT * FROM farms WHERE user_id=?", (user_id,)).fetchone()
    f = dict(row)
    raw = json.loads(f["plots"] or "[]")
    f["plots"] = [
        {"crop": p["crop"], "stage": _crop_stage(p["planted_at"])} if p else {"crop": "", "stage": "empty"}
        for p in raw
    ]
    return f


def _checkins_today(user_id: int) -> int:
    row = get_conn().execute(
        "SELECT checkins FROM daily_entries WHERE user_id=? AND entry_date=?",
        (user_id, date.today().isoformat())).fetchone()
    return _checkin_count(row["checkins"]) if row else 0


def farm_plant(user_id: int) -> dict:
    """种菜。每日额度 = 3 + 今日打卡数（自律联动）。"""
    conn = get_conn()
    f = get_farm(user_id)
    today = date.today().isoformat()
    plants_today = f["plants_today"] if f["last_plant_date"] == today else 0
    quota = 3 + _checkins_today(user_id)
    raw = _raw_plots(user_id)
    empty = [i for i, p in enumerate(raw) if not p]
    if plants_today >= quota:
        return {"error": "今日种植次数用完，去「自律」打卡解锁更多"}
    if not empty:
        return {"error": "田地满了，先收菜或清理枯萎"}
    idx = empty[0]
    raw[idx] = {"crop": random.choice(CROPS), "planted_at": now_iso()}
    conn.execute("UPDATE farms SET plots=?, plants_today=?, last_plant_date=? WHERE user_id=?",
                 (json.dumps(raw, ensure_ascii=False), plants_today + 1, today, user_id))
    conn.commit()
    return get_farm(user_id)


def farm_harvest(user_id: int, plot_index: int) -> dict:
    """收成熟作物；枯萎则清理（无奖励）。成熟收菜给宠物奖励。"""
    conn = get_conn()
    f = get_farm(user_id)
    if plot_index < 0 or plot_index >= PLOT_N:
        return {"error": "无效地块"}
    p = f["plots"][plot_index]
    if p["stage"] == "empty":
        return {"error": "这块地是空的"}
    raw = _raw_plots(user_id)
    if p["stage"] == "wilted":
        raw[plot_index] = None
        conn.execute("UPDATE farms SET plots=? WHERE user_id=?",
                     (json.dumps(raw, ensure_ascii=False), user_id))
        conn.commit()
        return get_farm(user_id)
    if p["stage"] != "ripe":
        return {"error": "还没成熟，再等等"}
    crop = raw[plot_index]["crop"]
    raw[plot_index] = None
    conn.execute("UPDATE farms SET plots=?, harvest=? WHERE user_id=?",
                 (json.dumps(raw, ensure_ascii=False), f["harvest"] + 1, user_id))
    conn.commit()
    pet_reward(user_id, 8, "study", f"农场收菜：{crop}")
    return get_farm(user_id)


def farm_steal(victim_user_id: int, plot_index: int, thief_user_id: int) -> dict:
    """偷菜：偷他人成熟作物，小偷得收成，被偷者作物消失。"""
    conn = get_conn()
    f = get_farm(victim_user_id)
    if plot_index < 0 or plot_index >= PLOT_N:
        return {"error": "无效地块"}
    if f["plots"][plot_index]["stage"] != "ripe":
        return {"error": "对方作物还没成熟，偷不到"}
    raw = _raw_plots(victim_user_id)
    crop = raw[plot_index]["crop"]
    raw[plot_index] = None
    conn.execute("UPDATE farms SET plots=? WHERE user_id=?",
                 (json.dumps(raw, ensure_ascii=False), victim_user_id))
    tf = get_farm(thief_user_id)
    conn.execute("UPDATE farms SET harvest=? WHERE user_id=?",
                 (tf["harvest"] + 1, thief_user_id))
    conn.commit()
    return {"stolen": crop, "farm": get_farm(victim_user_id),
            "my_harvest": get_farm(thief_user_id)["harvest"]}


def farm_community() -> list[dict]:
    """本地社区：所有学习者的农场一览（用于拜访/偷菜）。"""
    users = list_users()
    out = []
    for u in users:
        f = get_farm(u["id"])
        ripe = sum(1 for p in f["plots"] if p["stage"] == "ripe")
        out.append({"user_id": u["id"], "name": u["name"], "harvest": f["harvest"],
                    "ripe_count": ripe, "plots": f["plots"]})
    return out


def delete_event(event_id: int):
    get_conn().execute("DELETE FROM growth_events WHERE id=?", (event_id,))
    get_conn().commit()


def delete_scenario(sid) -> bool:
    """只允许删除自创场景（slug 以 custom- 开头）；内置场景受保护。"""
    sc = get_scenario(sid)
    if not sc:
        return False
    if not str(sc["slug"]).startswith("custom-"):
        return False
    get_conn().execute("DELETE FROM scenarios WHERE id=?", (sc["id"],))
    get_conn().commit()
    return True


# ---------- 日程表（学业与身心平衡规划 · 计划层） ----------

def add_schedule_item(user_id: int, title: str, date: str, start_time: str = "",
                      end_time: str = "", duration_min: int = 0,
                      goal_id: int | None = None, source: str = "agent") -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO schedule_items(user_id,title,date,start_time,end_time,
           duration_min,goal_id,status,source,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,'planned',?,?,?)""",
        (user_id, title, date, start_time, end_time, duration_min,
         goal_id, source, now_iso(), now_iso()))
    conn.commit()
    return cur.lastrowid


def get_schedule_item(item_id: int) -> dict | None:
    r = get_conn().execute("SELECT * FROM schedule_items WHERE id=?",
                           (item_id,)).fetchone()
    return dict(r) if r else None


def list_schedule(user_id: int, date: str | None = None) -> list[dict]:
    q = "SELECT * FROM schedule_items WHERE user_id=?"
    args: list = [user_id]
    if date:
        q += " AND date=?"
        args.append(date)
    q += " ORDER BY date, start_time, id"
    return [dict(r) for r in get_conn().execute(q, args)]


def update_schedule_item(item_id: int, **fields):
    if not fields:
        return
    fields["updated_at"] = now_iso()
    cols = ", ".join(f"{k}=?" for k in fields)
    get_conn().execute(f"UPDATE schedule_items SET {cols} WHERE id=?",
                       list(fields.values()) + [item_id])
    get_conn().commit()


def delete_schedule_item(item_id: int):
    get_conn().execute("DELETE FROM schedule_items WHERE id=?", (item_id,))
    get_conn().commit()


# ---------- 休息时段 ----------

def add_rest_window(user_id: int, start_time: str, end_time: str,
                    label: str = "", days: str = "0,1,2,3,4,5,6") -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO rest_windows(user_id,label,start_time,end_time,days,active,created_at)
           VALUES(?,?,?,?,?,1,?)""",
        (user_id, label, start_time, end_time, days, now_iso()))
    conn.commit()
    return cur.lastrowid


def list_rest_windows(user_id: int) -> list[dict]:
    return [dict(r) for r in get_conn().execute(
        "SELECT * FROM rest_windows WHERE user_id=? AND active=1 ORDER BY start_time",
        (user_id,))]


# ---------- 待确认操作（确认前不写入 / 可撤销） ----------

def create_pending_op(user_id: int, kind: str, payload: dict,
                      agent_output_id: int | None = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO pending_ops(user_id,kind,payload,before_snapshot,status,
           agent_output_id,created_at) VALUES(?,?,?,?, 'pending', ?,?)""",
        (user_id, kind, json.dumps(payload, ensure_ascii=False), "",
         agent_output_id, now_iso()))
    conn.commit()
    return cur.lastrowid


def get_pending_op(op_id: int) -> dict | None:
    r = get_conn().execute("SELECT * FROM pending_ops WHERE id=?",
                           (op_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["payload"] = json.loads(d["payload"] or "{}")
    d["before_snapshot"] = json.loads(d["before_snapshot"] or "{}")
    return d


def list_pending_ops(user_id: int, status: str | None = None) -> list[dict]:
    q = "SELECT * FROM pending_ops WHERE user_id=?"
    args: list = [user_id]
    if status:
        q += " AND status=?"
        args.append(status)
    return [dict(r) for r in get_conn().execute(q + " ORDER BY id DESC", args)]


def set_pending_op(op_id: int, status: str, before_snapshot: dict | None = None):
    fields = {"status": status, "applied_at": now_iso()}
    if before_snapshot is not None:
        fields["before_snapshot"] = json.dumps(before_snapshot, ensure_ascii=False)
    cols = ", ".join(f"{k}=?" for k in fields)
    get_conn().execute(f"UPDATE pending_ops SET {cols} WHERE id=?",
                       list(fields.values()) + [op_id])
    get_conn().commit()


# ---------- 分维度量化（睡眠/精力/专注/压力 · 实际层） ----------

def add_metric(user_id: int, date: str, dimension: str, value: float | None,
               source: str = "self_report", kind: str = "actual",
               note: str = "") -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO metrics(user_id,date,dimension,value,source,kind,note,created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (user_id, date, dimension, value, source, kind, note, now_iso()))
    conn.commit()
    return cur.lastrowid


def list_metrics(user_id: int, date: str | None = None,
                 dimension: str | None = None) -> list[dict]:
    q = "SELECT * FROM metrics WHERE user_id=?"
    args: list = [user_id]
    if date:
        q += " AND date=?"
        args.append(date)
    if dimension:
        q += " AND dimension=?"
        args.append(dimension)
    q += " ORDER BY date DESC, id DESC"
    return [dict(r) for r in get_conn().execute(q, args)]
