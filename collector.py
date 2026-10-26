# -*- coding: utf-8 -*-
"""
国央企校招雷达·真采集器 v1
======================================================================
设计来源（三方兼收）：
1. 豆包工作会话 38443870336914434 —— 方法论层
   · 七项准入：单位+岗位名+届别+学历+专业+地点+投递入口，必须同一证据同时满足
   · 分级输出：可直接投递 / 待钻取 / 条件式线索 / 排除，每级写明缺失字段
   · 每条必带可核验来源 URL
   · 主动剔除"标题写2027实为旧届"的脏数据
2. AIHOT 开源项目 —— 工程层
   · 行业 KnowHow 全部外置knowledge/candidates.yaml，代码零改动
   · 评分 + 分级门槛（thresholds），简单、可解释、可审计
   · published_at（信源声称）与 discovered_at（我方发现）分开存
3. 旧 probe.py 的教训 —— 反面教材
   · 它只 curl 首页就宣布"验证通过"，实际那些页面是 JS 渲染，静态抓不到任何岗位
   · 本脚本的"验证"必须是「数据字段完整性校验」，不是「HTTP 200」

关键技术事实（已实测，勿轻改）：
- 高校就业网（job.hhu/ustb/hebust）与 国聘网页面 均为 JS 动态渲染，
  静态 curl 只能拿到 1KB 左右空壳，HTTP 200 是假成功。
- 真实数据接口是 POST https://gp-api.iguopin.com/api/jobs/v1/recom-job
  body: {"search":{"page":1,"page_size":20,"keyword":"给排水"},
         "recom":{"update_time":true,"company_nature":true,"hot_job":true}}
  直连可用，返回结构化 JSON，含截止日期/学历/专业/地区/单位性质/任职要求全文。
- 上述字段天然满足七项准入，无需从 HTML 猜。
"""
import os
import re
import sys
import json
import time
import hashlib
import argparse
import datetime
import urllib.request
import urllib.error
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
KNOWLEDGE = HERE / "knowledge" / "candidates.yaml"
LEDGER = HERE / "data" / "ledger.json"
RAW_DIR = HERE / "data" / "raw"
LOG = HERE / "data" / "collect.log"

API = "https://gp-api.iguopin.com/api/jobs/v1/recom-job"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
PUSHPLUS = "https://www.pushplus.plus/send"

# 国聘 job_id -> 可访问详情页
DETAIL_PAGE = "https://www.iguopin.com/jobs/{job_id}.html"


def log(msg: str) -> None:
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------- 知识加载（外置，改配置不动代码） ----------------
def load_knowledge() -> dict:
    with open(KNOWLEDGE, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------- 采集 ----------------
def api_search(keyword: str, page: int = 1, size: int = 20, retries: int = 3) -> dict:
    """直连国聘搜索 API。失败重试，最终失败抛异常——绝不静默返回空。"""
    payload = json.dumps({
        "search": {"page": page, "page_size": size, "keyword": keyword},
        "recom": {"update_time": True, "company_nature": True, "hot_job": True},
    }).encode("utf-8")
    req = urllib.request.Request(
        API, data=payload, method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": UA,
            "Origin": "https://www.iguopin.com",
            "Referer": "https://www.iguopin.com/",
        },
    )
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as e:                      # noqa: BLE001
            last = e
            if i < retries - 1:
                time.sleep(2 * (i + 1))
    raise RuntimeError(f"国聘API失败 keyword={keyword} page={page}: {last}")


def fetch_all(keywords: list, pages: int = 2, size: int = 20) -> list:
    """按关键词矩阵多页抓取，job_id 去重。"""
    seen, out = set(), []
    for kw in keywords:
        for pg in range(1, pages + 1):
            try:
                d = api_search(kw, pg, size)
            except RuntimeError as e:
                log(f"  [抓取失败] {e}")
                continue
            data = d.get("data") or {}
            lst = data.get("list") or []
            if not lst:
                break
            new = 0
            for it in lst:
                jid = str(it.get("job_id"))
                if jid in seen:
                    continue
                seen.add(jid)
                it["_kw"] = kw
                out.append(it)
                new += 1
            log(f"  关键词[{kw}] 第{pg}页 → 本页{len(lst)}条，新增{new}条")
            if len(lst) < size:
                break
    return out


# ---------------- 字段抽取与规范化 ----------------
def norm_text(s) -> str:
    if not s:
        return ""
    if isinstance(s, (list, tuple)):
        return " ".join(str(x) for x in s)
    return str(s)


