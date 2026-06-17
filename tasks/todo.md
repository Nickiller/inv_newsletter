# v3 图片 pipeline 修复（CC-subagent 驱动）

## 背景 / 根因（2026-06-08 验证）
v3 从 prototype 转 API pipeline 时漏了 **image captioning 阶段**：
- `chunk.py` 造图片 chunk 时 `caption=""`（注释写"filled by a later stage"），但 `run_v3.py` STAGES 无此 stage。
- route 阶段（text-only sonnet）看到无 caption 的 `IMG_NN` → route.md `<image_chunks>` 规则"无法判断→DROP" → **24/24 全 DROP**。
- 结果：`images_routed: 0`，sections_input.images 全空，assemble 嵌入 0/24（legacy 同日 10/24）。
- `_select_key_images` 只按 size/扩展名过滤，**不做 logo/广告语义判断** → 必须有一次"看图"才能定 DROP/板块。

## 决策 — 全 CC subagents 驱动，按 stage 选模型档（2026-06-08 锁定，方案 A）
原型期 + **大概率正式版也用 A**。`run_v3.py`（API harness）已删除（2026-06-17）——v3 不再有 API 驱动路径，所有 LLM stage 一律走 CC subagent。
正式版"自动化" = 定时 CC session（如 scheduled-task）编排 subagents，非 launchd 调 API CLI。

| Stage | 驱动 | 模型 |
|---|---|---|
| format（规整） | CC subagent ×N 并行 | sonnet |
| chunk（切块） | Bash（纯代码，无 LLM） | — |
| text-route（文本 label） | CC subagent ×N 并行 | sonnet |
| **image-route（图片 label）** | CC subagent（看图） | sonnet |
| route_merge | Bash（代码） | — |
| sections（生成） | CC subagent ×6 并行 | **opus** |
| catalyst / tldr | CC subagent | sonnet/opus |
| assemble / finalize | Bash（代码） | — |

- **图片 label 必须在 CC 侧**：sonnet API text-only 看不到图（今天 24/24 DROP 的根因）；
  备选 API base64 vision 受 palebluedot >1.5MB 静默丢图限制，故放 CC。
