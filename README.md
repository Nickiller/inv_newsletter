# inv_newsletter

从企业 Outlook (M365) 邮箱自动抓取投研邮件，转换为 Markdown 并生成每日摘要。

## 特性

- **无需 Azure AD admin 权限** — 通过 Playwright 自动化 OWA 获取 token
- **灵活筛选** — YAML 配置发件人 + 主题关键词组合
- **全文保存** — HTML 转 Markdown，内联图片自动提取
- **自动去重** — 重复运行不会重复下载
- **Token 自动刷新** — headless 浏览器静默续期，约 1-3 个月才需手动登录一次

## 快速开始

```bash
# 安装
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium

# 首次运行（弹出浏览器登录 Outlook Web）
inv-newsletter --dry-run

# 正式抓取
inv-newsletter
```

## 配置

编辑 `filters.yaml` 管理邮件筛选规则：

```yaml
hours_back: 24

filters:
  - name: "JPM Tech Sketch"
    senders:
      - "mark.schilsky@jpmorgan.com"
    keywords:
      - "JPM TECH SKETCH"

  - name: "Jefferies Tech"
    senders:
      - "jfavuzza@jefferies.com"
    keywords:
      - "Jefferies Tech"
```

## CLI 用法

```bash
inv-newsletter                  # 抓取并保存到 data/mail/
inv-newsletter --dry-run        # 预览匹配邮件，不下载
inv-newsletter --hours 72       # 自定义时间范围
inv-newsletter --config my.yaml # 指定配置文件
```

## 输出结构

```
data/mail/
  2026-03-30/
    0901-crwd-upgrading-to-outperform-wolferesearch/
      email.md          # Markdown 全文 + YAML frontmatter
      img-001.png       # 提取的内联图片
      img-002.png
  .fetched_ids.json     # 去重记录
```

## 认证流程

```
get_session()
  ├─ token 缓存有效（>30min）→ 直接使用
  ├─ 缓存过期 → headless 浏览器静默刷新（~3s）
  └─ 浏览器 session 过期 → 弹出浏览器手动登录
```

Token 有效期约 26 小时，浏览器 session 约 1-3 个月（取决于企业策略）。

## 依赖

- Python >= 3.11
- playwright, requests, msal, pyyaml, beautifulsoup4, markdownify, python-dotenv
