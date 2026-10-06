#!/usr/bin/env python3
"""生成四角花边 SVG（穆夏风格：鞭梢曲线 + 叶 + 花苞）。
只跑一次：python3 _gen.py
"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))

# 花边主体（左上角 TL 的绘制，其余三角用 transform 镜像）
BODY = '''  <g fill="none" stroke="#C89B5A" stroke-linecap="round">
    <path d="M6 74 C6 34 32 8 74 6" stroke-width="1.7"/>
    <path d="M13 74 C13 40 36 15 72 13" stroke-width="1.05" opacity=".55"/>
    <path d="M6 74 C8 46 22 28 46 18" stroke-width=".9" opacity=".35"/>
  </g>
  <g fill="#C89B5A">
    <path d="M22 50 c-5 -7 -1 -16 7 -19 c4 8 -1 17 -7 19 Z" opacity=".5"/>
    <path d="M34 38 c-5 -7 -1 -15 7 -18 c4 7 -1 16 -7 18 Z" opacity=".4"/>
    <path d="M48 26 c-4 -6 -1 -12 6 -15 c3 6 -1 13 -6 15 Z" opacity=".3"/>
  </g>
  <circle cx="71" cy="10" r="4.4" fill="#853C1E"/>
  <circle cx="71" cy="10" r="2.1" fill="#E0B15D"/>
  <g fill="none" stroke="#C89B5A" stroke-width=".9" opacity=".55" stroke-linecap="round">
    <path d="M58 16 c6 -2 9 -7 10 -12"/>
    <path d="M60 23 c5 -1 8 -5 9 -9"/>
  </g>'''

# 四个角的镜像变换（绕中心 40,40）
CORNERS = {
    "corner-tl": None,
    "corner-tr": '  <g transform="translate(80,0) scale(-1,1)">\n' + BODY + '\n  </g>',
    "corner-bl": '  <g transform="translate(0,80) scale(1,-1)">\n' + BODY + '\n  </g>',
    "corner-br": '  <g transform="translate(80,80) scale(-1,-1)">\n' + BODY + '\n  </g>',
}

for name, inner in CORNERS.items():
    inner = BODY if inner is None else inner
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80" '
           'width="80" height="80">\n' + inner + '\n</svg>\n')
    with open(os.path.join(BASE, name + ".svg"), "w") as f:
        f.write(svg)
    print("wrote", name + ".svg")
