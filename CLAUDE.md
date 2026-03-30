# inv_newsletter — 投研邮件抓取与总结工具

## 项目概述
从企业 Outlook (M365) 邮箱中自动抓取投研邮件，转换为 Markdown 并用 LLM 生成每日摘要。

## 架构
- **认证**: Playwright 自动化 OWA，截取 Bearer token（无需 Azure AD admin 权限）
- **API**: Outlook REST API v2.0 (`outlook.office365.com/api/v2.0/me/messages`)
- **转换**: BeautifulSoup + markdownify（HTML → Markdown + 图片提取）
- **存储**: `data/mail/YYYY-MM-DD/{slug}/email.md` + 图片，JSON 去重

## 关键模块
```
src/inv_newsletter/
  auth.py       — OutlookBrowser: Playwright token 捕获（headless 优先，session 持久化）
  outlook.py    — OutlookClient: fetch_emails + fetch_attachments
  converter.py  — HTML→Markdown 转换 + cid/base64 图片提取
  storage.py    — 文件保存、YAML frontmatter、去重
  config.py     — 加载 filters.yaml
  cli.py        — CLI 入口 (inv-newsletter)
```

## 配置
- `filters.yaml` — 邮件筛选规则（发件人 + 主题关键词）
- `.env` — AZURE_CLIENT_ID, AZURE_TENANT_ID（当前未使用，保留备用）

## 使用
```bash
source .venv/bin/activate
inv-newsletter                  # 抓取并保存
inv-newsletter --dry-run        # 预览匹配邮件
inv-newsletter --hours 72       # 自定义时间范围
```

## Token 生命周期
1. Token 缓存（~26h 有效）→ 直接使用
2. Token 即将过期（<30min）→ headless 浏览器静默刷新
3. 浏览器 session 过期（1-3 个月）→ 弹出浏览器手动登录

## 开发约定
- Python >=3.11, 依赖管理用 pyproject.toml
- 数据文件不入 git（data/, output/, .token_cache/, .browser_state/）
- 投行邮件 HTML 转换存在布局表格噪音，不影响 LLM 总结质量
- 用户回复语言为中文时用中文回复

## 下一步 (TODO)
- [ ] 用 Claude API 脚本化每日总结（替代手动在 Claude Code 中总结）
- [ ] 定时任务自动化（cron / launchd）
- [ ] 总结结果推送到 IM 工具
