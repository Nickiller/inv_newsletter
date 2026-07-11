# 盲点扫描 + Prompt 升级方案（2026-07-11）

> 背景：以"全新架构师"视角对整个 repo 做的一次审计。目标对齐：**每天产出详实 & 重要性鲜明的 investment daily digest**。
> 方法：4 个并行探索 agent（git 考古 / prompt 盘点 / pipeline 健壮性 / 数据落差）+ 本人对关键结论逐条交叉验证。
> subagent 报告中被验证为**错误**的结论已剔除（如"While You Were Sleeping 失效 2.5 个月"——实际每天经 etnalabs 转发正常到达）。

---

## 一、盲点清单（unknown unknowns，已验证，按伤害排序）

### U1. 源健康零监控 ~~🔴~~ → 用户确认符合预期（2026-07-11）
> Wolfe / Jefferies 直发源停发是已知且符合预期的。不做告警机制；仅建议给 filters.yaml 里的死源加 `# inactive` 注释或直接移除，保持配置与现实一致。原始发现保留如下备查。

原文：
- **Wolfe Internet**（skhajuria@wolferesearch.com）最后到达 **2026-04-23**，近 7 天 0 封；
- **JPM Tech HW & Semis**（feihong@etnalabs.co）**从未到达过**；
- Jefferies WYWS 的直发源（comara@jefferies.com）已死，恰好被 etnalabs 转发顶上——说明"发件路径变更 → 静默漏"这类事件已经发生过一次，只是这次运气好。
- filters.yaml 配置 11 个 daily 源，实际存活 **8 个**。没有任何机制发现这件事。
- **含义**：digest 的"详实"上限被无声压低了 ~2 个月，互联网板块观点长期缺 Wolfe 视角。

### U2. 路由 DROP 黑洞：16-34% 的 chunk 被丢且不可审计 🔴
- 实测：07-08 丢 50/198（25%），07-09 丢 **72/212（34%）**，07-10 丢 31/189（16%）。
- `route_map.json["dropped"]` 只存 `chunk_id + source_slug`，**无 reason、无 excerpt**——要复核必须回 chunks.json 手动对。
- 抽查 07-09 Tech Sketch 的 13 个被丢 chunk：多为导航/卖方 webinar/娱乐新闻，丢得合理；HKCHINA daily 丢 27 个多为非 TMT（符合偏好）。**当前没证据表明有误杀，但系统性上无法证明没有**。
- 已验证 OK 的部分：DROP chunk 的 catalysts 仍会被收集（route_merge.py:487 是 chunk 级收集，META Connect / re:Invent 这类日历不会因 DROP 丢失）。

### U3. 质量分叉：monitor 自动总结走的是 legacy 单 prompt 路径 🔴
- monitor.py:77 触发的是 `summarizer.summarize_daily`（legacy API 路径），而夜间正主流程是 CC 驱动的 v3。
- 若某晚 v3 没跑、monitor 条件先满足（≥2 源 + 45min 静默），launchd 会自动产出一份 **legacy 质量**的 digest 并标记 `summarized`——而 memory 已记录 legacy 明显更差、v3 失败时不应 fallback legacy。
- 两条生成路径共存、质量不同、自动化的那条是差的——流程级盲点。

### U4. 规则联合作用："其他"板块成倾倒场 + AI 板块被抽干 🟡
- 实测 primary 分布：07-09 与 07-10 "其他"各 **45 条**（全板块最多）；07-10 "AI 模型与平台"仅 **2 条**。
- route.md:25-28 把 mega-cap 公司战略/财务（即使涉 AI）赶去 `其他`；但 sections/other.md（仅 14 行）自我定位是"**TMT 范畴外** + 久谦纪要为主"——内容被路由到一个**不认领它**的 prompt 手里，writer 大概率当噪音弱写。
- 两条规则各自合理（AI 板块聚焦 LLM labs 是明确偏好），但联合产生了没人设计过的行为。

### U5. 跨日连贯性缺失：重要性日间跳变 🟡
- 每天独立生成、无昨日上下文。实例：NFLX engagement 论点 07-09 三个数据支撑点详实展开（含 replay 链接），07-10 缩成一句"shorts 挖得很深"。
- "重要性"本质是跨日累积信号（**连续多日多源 > 单日多源**），当前架构对此完全不可见。theme 标签也跨日不稳定（07-08 叫 `存储涨价`，07-10 叫 `存储超级周期`——同一叙事，聚合断裂）。

