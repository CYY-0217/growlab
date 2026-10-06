"""DeepSeek 配置自检：读取 .env，真调一次，报告结果。"""
import os
import sys

try:
    from dotenv import load_dotenv
    from openai import OpenAI
except ImportError as e:
    print("依赖缺失，先装：./.venv/bin/pip install -i https://pypi.org/simple -r requirements.txt")
    sys.exit(1)

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

key = os.getenv("DEEPSEEK_API_KEY", "")
base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

if not key or "你的真实key" in key or key.startswith("sk-xxx"):
    print("❌ 未填入真实 key。请打开 .env，把 DEEPSEEK_API_KEY= 后面改成你的真实 key。")
    sys.exit(1)

print(f"配置读取：key={key[:6]}...{key[-4:]}  model={model}  base={base}")

client = OpenAI(api_key=key, base_url=base)
try:
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "只回复两个字：OK"}],
        max_tokens=10,
    )
    print("模型回复:", r.choices[0].message.content)
    print("✅ 配置成功，可以开工。")
except Exception as e:
    msg = str(e)
    print("❌ 调用失败：", msg)
    if "401" in msg or "auth" in msg.lower() or "invalid" in msg.lower():
        print("   → 大概率是 key 不对，检查 DEEPSEEK_API_KEY 是否填错/复制少了字符。")
    elif "model" in msg.lower() and ("not found" in msg.lower() or "does not exist" in msg.lower()):
        print("   → 模型名不对，去 platform.deepseek.com 看真实模型 id，改 .env 里的 DEEPSEEK_MODEL。")
    elif "insufficient" in msg.lower() or "balance" in msg.lower():
        print("   → 账户余额不足，去充值。")
    sys.exit(1)