def extract_regions(it: dict) -> list:
    out = []
    for d in (it.get("district_list") or []):
        for k in ("area_cn", "province", "address"):
            v = d.get(k)
            if v and v not in out:
                out.append(str(v))
    return out


def has_any(text: str, kws: list) -> list:
    return [k for k in (kws or []) if k and k in text]


# ---------------- 评分与七项准入 ----------------
def score_job(it: dict, cand_key: str, cfg: dict, today: str) -> dict:
    """借鉴 aihot：可解释的加减分法 + 分级门槛。每项加分都写明理由，便于审计。"""
    c = cfg["candidates"][cand_key]
    th = cfg["thresholds"]
    reasons, score = [], 0

    blob = " ".join([
        norm_text(it.get("job_name")),
        norm_text(it.get("major_cn")),
        norm_text(it.get("contents")),
        norm_text(it.get("company_name")),
    ])

    # 1) 专业匹配（强/中信号分级）
    strong = has_any(blob, c.get("major_strong", []))
    mid = has_any(blob, c.get("major_mid", []))
    if strong:
        score += th["strong_major_bonus"]
        reasons.append(f"强专业匹配({'/'.join(strong[:2])}) +{th['strong_major_bonus']}")
    elif mid:
        score += th["mid_major_bonus"]
        reasons.append(f"中专业匹配({'/'.join(mid[:2])}) +{th['mid_major_bonus']}")

    # 2) 单位性质
    nature = norm_text(it.get("company_info", {}).get("nature_cn") if
                       isinstance(it.get("company_info"), dict) else "")
    nature = nature or norm_text(it.get("nature_cn"))
    if has_any(nature, c.get("unit_keywords", [])) or "国有" in nature:
        score += th["nature_state_bonus"]
        reasons.append(f"单位性质[{nature}] +{th['nature_state_bonus']}")
    elif has_any(nature, c.get("excluded_nature", [])):
        score += th["non_state_penalty"]
        reasons.append(f"非国有[{nature}] {th['non_state_penalty']}")

    # 3) 地区
    regions = extract_regions(it)
    rblob = " ".join(regions)
    if has_any(rblob, c.get("location_prefer", [])):
        if has_any(rblob, ["天津"]):
            score += th["location_perfect_bonus"]
            reasons.append(f"天津[{','.join(regions[:2])}] +{th['location_perfect_bonus']}")
        else:
            score += th["location_north_bonus"]
            reasons.append(f"京津冀/北方[{','.join(regions[:2])}] +{th['location_north_bonus']}")
    if has_any(rblob + blob, c.get("location_exclude_hint", [])):
        score -= 30
        reasons.append("疑似海上/野外/偏远 -30")

    # 4) 学历（关键教训：结构化 education_cn 字段可能为空，而真实要求藏在正文里。