- **Rule 5 切分**：看图判断（caption + 板块/DROP）= 模型；JSON 合并 = 代码。
- 复用现有 plumbing：`route_merge`（image 分桶）+ `assemble._validate_image_refs/_embed_images` + `_select_key_images` 全不动主逻辑。
- **本轮只做图片 label 这一件**；format/text-route 改 CC 驱动属 deferred（验证图片 fix 直接复用今天已落盘的 routes/*.json 文本路由，无需重跑文本 route）。

## 设计（最小改动）
图片新流向：
1. `chunk.py` 不变 —— 图片 chunk 已带 `image_path` + 空 caption（24 张）。
2. **新增 image-route 步（CC subagent）**：按 email 并行，subagent `Read` 本封图片文件 → 输出
   `v3/image_routes.json` = `[{img_id, caption, primary, tickers}]`，primary ∈ 6 板块 或 `DROP`（logo/广告/签名）。
   - 新 prompt `digest_v3/prompts/image_route.md`：6 板块 taxonomy + DROP 规则（route.md 子集）+ caption 格式（仿 image_caption.md，≤40 字、保留 ticker 英文）+ "Read 给定图片再判断"。
3. **`route_merge.py` 小改（~15 行）**：若存在 `v3/image_routes.json`，用它覆盖图片 chunk 的 `caption` + `primary`
   （取代不可靠的 text-route 图片对象），其余分桶/校验逻辑不变。
4. section subagents 不变 —— 已收 `sections_input[sector].images`（img_id+caption+image_path），按 `![caption](IMG_NN)` 嵌入。
5. `assemble` 不变 —— 已做 ref 校验 + 嵌入。

## 任务清单

- [x] **Phase 1：实现 + 在 06-08 验证（数据已在盘）** ✅ 完成
  - [x] 写 `digest_v3/prompts/image_route.md`（6 板块 + DROP + caption 格式 + JSON schema）
  - [x] `route_merge.py`：加 `_load_image_routes()` + 图片来源解耦（chunks.json + image_routes 覆盖，不再依赖 text router）
  - [x] 跑 6 个 image-route subagent（sonnet，并行 ~30s）处理 24 张图 → image_routes/{slug}.json
  - [x] 重跑 route_merge → images_routed 0→18，sections_input.images 全 6 板块非空
  - [x] 重跑 6 个 section subagent（opus）+ assemble + finalize
  - [x] 🛑 **Checkpoint 1**：**14/24 嵌入（legacy 10/24）**，校验闸 PASS、14 refs 全解析、0 缺失

- [ ] **Phase 2（Checkpoint 后再定）：固化为标准流程**
  - [ ] 文档化 CC-subagent route 步（含图片路由）为原型期标准 flow
  - [ ] 更新 memory `project_digest_v3_arch`（route 步读图 / image_routes.json 契约 / API deferred）

## Deferred candidates（不提前承诺）
- 整个 text-route 步改 subagent 驱动（本轮只补图片这一环）
- 路由质量（DROP 过激进 / multi_source / read-through）
- 板块生成质量（section prompt 迭代）
- reviewer pass（去AI味儿）Phase 2/3
- API 路径补 haiku caption 阶段（若日后要 launchd 自动化）
- A/B：v3 vs legacy 图片嵌入率 / judge 打分

## Review（2026-06-08 完成）
- **根因坐实**：v3 缺 image captioning 阶段 → text-only router 把 24/24 图判 DROP。
- **修复**：新增 CC-subagent 视觉 image-route 阶段（看图打 caption + 板块/DROP），route_merge 把图片路由从文本 router 解耦。
- **结果**：image_routes 18 routed / 6 DROP（logo/装饰/niche 合理剔除）；section 嵌入 14/24（**超过 legacy 10/24**），
  校验闸 PASS、14 refs 全解析、图片文件全就位。
- **发布**：含图版飞书 doc https://www.feishu.cn/docx/Rno5dAB40o1rmexLqTHcNVUjnwf （无图旧版 UTFpd4gEIoYYKZxSeUfc7Gn6nyd 作废）
- **架构验证**：全 CC-subagent 流程跑通——format/route 复用今天 API 产物，image-route(sonnet ×6 并行)+sections(opus ×6)+tldr(opus) 全 CC。
- **改动文件**：`digest_v3/prompts/image_route.md`(新) + `digest_v3/route_merge.py`(解耦图片路由)。**未 commit**。
- **遗留小取舍**：IMG_05(AWS metrics) 路由到 internet 但该板块无 AWS 锚点被 section 跳过 → 可考虑路由到 semi/其他；
  IMG_09 catalyst 日历正确跳过（与本周关注重复）。

## 待定（Checkpoint 后）
- [ ] commit 代码改动（image_route.md + route_merge.py）——等用户指示
- [ ] Phase 2：固化 CC-subagent 全流程为标准 runbook/skill + 更新 memory `project_digest_v3_arch`

---
（以下为暂缓中的另一条线，勿与上方混淆）

# 去 AI 味儿审查（reviewer pass）

## 目标
在 digest 生成的最后加一道「文风审查」——把生硬、机械、带 AI 腔的中文改成自然专业的买方语言，
**只改措辞、不动任何事实/数字/ticker/链接/结构**。legacy 与 v3 共用同一实现。

## 已定决策
- 机制：**独立后处理 LLM pass**（不内联进生成 prompt）
- 默认：**开**，`--no-review` 可关
- 模型：**claude-sonnet-4-6**（短格式，proxy 友好）
- prompt：`src/inv_newsletter/prompts/reviewer.md`（已写好）
- 安全闸：审查后确定性 diff 所有 URL + `IMG_XX`，集合不一致 → 回退原文（已在 06-05 dry-run 验证 PASS）

## dry-run 结论（已完成）
- 在 `2026-06-05_daily_digest_v3.md` 上手动跑 31 处 prose 修改，破折号 63→38，全文 −309 字
- 安全闸：89 URL + 11 IMG 全一致 ✅；anchor 唯一性检查拦下 1 处不存在的文本（机制稳健）
- 校准：用户确认「力度差不多」（去 AI 腔的强度/下手轻重，不是编辑颗粒度）

## 设计

### 新模块 `src/inv_newsletter/reviewer.py`（仿 tldr.py）
```python
REVIEW_PROMPT_PATH  = prompts/reviewer.md
REVIEW_DEFAULT_MODEL = "claude-sonnet-4-6"

def review_digest(digest_md, model=..., prompt_text=None, client=None) -> (reviewed_md, usage)
    # system=reviewer.md, user=<digest>…</digest>，streaming，去 ```fence

def _link_img_signature(md) -> (urls:list, imgs:list)   # 正则提取，确定性

def naturalize(digest_md, model=..., client=None) -> (out_md, usage, used_review:bool)
    # 跑 review_digest → 安全闸比对 → PASS 用审查版、FAIL 回退原文并 log warning
```

### 接入点（两条路径都在「最终成文、写盘前」插一步）
- **legacy** `summarizer.py`：`prepend_tldr(...)` 之后、`output_path.write_text` 之前，
  `if review: digest = naturalize(digest, ...)`
- **v3** `assemble.py:finalize()`：prepend tldr 之后、写盘之前，加 `review: bool = True` 参数同样处理
- 一条路径只跑一次、覆盖全文（含已嵌图片路径里的 `IMG_XX`，安全闸照样比对）

### CLI `cli.py`
- 加 `--no-review`（默认开）；thread 进 `summarize_daily(..., review=not args.no_review)`

### 独立工具 `scripts/review_digest.py`（仿 gen_tldr.py）
- `uv run scripts/review_digest.py --digest <path>`：单独对已有 .md 跑审查（打印 + 安全闸报告）
- `--write` 才回写；默认只打印，方便在历史 digest 上验证

## 任务清单

- [ ] **Phase 1：reviewer.py 模块 + 独立工具**
  - [ ] 新建 `src/inv_newsletter/reviewer.py`（review_digest + 安全闸 + naturalize 回退）
  - [ ] 新建 `scripts/review_digest.py` CLI 包装
  - [ ] 🛑 **Checkpoint 1**：用真 sonnet pass 跑 06-05，确认安全闸 PASS + 文风效果接近手动 dry-run，diff 给用户

- [ ] **Phase 2：wire 进 legacy**
  - [ ] `summarizer.py` 写盘前加 review 步骤（flag 控制）
  - [ ] `cli.py` 加 `--no-review`，默认开
  - [ ] 跑一遍 legacy 全流程验证

- [ ] **Phase 3：wire 进 v3**
  - [ ] `assemble.py:finalize()` 加 `review` 参数 + review 步骤
  - [ ] 跑 v3 assemble 验证
  - [ ] commit（按用户指示）

## Deferred candidates（不提前承诺）
- `filters.yaml` 里加 review 开关/模型配置（v1 先用 CLI flag）
- TMTB 手动路径 / Claude Code 直接生成的 digest 也走 reviewer
- A/B 评测：reviewer on/off 两版给 judge_digest.py 打分
- 分段审查（per-section）替代整篇——若整篇 sonnet 漏改率高再考虑
- reviewer prompt 迭代：观察几天真实输出，补充新发现的 AI 腔 pattern

## 进度
- ✅ Phase 1：`reviewer.py` + `scripts/review_digest.py` 已建，sonnet 冒烟测试链路通（gate PASS / 回退就位）
- ⚠️ 发现：sonnet 在 review prompt 下会**改语义**（「是…的直接证据」→「势头仍在加速」）且漏改破折号；
  opus 更忠实。安全闸保链接/图片、**保不住语义** → review 模型档位待定（opus vs 加硬铁律重试 sonnet）
- ⏸️ Phase 2/3（wire 进 legacy/v3）暂缓

## 当前任务：今天(06-08)双版本发飞书（**均不加 review**）
- 「优化前 legacy」= legacy CLI，无 review
- 「优化后 v3」= 完整 v3 pipeline（手动驱动），无 review
- 版本号标题里；返回两个飞书 doc URL

## Review
（实现后补）

---

# 2026-06-15 多源主题识别优化（multi-source theme elevation）

**目标（唯一）**：被 ≥2 个来源（不同 source_slug）共同提到的**主题**，应被识别为高重要度
→ 上浮 + 独立 headline + 分点写出共识/分歧。当前 v3 只在 **ticker** 维度算 multi_source，
**主题级**多源（800VDC / 存储超级周期 / 政策 read-through）全漏 → 被压进无分点 prose 尾部。

**根因**：抽取是**逐封邮件**做的（per-email route），"多"这个维度结构性不可见；
route_merge 代码补算只认 **ticker 重叠**，不认**主题重叠**。legacy 单脑看全部能直接感知主题级多源。

**两层修复**
- 层 A（抽取层，对应"单封邮件抽取的问题"）：让 route 在单封内就抽出**主题标签**，把"这块属于什么主题"显式化。
- 层 B（归并层，"多"唯一能算出的地方）：跨邮件把同义主题聚到一起，≥2 source 的主题标 multi-source-theme，
  固化进 route_map，驱动排序 + section 写法。

**设计岔路（待定）**：主题聚类用代码还是 LLM？
- MVP = 代码 normalize + 精确/别名匹配（便宜、确定、可重跑）。
- 升级 = 一个 cheap LLM `theme_merge` subagent（只喂 {chunk_id, source, ticker, theme, 一行 gist} 紧凑元数据 ~221 行，**不喂全文**）聚同义主题。
- 推荐：**代码优先**，检查点看 800VDC 抓没抓到，漏同义词再上 LLM。

- [x] **Phase 1 — route 抽 theme（抽取层）** ✅ route.md 加 `<theme>` 段 + schema `theme` 字段；7 路由 agent 重跑，theme 标签率 6/45~28/34 不等
- [x] **Phase 2 — route_merge 归并主题（代码）** ✅ `_norm_theme`/`_clean_theme` + 4b theme 分组 + `_primary_sort_key` +300 + sections_input 带 theme/theme_multi_source + stats
- [x] **检查点（跑 2026-06-15 对照）✅ PASS**
  - 检出 5 个多源主题：`800VDC`(2源) / `AI capex`(4) / `GaN专利`(2) / `SPE涨价`(2) / `存储超级周期`(2)，theme_multi_source_items=17
  - **800VDC：pos 48/49 → pos 13/18/19 of 75**（脱离尾部，进 top quartile，3 块连续 → 可成块）
  - 已知边界：0031 用 `AIDC供电`、0824/1147 用 `800VDC`——同义/不同粒度未合并（代码精确匹配的固有局限，需 LLM theme_merge 才能跨语义合并）
  - ⏸ 待用户定 section 写法"算对"标准，再 wire 进 Phase 3
- [x] **Phase 3 — section 写法** ✅ master.md §一 加 `theme_multi_source` 规则（同主题聚一起、各自成 bullet、不折叠不删）+ §四 删除规则例外；6 section agent 重跑
  - 结果：semi 5 个多源主题全部成 `### {主题}` block + 分点（`### 800VDC` 从尾部 prose → 独立 block + 3 bullet 列 bull/bear/trade）；rubric「multi-source theme 有自己的 bullets」达成
  - 最终 digest 374 行 / 90,712 字（vs pre-theme 351 行 / 80,907）
  - [ ] （deferred）代码聚类漏同义主题（`AIDC供电` vs `800VDC` 未合并）→ 需要时再插 LLM `theme_merge` subagent

## 状态：✅ Phase 1-3 完成（代码路径），待用户决定是否 re-publish + commit

## Deferred / 待用户定
- **成功标准由用户先写**（feedback_user_authors_eval_rubric）：800VDC 这类"算正确处理"长什么样？必须独立 headline？分歧必须分点？
- sort 权重具体数值 / 主题别名词典（800VDC≈800V DC≈±400V）维护方式
- 主题级多源是否也该反哺 catalyst / TL;DR
