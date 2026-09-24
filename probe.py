"""
校招雷达·爬虫探针（先验证 3 个源能抓到）
- 河海大学就业网 job.hhu.edu.cn  （A 河海校友）
- 河北科技大学 job.hebust.edu.cn （B 河北科大校友）
- 北京科技大学 job.ustb.edu.cn   （金属/钢铁重点）

目的：确认 HTML 结构能解析、关键词能命中。
"""
import urllib.request
import re
import ssl
from datetime import date

# 关键词集
KEYWORDS_A = [  # A 河海给排水
    "给排水", "市政工程", "水务", "水处理", "环境工程",
    "给排水科学与工程", "建排", "中建", "中核", "中冶",
    "电建", "建筑安装", "机电安装",
]
KEYWORDS_B = [  # B 河北科大金属材料
    "金属材料", "材料成型", "冶金", "钢铁", "材料加工",
    "热处理", "铸造", "焊接", "无损检测", "宝武", "河钢",
    "首钢", "中铝", "一重", "中色", "材料工程",
]

SOURCES = [
    ("河海大学就业网", "https://job.hhu.edu.cn/teachinOnline/index?category=2"),
    ("河北科技大学就业网", "https://job.hebust.edu.cn/teachinOnline/index?category=2"),
    ("北京科技大学就业网", "https://job.ustb.edu.cn/f/career/jobhunting"),
]


def fetch(url: str, timeout: int = 15) -> str:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read().decode("utf-8", errors="replace")


def match(text: str, keywords: list) -> list:
    return [k for k in keywords if k in text]


def probe():
    print(f"=== 探针 {date.today()} ===\n")
    for name, url in SOURCES:
        try:
            html = fetch(url)
            a_hit = match(html, KEYWORDS_A)
            b_hit = match(html, KEYWORDS_B)
            print(f"✓ {name}")
            print(f"  URL: {url}")
            print(f"  HTML 长度: {len(html)}")
            print(f"  A 命中: {a_hit if a_hit else '(无)'}")
            print(f"  B 命中: {b_hit if b_hit else '(无)'}")
            print()
        except Exception as e:
            print(f"✗ {name}: {type(e).__name__}: {e}\n")


if __name__ == "__main__":
    probe()