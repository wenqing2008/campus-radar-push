# campus-radar-push

云端定时推送校招日报到聪哥微信（pushplus）。

## 链路

GitHub Actions (cron 0 1 * * * UTC = 北京时间 9:00) → pushplus_notify.py → pushplus.plus/send → 微信公众号

## 配置

- `secrets.PUSHPLUS_TOKEN`：pushplus 个人 token（聪哥手工在 repo Settings → Secrets 设置）
- 推送内容在 `.github/workflows/daily-push.yml` 里改

## 手动触发

```
gh workflow run daily-push.yml --repo wenqing2008/campus-radar-push
```

或在 GitHub 网页 Actions 页面点 "Run workflow"。