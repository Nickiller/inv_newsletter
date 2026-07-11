# Handoff — 2026-07-11 session（prompt 简化 + 盲点扫描）

> 下一个 session 从这里接。详细的盲点分析 + 四步方案 + 每步产出/被推翻的计划项都在
> [`260711_blindspot_scan.md`](260711_blindspot_scan.md)（已提交）。本文件只讲**状态 + 下一步 + 接手须知**。

## 状态：已完成并推送

3 个 commit 已 push 到 `origin/main`（Nickiller/inv_newsletter），working tree 干净（除 output/ 备份，已 gitignore）：
- `20622a1` chore — Step 1：删 4 个 legacy prompt + monitor 改只通知 + CLAUDE.md 纠正
- `45b7b19` refactor — Step 2-4：theme 词库外置 + master/tldr 瘦身 + 跨 prompt 冲突修复
- `7e35261` docs — 盲点扫描记录

**成果**：v3 prompt 套件 ~480 → ~400 行；删近千行 legacy；消除 4 处冲突；theme 一致性移进 `digest_v3/prompts/themes.txt`。
**A/B 实测（2026-07-10）**：其他板块 45→27、AI 板块 2→14、多源主题 4→11、无真内容丢失。
对比文件留在 `output/daily/2026-07-10_daily_digest_v3_{OLD,NEW}.md`（gitignore，本地可看）；旧中间产物 `output/daily/2026-07-10/v3_old_prompts/`。

## 接手须知（关键上下文）

1. **v3 是 CC-session 驱动，不调 API、不跑 run 脚本**（见 memory [[feedback_v3_no_api_cc_driven]]）。
   编排规范是 `src/inv_newsletter/digest_v3/RUNBOOK.md`（10 stage）。LLM stage 用 Agent 工具派 subagent
   （route/catalyst=sonnet，sections/tldr=opus），确定性 stage 是 `python -m inv_newsletter.digest_v3.{chunk,route_merge,assemble}`。
2. **只改了 prompt 时怎么跑 A/B**（本 session 用过，验证有效）：先 `cp` 备份旧 digest + `cp -r v3 v3_old_prompts`
   （因 finalize 会覆盖 canonical 名）；**复用** formatted/chunks/image_routes（这些 stage 的 prompt 没变）；
   **重跑** text-route → route_merge → sections → catalyst → assemble → tldr → finalize。跑完做泄漏标记扫描
   （RUNBOOK Post 步骤的 grep）。详见 memory [[project_v3_ab_rerun_procedure]]。
3. **不要重试这三个被推翻的计划项**（近距离读代码后判定是坏主意，理由在盲点文档 Step 2/4）：
   ①把 section prompt 砍到 ≤12 行（coverage 花名册是 load-bearing）；②把链接抽成结构化 `links` 字段
   （切断链接↔论点对应 + 与 skip-list 冲突）；③TL;DR「按正文顺序取前 3-5」（正文是 canonical 板块序非重要性序）。

## 下一步（都独立，未承诺，按用户意愿挑）

### A. 代码库文件清理（用户最初提的第二优先级；低风险、纯整理）
- 根目录：`test_fetch.py` → `tests/` 或删；`log.md` → 并入 tasks/ 或删；`.DS_Store` → 加 .gitignore。
- `scripts/`：`meritco_explore.py` 等一次性探测脚本 → `scripts/_archive/`（已有先例）。
- `web/`：按用户约定（消费侧 app 独立成 `~/Code/Claude_Workspace/{name}/`，见 [[feedback_separate_consumer_projects]]）应迁出本仓库。
- legacy 保留决策后（选项 A）：`summarizer.py`(535 行) 里 daily 专属代码仍在，但 `--summarize` 作手动兜底保留——
  **不要动**，除非用户改主意要彻底退役（届时注意 cost/images/postprocess 是与 weekly 共享的 helper）。

### B. Deferred candidates（对「详实 & 重要性鲜明」有杠杆，但要动编排/代码）
- **跨日连贯性**（盲点 U5，杠杆最高）：section writer 输入附昨日同板块正文，加规则「昨日已覆盖的主题只写增量」。需改 RUNBOOK Stage 6 编排。
- **DROP 可审计**（盲点 U2）：route 输出加 `drop_reason`（枚举），route_merge 把 reason+excerpt 前 80 字写进 dropped；丢弃率 >40% 告警。（本 session 已给 route JSON 加了 `theme_is_new` 先例，加字段路径清楚。）
- theme 跨日聚合升权（连续 ≥2 日多源）；PDF 附件文本提取进 digest；时区规整（统一 Asia/Shanghai 划日）。

## 用户还没最终确认的 A/B 观察点（下次可主动问）
- 新版 `#### TICKER` 从 30 砍到 15（headline 纪律 + skip-list）——重要的票是否都还有独立段落？
- AI 板块 3 倍变厚——是否混进了本该在互联网板块的 mega-cap capex/战略叙事？
