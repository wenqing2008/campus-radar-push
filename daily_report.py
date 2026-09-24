"""
校招雷达·日报推送（每日 9:00 北京时间自动推）
- GitHub Actions cron 0 1 * * * UTC = 北京时间 9:00
- 也支持 workflow_dispatch 手动触发
- 内容动态部分：日期 + 关键截止倒计时
"""
from datetime import date, timedelta
from pushplus_notify import send


# 关键截止日期（手动维护，对应 V5 台账里的"待投递/待钻取"清单）
DEADLINES = [
    ("中冶建研院 J10554 网申", date(2026, 11, 7)),
    ("中铝集团 2027 校招统一入口", date(2027, 3, 7)),
    ("中铝包头铝业 工程技术", date(2027, 5, 31)),
    ("中建八局华北 校招通道", date(2027, 7, 31)),
]


def build_countdown(today: date) -> str:
    """生成关键截止日期倒计时段（90 天内高亮）"""
    lines = []
    for name, dl in DEADLINES:
        days = (dl - today).days
        if days < 0:
            lines.append(f"- ~~{name}：已截止（{dl}）~~")
        elif days <= 30:
            lines.append(f"- 🔴 **{name}：仅剩 {days} 天**（{dl} 截止，紧急）")
        elif days <= 90:
            lines.append(f"- 🟡 {name}：还剩 {days} 天（{dl} 截止）")
        else:
            lines.append(f"- 🟢 {name}：还剩 {days} 天（{dl} 截止）")
    return "\n".join(lines)


# 基础内容（V5 校准版）
BASE_CONTENT = """## A 河海给排水（3 条直接可投）

| 岗位 | 入口 | 投递方式 | 薪酬 | 地点 |
|---|---|---|---|---|
| 中建三局三公司·给排水生产工程师 | career.hebut.edu.cn/correcruit/content/id/80401.html | 页内"投递简历"按钮 / 0571-88066106 | 实习 6-8K / 转正 8-10K | 京津冀等 5 区（不可指定） |
| 中建三局三公司·给排水商务工程师 | 同上 | 同上 | 同上 | 同上 |
| 中建八局华北·专业工程师 | career.hit.edu.cn/zhxy-xszyfzpt/zpxx/zpxxxq?id=M2NjN2JhOGU4ODExNGE3ZDk3YzQ1MzRlMjQ2MTdlNDc- | 邮箱 18622201168@163.com / 022-65353967 | 10K-15K | 天津/京/粤/冀/雄安/唐山 |

## B 河北科大金属材料工程

### 直接可投 3 条

| 岗位 | 入口 | 投递方式 | 薪酬 | 地点 |
|---|---|---|---|---|
| 中冶建研院·材料研发 J10554 | zyjyy.zhiye.com/campus/jobs | 平台报名 | 6K-12K | 天津蓟州 |
| 天津钢管·生产工艺 | career.hebut.edu.cn/home/correcruit/content/id/72819.html | 邮箱 citicitpcohr@citicsteel.com | 6000-8000 | 天津东丽区 |
| 一重天津重工·工艺技术（机械） | tjut.bysjy.com.cn/detail/job?id=3239365 | 页内"投递简历" | 未公开 | 天津东丽区 |

⚠️ 中冶建研院平台首页当前"暂无热招"，J10554 直链待补
⚠️ 一重天津重工岗位要求原文未列"金属材料工程"，B 投有专业被筛风险

### 视野放宽 8 条

| 单位 | 入口 | 投递方式 | 薪酬 | 地点 |
|---|---|---|---|---|
| 邯郸钢铁·河钢邯钢 | wsu.ncss.cn/student/jobs/18eecd4aec294c77b533d3b7f103bb53/corp.html | 邮箱 hgrlzyb@hbisco.com / 0310-2095903 | 未公开 | 河北邯郸 |
| 河钢大河金属·管培生 | career.hebut.edu.cn/correcruit/content/id/80702.html | 页内"投递简历" | 试用 4.5-6K / 转正 6-8K | 冀/苏/皖/鲁 |
| 首钢京唐·钢铁工艺工程师 | 学校就业网 | 邮箱 sgjt_zp@163.com / 0315-8873952 | 未公开 | 河北唐山曹妃甸 |
| 唐山钢铁·产线区域工程师 | career.csu.edu.cn/job/view/id/1189631 | 邮箱 tangsteelhr@163.com / 0315-2703871 | 7500-10000 | 河北唐山 |
| 首钢股份·冶金工程师 | job.ustb.edu.cn/f/recruitmentinfo/show?recruitmentId=dd42895311dc458bbd475671959a79ee | 邮箱 gfzp@sgqg.com / 0315-7706078 | 未公开 | 河北唐山迁安 |
| 宝钢湛江·钢铁工艺工程师 | baowugroup-zhaopin.51job.com | 网申 + WPS 表单 f.wps.cn/g/3w6gXXnR/ | 试用 7-8K / 转正 9-10 万 | 广东湛江 |
| 中铝集团·统一入口 | chinalco2027.iguopin.com | 平台报名 | 按子公司 | 全国多地 |
| 中铝包头铝业·工程技术 | career.tyut.edu.cn/Zhaopin/zhiweiDetail.html?id=1608eea7-3b8c-498d-9a6c-fe171d5306f9 | 邮箱 blrsbzp@163.com / 0472-6935098 | 8000-10000 七险二金 | 内蒙古包头 |

⚠️ 首钢股份原文专业需求表"金属材料工程"不在内，B 只能投"材料加工工程"或"冶金工程"
"""


def build_content() -> tuple[str, str]:
    today = date.today()
    title = f"校招日报 {today}"
    countdown = build_countdown(today)
    content = f"""# 校招日报 {today}（{['周一','周二','周三','周四','周五','周六','周日'][today.weekday()]})

> 云端版 · GitHub Actions 自动推 · 本机 Windows 关机不影响

## ⏰ 关键截止倒计时

{countdown}

{BASE_CONTENT}
"""
    return title, content


if __name__ == "__main__":
    title, content = build_content()
    resp = send(title, content, template="markdown")
    ok = resp.get("code") in (200, "200")
    print({"ok": ok, "title": title, "response": resp})
    if not ok:
        raise SystemExit(1)