#    实测抓到"学历字段空、正文写'2027届硕士及以上'"的岗位，
#    只信字段会把它误判为可投。因此字段与正文必须交叉验证，取更严格者。）
    edu_field = norm_text(it.get("education_cn"))
    body = norm_text(it.get("contents"))
    edu = edu_field
    # 正文里显式要求"硕士及以上/博士及以上"→ 一律判为不符（本科生）
    if re.search(r"硕士及以上|研究生及以上|博士及以上|硕士以上|研究生以上", body):
        edu = "硕士(正文要求)"
    if edu_field in ("博士", "硕士") or edu.startswith("硕士") or edu.startswith("博士"):
        score += th["senior_only_penalty"]
        reasons.append(f"仅招[{edu}] {th['senior_only_penalty']}")
    elif edu in ("本科", "大专", "专科", "不限", ""):
        reasons.append(f"学历[{edu or '字段空·正文未限本科以上'}] 本科可报")
    # 正文若明写仅限硕士/博士招聘
    if re.search(r"仅限硕士|仅招硕士|限硕士及以上|面向硕士", body):
        edu = "硕士(正文仅限)"
        score += th["senior_only_penalty"]

    # 4b) 经验门槛（社招陷阱：应届生字段与正文可能不一致）
    exp = norm_text(it.get("experience_cn"))
    if re.search(r"\d+\s*年(以上|及以上)?(工作)?经验|经验\s*\d+\s*年", body) and \
            not re.search(r"应届|实习|无经验|经验不限", body):
        score -= 35
        reasons.append("⚠正文要求工作经验，疑似社招 -35")
    elif exp in ("应届生", "经验不限", "在校生", "实习"):
        reasons.append(f"经验[{exp}] 校招ok")

    # 5) 届别（硬闸：只认明确含 2027 的。实测国聘仅约 12% 岗位明确写届别，
    #    因此"应届生"不等于"2027届"，必须区分，否则会把社招/往届混进来）
    blob_year = norm_text(it.get("contents")) + norm_text(it.get("job_name")) \
        + norm_text(it.get("category_cn")) + norm_text(it.get("department_cn"))
    grad = it.get("is_graduates")
    year_hit = bool(re.search(r"2027|27届|二七届", blob_year))
    old_year = bool(re.search(r"202[0-6]届|20(2[0-6])年度校招|往届|届已满", blob_year))
    if year_hit:
        reasons.append("届别命中2027✓")
    elif old_year:
        reasons.append("⚠命中旧届(2020-2026)表述，倾向不符")
    elif grad:
        reasons.append("应届生但未标届数(须二次确认)")

    # 6) 截止日期
    end = norm_text(it.get("end_time"))[:10]
    deadline_ok, days_left = False, None
    if end and end != "None":
        try:
            e = datetime.date.fromisoformat(end)
            d0 = datetime.date.fromisoformat(today)
            days_left = (e - d0).days
            if days_left >= 0:
                deadline_ok = True
                if days_left <= 30:
                    score += th["deadline_near_bonus"]
                    reasons.append(f"{days_left}天截止 +{th['deadline_near_bonus']}")
            else:
                score -= 40
                reasons.append(f"已过期({end}) -40")
        except Exception:
            pass
    else:
        score += th["no_deadline_penalty"]
        reasons.append(f"无截止日期 {th['no_deadline_penalty']}")

    # 七项准入逐项判定
    # 「学历」必须确认本科可报：字段或正文任一确认即可，但"硕士及以上"一律排除
    edu_ok = edu in ("本科", "大专", "专科", "不限", "")
    # 岗位名排雷：纯管理/商务/销售岗对工科生无意义
    mgmt_kw = ["商务", "销售", "总监", "经理（", "客户经理", "销售总监",
               "总经理", "副总", "董事长", "商务经理", "投资管理", "经营管理",
               "（经营）", "(经营)", "投资岗", "财务", "人力资源", "行政管理"]
    is_mgmt = any(k in norm_text(it.get("job_name")) for k in mgmt_kw)
    gate = {
        "单位": bool(it.get("company_name")),
        "岗位名": bool(it.get("job_name")),
        "届别": year_hit,
        "学历": edu_ok,
        "专业": bool(strong or mid),
        "地点": bool(has_any(rblob, c.get("location_prefer", []))),
        "投递入口": bool(it.get("job_id")),  # 国聘均可在站内投递
    }
    passed = sum(1 for v in gate.values() if v)

    # 分级：届别是硬闸，不允许"高分低届别"混进可投/待钻取
    # （豆包教训：它把"标题写2027实为2023旧宣讲页"当2027处理，翻车）
    if not year_hit:
        level = "noise" if score < th["drill_min_score"] else "lead"
    elif (score >= th["ready_min_score"] and passed == 7
          and edu_ok and not is_mgmt):
        level = "ready"
    elif score >= th["drill_min_score"] and passed >= 4 and not is_mgmt:
        level = "drill"
    elif is_mgmt and score >= th["drill_min_score"] and passed >= 5:
        level = "lead"      # 管理/商务岗单列，不占可投名额
    else:
        level = "noise"

    return {
        "level": level,
        "score": score,
        "gate": gate,
        "gate_passed": passed,
        "reasons": reasons,
        "regions": regions,
        "deadline": end,
        "days_left": days_left,
        "education": edu,
        "major_cn": norm_text(it.get("major_cn")),
        "nature": nature,
    }


