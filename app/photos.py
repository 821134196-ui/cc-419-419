# -*- coding: utf-8 -*-
"""本地照片：零依赖生成 SVG 占位照片（演示数据用）。

真实使用时可替换 data/photos 下的文件；系统只认路径。
封面统一 4:3，卡片按统一比例裁切展示。
"""
from __future__ import annotations

from pathlib import Path

ROSE = "#B76E79"
ROSE_DARK = "#8E4A54"
INK = "#1A1A1A"
GRAY = "#F2F0EF"
WHITE = "#FFFFFF"
IVORY = "#FBF8F4"

W, H = 800, 600  # 统一封面比例 4:3


def _frame(title: str, subtitle: str, body: str, bg: str = GRAY) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <rect width="{W}" height="{H}" fill="{bg}"/>
  <rect x="18" y="18" width="{W-36}" height="{H-36}" fill="none" stroke="{ROSE}" stroke-width="2"/>
  {body}
  <text x="40" y="{H-58}" font-family="Georgia,serif" font-size="30" fill="{INK}">{title}</text>
  <text x="40" y="{H-28}" font-family="Arial,sans-serif" font-size="18" fill="{ROSE_DARK}">{subtitle}</text>
</svg>"""


def gown_svg(code: str, name: str, silhouette: str) -> str:
    """礼服封面：简约线稿裙身，玫瑰红点缀。silhouette 决定裙型。"""
    cx = 400
    if silhouette == "mermaid":  # 鱼尾
        skirt = f"M{cx-70},250 C{cx-40},330 {cx-60},430 {cx-150},500 L{cx+150},500 C{cx+60},430 {cx+40},330 {cx+70},250 Z"
    elif silhouette == "aline":  # A 字
        skirt = f"M{cx-70},250 L{cx-185},500 L{cx+185},500 L{cx+70},250 Z"
    elif silhouette == "qunagua":  # 秀禾
        skirt = f"M{cx-95},235 L{cx-160},505 L{cx+160},505 L{cx+95},235 Z"
    else:  # train 拖尾（默认）
        skirt = f"M{cx-70},250 L{cx-250},505 L{cx+250},505 L{cx+70},250 Z"
    gown_fill = IVORY if silhouette != "qunagua" else INK
    gown_stroke = INK if silhouette != "qunagua" else ROSE
    deco_color = ROSE if silhouette != "qunagua" else ROSE
    body = f"""
  <ellipse cx="{cx}" cy="150" rx="34" ry="42" fill="{gown_fill}" stroke="{gown_stroke}" stroke-width="3"/>
  <path d="M{cx-58},196 L{cx+58},196 L{cx+70},250 L{cx-70},250 Z" fill="{gown_fill}" stroke="{gown_stroke}" stroke-width="3"/>
  <path d="{skirt}" fill="{gown_fill}" stroke="{gown_stroke}" stroke-width="3"/>
  <path d="M{cx-60},205 Q{cx} {235 if silhouette!='qunagua' else 250} {cx+60},205" fill="none" stroke="{deco_color}" stroke-width="3"/>
  <circle cx="{cx}" cy="214" r="6" fill="{deco_color}"/>
  <path d="M{cx-120},330 Q{cx} 360 {cx+120},330" fill="none" stroke="{deco_color}" stroke-width="2" stroke-dasharray="8 8"/>
"""
    return _frame(f"{code} · {name}",
                  {"mermaid": "鱼尾款", "aline": "A 字款",
                   "train": "拖尾款", "qunagua": "秀禾款"}.get(silhouette, ""),
                  body)


def accessory_svg(code: str, name: str, pieces: list[str]) -> str:
    chips = ""
    for i, p in enumerate(pieces[:6]):
        x = 290 + (i % 3) * 170
        y = 210 + (i // 3) * 120
        chips += (f'<rect x="{x}" y="{y}" width="140" height="86" rx="10" '
                  f'fill="{WHITE}" stroke="{ROSE}" stroke-width="2"/>'
                  f'<text x="{x+70}" y="{y+50}" text-anchor="middle" '
                  f'font-family="Arial,sans-serif" font-size="20" fill="{INK}">{p}</text>')
    body = f"""
  <circle cx="120" cy="150" r="46" fill="none" stroke="{ROSE}" stroke-width="4"/>
  <path d="M92,150 L114,172 L152,126" fill="none" stroke="{ROSE_DARK}" stroke-width="6"/>
  {chips}
"""
    return _frame(f"{code} · {name}", "配件套装 · 按编号绑定", body)


def detail_svg(label: str, note: str, mark: str = "") -> str:
    """细节/污渍/破损照片：可选玫瑰红标记圈。"""
    mark_svg = ""
    if mark:
        mark_svg = (f'<ellipse cx="400" cy="300" rx="150" ry="90" '
                    f'fill="none" stroke="{ROSE}" stroke-width="5" stroke-dasharray="12 8"/>'
                    f'<text x="400" y="395" text-anchor="middle" '
                    f'font-family="Arial,sans-serif" font-size="26" fill="{ROSE_DARK}">{mark}</text>')
    body = f"""
  <path d="M250,200 L550,200 L590,420 L210,420 Z" fill="{IVORY}" stroke="{INK}" stroke-width="2"/>
  {mark_svg}
"""
    return _frame(label, note, body)


def avatar_svg(code: str, name: str) -> str:
    initial = name[0] if name else "客"
    body = f"""
  <circle cx="400" cy="270" r="150" fill="{WHITE}" stroke="{ROSE}" stroke-width="4"/>
  <circle cx="400" cy="220" r="55" fill="{ROSE}"/>
  <path d="M300,380 Q400 290 500,380" fill="{ROSE}"/>
  <text x="400" y="242" text-anchor="middle" font-family="Georgia,serif" font-size="52" fill="{WHITE}">{initial}</text>
"""
    return _frame(code, f"{name} · 演示客户", body)


def write_svg(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)
