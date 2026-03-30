# 项目开发日志

## 2026-03-30 — 初始搭建完成

### 已完成
1. **Outlook 认证** — Playwright 自动化 OWA，截取 Bearer token
   - 无需 Azure AD admin 权限（用户无 admin 权限）
   - 三层递进：token 缓存 → headless 刷新 → 可见浏览器登录
   - Token 从 JWT 解码真实过期时间（~26h），30min 内自动刷新
   - 浏览器 session 持久化在 `.browser_state/`

2. **邮件抓取** — Outlook REST API v2.0
   - 按发件人 `$filter` + 客户端关键词匹配
   - 分页支持，附件下载（含内联图片）
   - 去重机制（`.fetched_ids.json`）

3. **HTML→Markdown 转换**
   - BeautifulSoup 清理 + markdownify 转换
   - cid: 内联图片和 base64 图片提取保存
   - 投行邮件布局表格噪音已部分清理（不影响 LLM 总结）

4. **筛选配置** — `filters.yaml`
   - 5 组 daily 必读: JPM Tech Sketch, Jefferies Tech, Bernstein TMT, FOMO Therapy, Wolfe Internet
   - 支持发件人 + 关键词组合

5. **每日总结（手动）**
   - 在 Claude Code 中手动读取邮件并生成总结
   - 输出到 `output/daily/2026-03-30_daily_digest.md`
   - 按板块/Ticker 排序，中文，标注信息来源

6. **Claude API 脚本化总结**
   - 实现基于 Claude API 的每日邮件摘要生成
   - 支持 multimodal 图片分析（>30KB PNG 图表）
   - 使用第三方 Anthropic API 中转站，需在 `.env` 配置：
     - `ANTHROPIC_API_KEY`: API 密钥
     - `ANTHROPIC_BASE_URL`: 中转站 URL（可选，不设置则使用官方 API）

### 待做
- [ ] **定时任务** — cron/launchd 自动化每日运行
- [ ] **IM 推送** — 总结结果推送到微信/飞书

### 技术决策记录
- 放弃 Graph API + MSAL 方案（用户无 Azure AD admin 权限）
- 选择 Playwright 截取 OWA token + Outlook REST API v2.0
- 关键词过滤从服务端 `$search` 改为客户端匹配（避免 $filter+$search 400 错误）
- HTML 转换用 markdownify（优于 html2text，表格处理更好）
