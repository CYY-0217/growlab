"""一次性种子：4 位学习者 + 真实使用记录（10-01 ~ 10-03）。

只跑一次：./.venv/bin/python seed_demo_data.py
数据来源：用户 2026-10-03 提供的真实使用记录，如实导入、不伪造对话时间线。
"""
import database


def main():
    conn = database.get_conn()
    # 清空旧用户（agent_outputs 无 CASCADE，先清；其余表级联清理）
    conn.execute("DELETE FROM agent_outputs")
    conn.execute("DELETE FROM users")
    conn.commit()

    # 1. 四位学习者
    u_xiaoyun = database.add_user("小韵", "self", "想早睡，但总被朋友深夜喊打游戏")
    u_ache = database.add_user("阿澈", "balance", "想兼顾健身和学习，但两者总互相挤占")
    u_zhou = database.add_user("周舟", "swim", "校队周二四固定训练，训练日怎么调开学习")
    u_shan = database.add_user("小闪", "think", "点子多、启动难，项目不知从哪拆起")

    # 2. 目标
    g_yun_sleep = database.add_goal(u_xiaoyun, "早睡（12点前关机）", 4, 0, 7, "health")
    g_yun_fr = database.add_goal(u_xiaoyun, "法语学习（多邻国+背词）", 3, 25, 7, "study")
    g_che_fit = database.add_goal(u_ache, "健身", 4, 60, 4, "health")
    g_che_study = database.add_goal(u_ache, "自习/学习", 4, 50, 7, "study")
    g_zhou_train = database.add_goal(u_zhou, "校队训练", 5, 90, 3, "sport")
    g_zhou_study = database.add_goal(u_zhou, "学习（作业）", 4, 50, 7, "study")
    g_shan_idea = database.add_goal(u_shan, "每日记一个点子", 3, 10, 7, "habit")
    g_shan_proj = database.add_goal(u_shan, "AI生日提醒项目", 4, 40, 5, "project")

    # 3. 每日打卡（daily_entries）
    database.upsert_daily_entry(
        u_xiaoyun, "2026-10-01", raw_text="多邻国+背法语",
        checkins={str(g_yun_fr): 1.0},
        note="国庆回家也没断卡，法语听写错3个词，全是性数配合")
    database.upsert_daily_entry(
        u_shan, "2026-10-02", raw_text="每天记一个点子",
        checkins={str(g_shan_idea): 1.0},
        note="连记3天了；点子不写下来，第二天真的会忘")
    database.upsert_daily_entry(
        u_zhou, "2026-10-03", raw_text="训练日时间调节",
        checkins={str(g_zhou_study): 1.0},
        note="训练日把背单词挪到地铁通勤，整块时间留给作业")

    # 4. 探索（explorations）
    database.add_exploration(
        u_xiaoyun, "为什么总是熬夜",
        [{"name": "把手机留在客厅", "why": "不是睡不着，是没人催就不想下线", "cost": "低"}])

    # 5. 想法拆解（agent_outputs · idea）
    oid = database.save_agent_output(
        u_shan, "idea", "给社团做AI生日提醒",
        "拆成5步：先定触发→再拉成员生日→再生成文案→再定时推送→最后留手动确认。第一步今晚就能动，先写了10行原型。")
    database.decide_agent_output(oid, True)

    # 6. 实验（experiments）
    e1 = database.create_experiment(
        u_ache, source_scene="健身撞上自习",
        hypothesis="健身后1小时做题更专注",
        action="把难题挪到健身后1小时",
        record_what="做题正确率/专注时长", review_date="2026-10-03")
    database.update_experiment(e1, outcome="验证成立，决定把难题挪到那个时段", status="done")
    e2 = database.create_experiment(
        u_zhou, source_scene="训练周复盘",
        hypothesis="提前把训练强度写进日历就不会崩",
        action="提前把训练强度写进日历",
        record_what="训练日是否如期完成", review_date="2026-10-03")
    database.update_experiment(e2, outcome="教练临时加练那天崩了，下次提前把强度写进日历", status="done")

    # 7. 成长档案（memory，情境剧场等——只记结果，不伪造对话时间线）
    database.add_memory(u_xiaoyun, "experience",
                        "情境剧场·拒绝深夜邀约：换了种说法，阿杰没伤感情，自己23:00准时下线",
                        "情境剧场·拒绝深夜邀约")
    database.add_memory(u_ache, "experience",
                        "情境剧场·健身撞上自习：学会先锁「不可移动块」，训练和学习第一次都保住了",
                        "情境剧场·健身撞上自习")
    database.add_memory(u_shan, "experience",
                        "情境剧场·给朋友讲清「这个点子难在哪」：第一次能把依赖讲明白，朋友把第2步认领走了",
                        "情境剧场·讲清点子难在哪")

    # 8. 宠物/卡牌奖励（把记录折算成经验，让萌宠/卡牌有历史感）
    database.pet_reward(u_xiaoyun, 15, "study", "每日打卡·多邻国+背法语")
    database.pet_reward(u_xiaoyun, 5, "explore", "探索·为什么总是熬夜")
    database.pet_reward(u_xiaoyun, 3, "note", "情境剧场·拒绝深夜邀约")
    database.pet_reward(u_ache, 15, "lab", "实验·晚间精力高峰测试")
    database.pet_reward(u_ache, 3, "note", "情境剧场·健身撞上自习")
    database.pet_reward(u_zhou, 15, "study", "训练日时间调节")
    database.pet_reward(u_zhou, 15, "lab", "复盘·训练周")
    database.pet_reward(u_shan, 15, "study", "习惯养成·每天记一个点子")
    database.pet_reward(u_shan, 3, "note", "情境剧场·讲清点子难在哪")

    print("✅ 种子完成：4 位学习者 + 目标 + 记录 + 宠物/卡牌奖励")


if __name__ == "__main__":
    main()
