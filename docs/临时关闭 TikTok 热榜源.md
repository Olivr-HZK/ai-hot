# 临时关闭 TikTok 热榜源

## Summary
当前热榜会启动是因为 `.env` 中配置了 `RAPIDAPI_TIKTOK_HOT_FEED_PATH`。临时止损只需要把这个 path 置空，代码会自动跳过热榜，继续走 TikTok 关键词搜索。

## Required Change
修改 `.env`：

```env
RAPIDAPI_TIKTOK_HOT_FEED_PATH=
```

保留这个 key 不动即可：

```env
RAPIDAPI_TIKTOK_HOT_FEED_KEY=...
```

## Expected Behavior
- 下次 TikTok 流程不会再请求 `/api/trending/video`。
- 不会再出现热榜接口的 `This endpoint is disabled for your subscription` warning。
- TikTok 仍会继续使用原来的 Apify / RapidAPI 关键词搜索逻辑。
- 需要注意：如果 Apify 仍有 `Too many outstanding invoices`，TikTok 主抓取仍可能失败，这和热榜关闭是两个问题。

## Verification
关闭后运行一次 TikTok 抓取或日常 dry run，检查日志中不再出现：

```text
TikTok hot feed fetch failed
/api/trending/video
```
