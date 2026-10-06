"""成长卡牌 · 牌组种子（16 张主牌）。

定位：成长原型 / 反思卡，塔罗的形、成长的魂——抽到给反思、不给预测。
图片由用户用生图模型生成后放入 static/cards/，命名 card-00.jpg … card-15.jpg。
"""

CARDS = [
    {"code": "0",  "name": "启程者", "keywords": "出发 · 好奇 · 未知",
     "meaning": "不必等万事俱备，先迈出第一步。"},
    {"code": "1",  "name": "守望者", "keywords": "内省 · 直觉 · 静默",
     "meaning": "答案有时不在喧闹里，在安静里。"},
    {"code": "2",  "name": "播种者", "keywords": "积累 · 耐心 · 耕耘",
     "meaning": "今天的积累，是明天看不见却正在长出的根。"},
    {"code": "3",  "name": "燃灯者", "keywords": "灵感 · 点亮 · 分享",
     "meaning": "你点亮的，也会照亮别人。"},
    {"code": "4",  "name": "筑巢者", "keywords": "秩序 · 安全感 · 安顿",
     "meaning": "先照顾好自己，才能稳妥地照顾重要的事。"},
    {"code": "5",  "name": "试炼者", "keywords": "勇气 · 面对 · 突破",
     "meaning": "害怕是正常的，勇气是带着害怕往前。"},
    {"code": "6",  "name": "连接者", "keywords": "倾听 · 关系 · 同理",
     "meaning": "被听见，比被说服更让人安心。"},
    {"code": "7",  "name": "驯浪者", "keywords": "情绪 · 压力 · 驾驭",
     "meaning": "情绪不是敌人，是浪——学会与它共处。"},
    {"code": "8",  "name": "破茧者", "keywords": "蜕变 · 成长 · 新生",
     "meaning": "此刻的不舒服，可能是正在长出新翅膀。"},
    {"code": "9",  "name": "平衡者", "keywords": "取舍 · 节奏 · 协调",
     "meaning": "不是全部都要，而是知道此刻什么最重要。"},
    {"code": "10", "name": "回望者", "keywords": "复盘 · 沉淀 · 感恩",
     "meaning": "走过的弯路，回头都是路标。"},
    {"code": "11", "name": "修补者", "keywords": "修复 · 和解 · 温柔",
     "meaning": "裂痕不是缺陷，是可以进光的地方。"},
    {"code": "12", "name": "举火者", "keywords": "坚持 · 传递 · 信念",
     "meaning": "再坚持一下，你的火会带别人走出黑暗。"},
    {"code": "13", "name": "星辰者", "keywords": "愿景 · 方向 · 辽阔",
     "meaning": "抬头看远一点，就不会困在眼前。"},
    {"code": "14", "name": "归心者", "keywords": "接纳 · 自洽 · 完整",
     "meaning": "你已经足够，不必再证明什么。"},
    {"code": "15", "name": "同行者", "keywords": "陪伴 · 互助 · 温暖",
     "meaning": "你不必一个人扛，开口，就有人陪。"},
]


def img_for(code: str) -> str:
    return f"/static/cards/card-{int(code):02d}.jpg"
