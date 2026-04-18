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
  config.py     — 加载 filters.yaml（含 MonitorConfig）
  monitor.py    — 自动监控：轮询邮件 + 条件触发总结
  summarizer.py — Claude API 总结（支持邮件 + PDF）
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
inv-newsletter --summarize      # 抓取 + API 总结
inv-newsletter --monitor -v     # 自动监控模式（launchd 调用）

# 发布到飞书（完整流水线：fetch → summarize → publish to Lark）
inv-newsletter --summarize --publish                    # 抓取 + 总结 + 发布飞书
inv-newsletter --summarize --publish --date 2026-04-17  # 指定日期
inv-newsletter --publish-file output/daily/2026-04-17_daily_digest.md  # 单独发布已有文件
```

### 发布流程说明
`--publish` 会在总结完成后自动调用 `lark_publisher.py`，将 Markdown 转为飞书文档并生成公开分享链接（可直接转发微信）。`--publish-file` 用于单独发布已有的摘要文件，跳过抓取和总结步骤。

## 自动监控
- launchd 每 30 分钟调用 `--monitor`，20:00-23:00 CST 窗口
- 检测 6 个邮件源到达情况，≥2 源 + 45 分钟无新邮件 → 自动总结
- 23:00 截止强制总结已收邮件
- 配置：`filters.yaml` 的 `monitor:` 段
- 日志：`logs/monitor.log`
- 状态：`data/mail/.monitor_state.json`

## TMTB PDF 工作流
TMTB daily 是 Safari 截图型 PDF（有复制保护，pdftotext 无法提取文字）：
1. 用户手动将 PDF 放到 `data/` 目录
2. 用 `pdftoppm -png -r 150` 转为图片
3. Claude Code 用 Read 工具逐页读取图片提取文字
4. 保存为 `data/mail/YYYY-MM-DD/0600-tmtb-morning-wrap-tmt-breakout/email.md`
5. Claude Code 直接生成每日摘要（不走 API proxy，因 proxy 有请求体大小限制）

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
- [x] 用 Claude API 脚本化每日总结（summarizer.py 已实现）
- [x] 定时任务自动化（launchd + monitor.py 已实现）
- [x] 总结结果推送到 IM 工具（lark_publisher.py + --publish CLI 已实现）
- [ ] TMTB PDF 自动化（目前手动提取，可考虑 Tesseract OCR 或定时 Claude Code 任务）
