"""
pushplus 微信推送 - Codex 额度重置通知专用
- 调用 pushplus.plus/send 接口
- token 读取顺序：
  1) 环境变量 PUSHPLUS_TOKEN / PUSH_PLUS_TOKEN
  2) 同目录 pushplus_token.txt（聪哥手工写入，权限锁 600）
- 失败抛异常，让调用方决定是否回退 Agent Mail
"""
import os
import sys
import json
import urllib.request
import urllib.error


PUSHPLUS_URL = "https://www.pushplus.plus/send"


def _resolve_token() -> str:
    for key in ("PUSHPLUS_TOKEN", "PUSH_PLUS_TOKEN"):
        v = os.environ.get(key)
        if v:
            return v.strip()
    here = os.path.dirname(os.path.abspath(__file__))
    f = os.path.join(here, "pushplus_token.txt")
    if os.path.exists(f):
        return open(f, encoding="utf-8").read().strip()
    raise RuntimeError(
        "pushplus token 未配置：在 ~/.workbuddy/automations/"
        "automation-1786404713606/pushplus_token.txt 写入 token，"
        "或设置环境变量 PUSHPLUS_TOKEN"
    )


def send(title: str, content: str, template: str = "markdown") -> dict:
    """推一条到 pushplus。返回 pushplus 原始响应 dict。"""
    tk = _resolve_token()
    payload = {
        "token": tk,
        "title": title[:100],
        "content": content,
        "template": template,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        PUSHPLUS_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"pushplus HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}"
        )
    except urllib.error.URLError as e:
        raise RuntimeError(f"pushplus URL error: {e.reason}")
    except Exception as e:
        raise RuntimeError(f"pushplus unknown error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    # CLI: python pushplus_notify.py "<title>" "<content>"
    if len(sys.argv) < 3:
        print(
            json.dumps({"ok": False, "error": "usage: pushplus_notify.py <title> <content>"}),
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        data = send(sys.argv[1], sys.argv[2])
        ok = data.get("code") in (200, "200")
        print(json.dumps({"ok": ok, "response": data}, ensure_ascii=False))
        sys.exit(0 if ok else 1)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)