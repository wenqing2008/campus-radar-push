# campus-radar-push（真采集·云端版）

> **云端执行，关机也能推送。** 这是关机兜底通道。
> 本机版（WorkBuddy 自动化 08:30）见 `D:\Workbuddy\campus-radar-live`；
> 本机不开机时，由本仓库的 GitHub Actions 在北京时间 **08:35** 接管。

## 两套通道的关系

| | 本机 | 云端（本仓库） |
|---|---|---|
| 触发 | WorkBuddy 自动化，工作日 08:30 | GitHub Actions，北京 08:35 |
| 依赖 | 机器开机 + WorkBuddy 运行 | GitHub 服务器，与本机无关 |
| 关机时 | ❌ 不执行 | ✅ 照常执行 |

两者用同一套采集逻辑与账本去重，**同时在线不会重复展开内容**（本机推过的岗位云端标为已见）。

## 关键前提：账本持久化

云端每次都是**全新容器**，账本默认会丢。若不管，每天所有条目都会被当成"新增"，
去重机制失效。本仓库用 `actions/cache` 持久化 `data/ledger.json`。

⚠️ **已知限制**：GitHub 的 cache 有淘汰机制，若连续多天未触发可能 miss，
表现为"所有岗位都标 🆕"。这不影响的岗位信息本身的正确性，只是新增标记不准。
artifact 里留了每次的原始档，可据此手工恢复。

## 为什么旧版是假的

旧 `daily_report.py` 推送的是代码里**写死的静态文本**（`BASE_CONTENT`），从不联网。
`probe.py` 只 curl 首页就宣布"3 个源验证通过"，但那些页面是 JS 渲染，
静态抓取只能拿到 1KB 空壳、关键词命中 **0** 次——属假成功。

现全部改为直连国聘真实接口采集。详见 `D:\Workbuddy\campus-radar-live\README.md`。

## 配置

- `secrets.PUSHPLUS_TOKEN`：已在本仓库 Settings → Secrets 配置，云端读取环境变量
- 候选人画像与评分阈值：`knowledge/candidates.yaml`（改这里，不动代码）

## 手动触发

GitHub 网页 Actions → `campus-radar-cloud` → Run workflow。

## 配置

- `secrets.PUSHPLUS_TOKEN`：pushplus 个人 token（聪哥手工在 repo Settings → Secrets 设置）
- 推送内容在 `.github/workflows/daily-push.yml` 里改

## 手动触发

```
gh workflow run daily-push.yml --repo wenqing2008/campus-radar-push
```

或在 GitHub 网页 Actions 页面点 "Run workflow"。