### U6. 次级盲点（真实但低频，backlog）
- monitor 在 launchd 后台跑时 token 过期 → 当天静默零抓取（仅 log warning）；
- PDF/Office 附件完全不进 digest（converter.py 只处理 `image/*`；TMTB 手动流程之外的卖方 PDF 附件被静默忽略）；
- `received_at`(UTC) 与日期目录名的时区边界（午夜前后邮件可能落错日期目录）；
- slug 同分钟碰撞可覆盖邮件（概率极低）；
- 图片 >1.5MB / 超 5 张被过滤时仅 info 级日志，无统计汇报。

---

## 二、Prompt 层问题（本人逐行读过 v3 全部 prompt 后确认）

生产路径是 `digest_v3/prompts/*`（CC 驱动）+ `prompts/tldr.md`。合计约 480 行、11 个文件。总体评价：架构分层清晰、风格约束优秀（数字呈现优先级、锚文本陷阱、headline 句范式都是高水平设计），弱点集中在**重要性判据**与**跨 prompt 一致性**。

### P1. 重要性只有二值 flag，缺全序与负面清单（对"重要性鲜明"伤害最大）
- route.md `headline_flag` 四个触发条件**平权**：当天财报 ≈ 无新闻的 mega-cap anchor ≈ 多源。true 之后一律平铺 `####`，读者无法从版面分出"今天真正的事"和"例行 anchor"。
- master.md:73 "短内容优先直接删除"**无判据**——writer 各凭感觉，详实度不稳定的直接来源。

### P2. theme 标签无标准词库（多源信号——最重要的信号——聚合靠运气）
- route.md:73-76 仅 8 个例子；跨邮件聚合依赖各批次 LLM 自发用同一标签，`_norm_theme()` 只删空格标点，救不了同义词。
- 实证：07-08 `multi_source_themes` 里 `国产存储替代` 与 `存储涨价` 并列，07-10 变成 `存储超级周期`——同一叙事被拆成多个弱信号，本应是"当天最重要信号"的权重被稀释。

### P3. mega-cap 战略内容归宿错位（对应 U4）
- 建议归"该公司主业板块"而非 `其他`：Google 增发 → 互联网与数字广告；Nadella 谈竞争 → 软件与SaaS；对应 section prompt 加一句接纳条款。

### P4. 重要性判据三处各写一套
- tldr.md 用板块序（AI > semi > memory > …），route.md 用事件条件，master.md 说"上游已排好序"。同一概念三种定义，TL;DR 选条和正文排序可能打架。

### P5. 小项
- ai_platform.md:14 "按 LLM lab 分别成段 `#### 公司名`" 与 master.md:12 "只有 `headline: true` 才起 `####`" 冲突；
- other.md 仅 14 行，却是近两天承接内容最多（45 条）的板块——prompt 厚度与内容量倒挂；
- dropped 审计（见 U2）需要 route 输出配合：DROP 时带一个 `drop_reason`。

---

## 三、改进方案 v2（2026-07-11 修订：以"简化"为总方向，参考 ai-signal）

> 用户反馈：prompt 层优化第一优先，但**现有 prompt 已过于复杂**，方向参考
> https://github.com/Benboerba620/ai-signal（6 个 prompt 文件、各 ~30 行）。
> 其次是代码库文件/架构堆积的清理。
> ⚠️ 原方案 1a 中"headline 改三级 importance"**撤回**——那是加复杂度，与新方向相反。

### ai-signal 为什么短（哪些可搬、哪些不可搬）

可搬的四个结构原则：
1. **合同进代码/数据，判断留 prompt**。它的 prompt 短是因为 30KB 的 `prepare_digest.py`
   把数据做成命名字段 JSON，prompt 只说"用 JSON 里的 url"。复杂度没消失，是搬进了确定性代码
   ——与本仓库 CLAUDE.md Rule 5 同源。
2. **一个概念只定义一次**（单一事实源）。
3. **二值 include/skip 清单**替代加权/分级判断。
4. **一个好例子顶三条规则**。
不可搬的：ai-signal 是单源流水线（每条内容独立总结、互不综合）；本项目的跨邮件多源共识、
重要性排序、买方口吻是"详实 & 重要性鲜明"的正当复杂度，砍掉会直接伤目标。

### 现有 480 行 v3 prompt 的复杂度成分分析

| 成分 | 行数占比（约） | 处置 |
|---|---|---|
| 合同类规则（链接保留/锚文本陷阱/图片 ID/排序/多源标注） | ~25% | **搬进数据契约**：chunk 阶段把 links 抽成结构化字段，prompt 缩到一两行 |
| 跨文件重复（sector 定义、hyperscaler 例外、anchor 列表、重要性判据 ×3 处） | ~20% | **单一事实源**：每个概念只留一处 |
| 风格微规则（headline 句式/表格触发/数字优先级/防 AI 味） | ~30% | **压缩**：例子留最好的一个，散文改 checklist；防 AI 味交给 reviewer 事后 pass |
| 真判断规则（路由/DROP/theme/什么值得写） | ~25% | **保留**，格式改成 include/skip 二值清单 |