# ---------------- 账本（增量去重） ----------------
def load_ledger() -> dict:
    """账本加载。云端（GitHub Actions）每次是全新容器，账本会丢，
    因此支持用环境变量 LEDGER_JSON 注入上一次的账本快照（配合 workflow 的
    actions/cache 或 artifact 持久化）。本地则直接读文件。"""
    env = os.environ.get("LEDGER_JSON")
    if env:
        try:
            return json.loads(env)
        except Exception:
            log("LEDGER_JSON 解析失败，回退文件账本")
    if LEDGER.exists():
        try:
            return json.loads(LEDGER.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_ledger(led: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(led, ensure_ascii=False, indent=2), encoding="utf-8")


def job_key(it: dict) -> str:
    raw = f"{it.get('company_name')}|{it.get('job_name')}|{it.get('job_id')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


# ---------------- 主流程 ----------------
def collect(dry_run: bool = False, pages: int = 2) -> dict:
    cfg = load_knowledge()
    today = datetime.date.today().isoformat()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    raw, seen_kw = [], set()
    for cand_key, kws in cfg["search_keywords"].items():
        for kw in kws:
            if kw in seen_kw:
                continue
            seen_kw.add(kw)
        log(f"[{cand_key}] 抓取关键词: {kws}")
        raw += fetch_all(kws, pages=pages)
    log(f"原始去重后总量: {len(raw)}")

    if not raw:
        raise RuntimeError("全部数据源抓取失败，0 条——判定为采集异常，拒绝产出报告")

    # 落原始档（可追溯）
    (RAW_DIR / f"raw_{today}.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    # 评分分级
    results = []
    for it in raw:
        jid = str(it.get("job_id"))
        for ck in cfg["candidates"]:
            sc = score_job(it, ck, cfg, today)
            if sc["level"] == "noise":
                continue
            results.append({
                "candidate": ck,
                "job_id": jid,
                "company": it.get("company_name"),
                "position": it.get("job_name"),
                "nature": sc["nature"],
                "education": sc["education"],
                "major": sc["major_cn"],
                "regions": sc["regions"],
                "deadline": sc["deadline"],
                "days_left": sc["days_left"],
                "score": sc["score"],
                "level": sc["level"],
                "gate": sc["gate"],
                "gate_passed": sc["gate_passed"],
                "reasons": sc["reasons"],
                "url": DETAIL_PAGE.format(job_id=jid),
                "contents_head": norm_text(it.get("contents"))[:400],
                "discovered_at": today,
                "published_at": norm_text(it.get("start_time"))[:10],
            })

    results.sort(key=lambda x: (-x["score"], x.get("days_left") or 999))
    log(f"分级完成: 可投{sum(1 for r in results if r['level']=='ready')} "
        f"待钻取{sum(1 for r in results if r['level']=='drill')} "
        f"线索{sum(1 for r in results if r['level']=='lead')} "
        f"丢弃{len(raw)-len(results)}")

    # 账本增量
    led = load_ledger()
    new_cnt = 0
    for r in results:
        k = job_key(r)
        if k not in led:
            led[k] = {
                "candidate": r["candidate"], "company": r["company"],
                "position": r["position"], "url": r["url"], "level": r["level"],
                "score": r["score"], "first_seen": today, "status": "active",
                "published_at": r["published_at"],
            }
            new_cnt += 1
            r["is_new"] = True
        else:
            led[k]["last_seen"] = today
            led[k]["level"] = r["level"]
            r["is_new"] = False
    if not dry_run:
        save_ledger(led)
    log(f"账本更新: 新增{new_cnt}条，账本总量{len(led)}条")

    return {"date": today, "total_raw": len(raw), "results": results,
            "new_count": new_cnt, "ledger_total": len(led)}


# ---------------- 报告（借鉴豆包分级输出结构） ----------------
def build_report(data: dict) -> tuple:
    cfg = load_knowledge()
    today = data["date"]
    res = data["results"]
    cands = cfg["candidates"]

    title = f"校招雷达·晨报 {today}（新增{data['new_count']}·样本{data['total_raw']}）"
    md = [f"# {title}\n",
          f"> 数据源：国聘网真实搜索接口（结构化字段）｜采集条目 {data['total_raw']}｜"
          f"账本累计 {data['ledger_total']}\n",
          "> 分级依据：七项准入（单位/岗位/届别/学历/专业/地点/投递入口）"
          "与可解释评分；**不编造任何邮箱电话，缺证据即降级**。\n"]

    for ck in ("A", "B"):
        c = cands[ck]
        sub = [r for r in res if r["candidate"] == ck]
        if not sub:
            md.append(f"\n## 👤 {ck} · {c['name']}（{c['major']}）\n今日无达标线索。\n")
            continue
        md.append(f"\n## 👤 {ck} · {c['name']}（{c['major']}）\n")

        for level, label, emoji in (("ready", "可直接投递", "✅"),
                                    ("drill", "待钻取（证据不全）", "🔍")):
            group = [r for r in sub if r["level"] == level]
            if not group:
                continue
            md.append(f"\n### {emoji} 【{label}】{len(group)} 条\n")
            for r in group:
                flag = "🆕" if r.get("is_new") else "·"
                md.append(f"\n{flag} **{r['company']}** — {r['position']}  `{r['score']}分`")
                md.append(f"- 单位性质：{r['nature'] or '未标注'}｜学历：{r['education'] or '未标注'}"
                          f"｜专业：{r['major'][:40]}")
                md.append(f"- 地点：{', '.join(r['regions'][:3]) or '未标注'}"
                          + (f"｜**{r['days_left']}天截止({r['deadline']})**"
                             if r.get("days_left") is not None else "｜截止：未标注"))
                miss = [k for k, v in r["gate"].items() if not v]
                md.append(f"- 七项准入：{r['gate_passed']}/7"
                          + (f"　缺：{'、'.join(miss)}" if miss else "　**全通过**"))
                md.append(f"- 评分依据：{'；'.join(r['reasons'][:4])}")
                if r["contents_head"]:
                    md.append(f"- 简章摘录：{r['contents_head'][:180]}…")
                md.append(f"- 来源：{r['url']}")
        if any(r["level"] == "drill" for r in sub):
            md.append("\n> 「待钻取」= 已确认存在该岗位，但证据链不完整，"
                      "**请勿直接投递**，需按缺失字段二次核实后再决策。\n")

        leads = [r for r in sub if r["level"] == "lead"]
        if leads:
            md.append(f"\n### ⚠️ 【条件式线索·届别未明】{len(leads)} 条\n")
            md.append("> 下列岗位专业/地区/单位性质匹配，但**简章未明确写 2027 届**，"
                      "仅可作参考。**投前必须向 HR 确认届别**，否则可能白投。\n")
            md.append("\n| 单位 | 岗位 | 性质 | 学历 | 地点 | 截止 | 分 |")
            md.append("|---|---|---|---|---|---|---|")
            for r in leads[:18]:
                md.append(f"| {str(r['company'])[:22]} | {str(r['position'])[:24]} "
                          f"| {r['nature'] or '?'} | {r['education'] or '?'} "
                          f"| {','.join(r['regions'][:2]) or '?'} "
                          f"| {r['deadline'] or '?'} | {r['score']} |")
            if len(leads) > 18:
                md.append(f"\n> 另有 {len(leads)-18} 条同类线索见原始档 "
                          f"`data/raw/raw_{data['date']}.json`")

    return title, "\n".join(md)


# ---------------- 推送 ----------------
def resolve_token() -> str:
    for k in ("PUSHPLUS_TOKEN", "PUSH_PLUS_TOKEN"):
        v = os.environ.get(k)
        if v:
            return v.strip()
    cands = [
        HERE / "pushplus_token.txt",
        Path.home() / ".workbuddy/automations/campus-morning-radar/pushplus_token.txt",
        Path.home() / ".workbuddy/automations/automation-1786404713606/pushplus_token.txt",
    ]
    for f in cands:
        if f.exists():
            return f.read_text(encoding="utf-8").strip()
    raise RuntimeError("PushPlus token 未配置")


def push(title: str, content: str) -> dict:
    tk = resolve_token()
    body = json.dumps({"token": tk, "title": title[:100],
                       "content": content, "template": "markdown"}).encode("utf-8")
    req = urllib.request.Request(
        PUSHPLUS, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"pushplus HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}")
    except Exception as e:                                    # noqa: BLE001
        raise RuntimeError(f"pushplus失败: {type(e).__name__}: {e}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只生成不推送")
    ap.add_argument("--push", action="store_true", help="推送微信")
    ap.add_argument("--pages", type=int, default=2, help="每关键词页数")
    a = ap.parse_args()

    data = collect(dry_run=a.dry_run, pages=a.pages)
    title, content = build_report(data)
    (HERE / "output").mkdir(exist_ok=True)
    out = HERE / "output" / f"校招晨报_{data['date']}.md"
    out.write_text(content, encoding="utf-8")
    log(f"报告已写出: {out}")

    if a.push:
        try:
            r = push(title, content)
            log(f"推送结果: code={r.get('code')} msg={r.get('msg')}")
        except Exception as e:                                # noqa: BLE001
            log(f"推送失败（报告已落盘，内容未丢）: {e}")
    else:
        log("未指定 --push，仅生成报告")


if __name__ == "__main__":
    main()