### Step 1 — 删除 + monitor 改造（进行中，2026-07-11）

**已完成（安全部分）：**
- ✅ 删 4 个零引用 legacy prompt（全仓库 grep 确认无加载、无 glob 动态加载）：
  `digest_system.md`、`digest_system_v2_restructured.md`、`digest_system_v3_en.md`、`few_shot_examples.md`。
- ✅ monitor 改**只通知不自动生成**：`if should:` 块不再调 `summarize_daily`，改为 set `notified` flag
  + `_notify_user`。解决盲点 U3（monitor 不会再自动发 legacy 质量 digest）。语法检查通过。
- 保留：`tldr.md`、`reviewer.md`、`weekly_system.md`、`image_caption.md`。

**⚠️ 未做，需你拍板 —— `digest_system_v3.md`（306 行）+ `summarize_daily` 全退役：**
- 现状（grep 确认）：`digest_system_v3.md` 仍被 `summarizer.summarize_daily` 加载；monitor 改造后，
  该函数**唯一剩余调用方** = `inv-newsletter --summarize`（cli.py:328，CLAUDE.md 有文档）+ `--system-prompt` A/B flag。
- 全退役 = 删 digest_system_v3.md + 从 summarizer.py 拆掉 summarize_daily（~300 行，但 cost/images/postprocess
  是与 weekly 共享的 helper，要做引用分析后精准切）+ cli.py 去掉 `--summarize` daily 分支。
- 冲突需 surface（Rule 7）：CLAUDE.md 文档把 `--summarize --publish` 写成"主流水线"，但
  memory [[feedback_v3_no_api_cc_driven]] 说 daily 已全 CC 驱动、不调 API。二者矛盾，CLAUDE.md 疑似过时。
- **选项 A（保守，推荐）**：保留 `--summarize` 作手动 escape hatch（headless/cron 无法开 CC session 时
  legacy digest > 无 digest），只更新 CLAUDE.md 注明它是 legacy 手动路径、非主路径。digest_system_v3.md 留着。
- **选项 B（激进）**：彻底退役，删命令 + 删 300 行 + 删 prompt。最干净，但破坏一个有文档的命令、去掉 A/B 能力。

### Step 2 — 收敛重复（已完成，2026-07-11）

**范围修正**：近距离读完 6 个 section prompt 后**撤回**"缩成 role+focus、各 ≤12 行"——它们已很精简
（14-22 行），`<coverage>` 的 ticker 花名册不是 route.md 的重复（route.md 只有一行板块定义），
是 writer 的 load-bearing 领域上下文；三处"AI 层面归 AI 板块、不要重复"看似重复实为 point-of-use
防跨板块重复的 defense-in-depth，一并保留。Step 2 聚焦**真·重复与冲突**：

- ✅ **theme 词库外置** `digest_v3/prompts/themes.txt`（~34 个常青标签，基于实际 route_map 出现过的多源
  主题 + 标准行业主题）。route.md `<theme>` 改为"优先逐字照抄词库，对不上才自造并置 `theme_is_new:true`"；
  `<output>` schema 加 `theme_is_new`；RUNBOOK Stage 3 让 route subagent 也 Read themes.txt。
  治理 P2（多源信号碎片化，如"存储涨价"vs"存储超级周期"被拆成弱信号）——复杂度进数据不进散文。
- ✅ **闭环消费** `theme_is_new`：route_merge.py item 带上该字段，stats 新增 `new_themes` 列表
  （每周把反复出现的自造主题人工吸收进 themes.txt）。真实数据（2026-07-10）重跑验证通过、向后兼容。
- ✅ **修 ai_platform.md ↔ master.md `####` 冲突**：原无条件"按 lab 各起 `#### 公司名`"，
  改为服从 master 的 headline 规则（headline:true 才独立成段）。
- ✅ **修 software_saas.md 简短跟踪冲突**：原让网络安全"并入 `### 简短跟踪`"，与 master.md:76
  + memory [[feedback_digest_cut_short_tracking]] 矛盾，改为"一句带过或删，不单设简短跟踪段"。
- ✅ mega-cap 战略归主业板块：Step 1 已在 route.md 落地。

**移到 Step 3**：master.md "短内容优先删除"改 ai-signal 式 skip-list（二值），归入 master 瘦身一起做。

### Step 3 — master.md 瘦身（已完成，2026-07-11：119 → 61 行，-49%）
- ✅ 删 16 行 `────` 装饰分隔线（零信息），换 `##` markdown 标题。
- ✅ 删排序说明冗余：原 §四"排序"段（anchor>headline>多源>其余）与 §一"已按重要性排好序"重复，
  且顺序由代码强制——合并为 §一 一句"按给定顺序写、不要自己重排"。
- ✅ headline 例子 3 → 2（删 Samsung"盘中蒸发后收复"，留涨/miss 两个 + fallback 说明）。
- ✅ 表格触发 12 行 → 2 行（三个触发条件 + 顿号串禁令压成一段）。
- ✅ 短内容改 **skip-list**（二值 4 条：评级重申/纯情绪/单源无 read-through/详版覆盖），
  比原"优先删除"凭感觉更可执行；theme_multi_source 例外保留为 blockquote。
- 保留（逐字或等价）：数字呈现优先级全 4 条、theme_multi_source 处理、读者口吻、
  §六链接章节（按计划"先不动"，留 Step 4 数据契约落地后再缩）、图片规则、严禁。
- 自检：12 条 load-bearing 规则关键词全部命中。

### Step 4 — 数据契约 + tldr（已完成，2026-07-11。计划两半均经复核修正）

**① 链接结构化 —— 撤销（读 chunk.py/assemble.py 后判定不成立）：**
- 原设想：chunk.py 抽 `links` 字段 → §六"锚文本陷阱"可删。**推翻**，三条理由：
  (a) 链接是位置性的、贴着具体论点；抽成独立数组切断"链接↔论点"对应，writer 更易张冠李戴；
  (b) 链接本就内联可见，§六 是纪律（别丢/命名/贴内容）不是可见性问题，代码替代不了判断；
  (c) 想过 assemble 加"输入链接必须出现在输出"的校验闸，但与 Step 3 skip-list 冲突
  （低价值单源被合法删除时其链接也该消失，闸会对每次合法删除误报）。
- 结论：链接保持内联，master §六 5 行判断规则**不动**。assemble.py 现状只校验 IMG、不校验链接——维持。

**② tldr.md 瘦身（已完成：65 → 45 行）：**
- 核心修正：原计划"按正文出现顺序取前 3-5"**不成立**——正文的板块顺序是 canonical 固定序、非重要性序，
  照搬会永远把第一个板块顶上去。
- 实际改法：删掉那个 6 档"重要性优先级"阶梯（P4 的第三套重叠排序），把重要性锚定在 **信号强度**
  （±5%/guide change/多源共识/mega-cap pull-forward/IPO/宏观——与 route.md headline 逻辑同源），
  6 档阶梯降级成一行 tiebreaker（"信号相当时 AI/算力/半导体 优先"）。示例删 1 条 sub-bullet。
- 保留：3-5 bullet、sub-bullet 链接规则、涉及行不带链接、✅/⚠️ 与 long/short 禁令、卖方>媒体>博客 优先级、
  lean 示例。9 条 load-bearing 关键词自检全命中。

### 代码库清理清单（第二优先级，与 Step 1 同批做掉大头）
- `prompts/` legacy 5 文件（见 Step 1）；
- 根目录：`test_fetch.py`（挪 tests/ 或删）、`log.md`（并入 tasks/ 或删）、`.DS_Store`（加 .gitignore）；
- `scripts/`：`meritco_explore.py` 等一次性探测脚本 → `scripts/_archive/`（已有此先例）；
- `web/`：按既定约定（消费侧 app 独立成 `~/Code/Claude_Workspace/{name}/`）应迁出本仓库；
- legacy daily 路径退役后：`summarizer.py`（535 行）里 daily 专属代码可删/合并，只留 weekly 所需；
  `postprocess.py`/`images.py` 中仅服务 daily-legacy 的部分同步清理（动手前先做引用分析）。

### Deferred candidates（不承诺，视上述效果再议）
- 跨日连贯性：section writer 附昨日同板块正文，"昨日已覆盖的主题只写增量"（需改 RUNBOOK 编排）；
- theme 跨日聚合升权（连续 ≥2 日多源）；
- DROP 可审计（route 输出带 drop_reason + excerpt 前 80 字）；
- PDF 附件文本提取；时区规整（统一 Asia/Shanghai 划日）。

---

## 四、已验证为不成立/无需处理的 subagent 结论（防止误信）
- ❌ "While You Were Sleeping 失效 2.5 个月" — 实际每天经 etnalabs 转发到达；
- ❌ "催化剂日历随 DROP chunk 丢失" — catalysts 是 chunk 级收集，与 routes 的 DROP 独立；
- ❌ "mega-cap 列表两处定义冲突" — route.md 内 anchor 与 AI 中盘本就是两个并列集合，非冲突；
- ⚠️ "27 chunks 未路由" — 实际丢弃量更大（16-34%），但抽查未见误杀，问题是不可审计而非已出错。
