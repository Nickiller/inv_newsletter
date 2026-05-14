# Digest Quality Rubric

> 这份文档由你（用户）填写，不要让 LLM 帮你填具体内容。Claude 只负责**把你写的标准 encode 到 judge prompt**，不替你定义"好"的标准。

## 使用方法

1. 每个 axis 你给出 1 / 3 / 5 分各自的**具体行为描述**（不要用形容词，用"读者看到什么"来描述）
2. 每个 axis 尽量锚定一个 anchor example —— 直接引用 `output/daily/2026-05-11_daily_digest.md`（你视作 gold standard）或 `output/daily/2026-05-13_daily_digest.md`（当前 weak）里的具体行号 / 段落
3. 不用怕重叠 —— judge 会对每个 axis 独立打分
4. 写完后 Claude 把这个文件**逐字** encode 进 `scripts/judge_digest.py` 的 judge prompt，不会"优化"你的措辞

---

## Part A — TL;DR / 今日要点 section（仅评分顶部速读段）

> 评分对象：digest 最上面的 `## 今日要点` section。Sector 内容由 Part B 评。
>
> **整体风格定调**（来自用户对样本的评价）：
> - **Lean bullets 远胜于 dense thesis-tagged paragraphs**（V1 4/5 vs V2 1-2/5）
> - **不要 ✅加强 / ⚠️减弱 标记**，**不要** "long X / short Y" tag
> - **每条只列相关 ticker / 公司**，不映射到 L/S
> - **3-5 条**，按重要性降序
> - **可用 sub-bullets** 把一条 headline 拆开（粗体 headline + 2-3 个 sub-bullet）
> - **去 AI 味儿**：拆短句而不是 `..., 但...` 长串；中文连接词；缩写说人话（"MT" → "中期"）

### Axis A1: Scan-first 可用性 — "PM 60 秒内能否抓住当日 top 3-5 信号？"

- **5 分（优秀）**：
  - 3-5 条粗体 headline，每条 < 1 行扫到 ticker + 事件
  - 每 headline 下可有 2-3 个 sub-bullet 承载数据（如 `5/13 V1` 中第一条若拆为：DRAM/NAND q/q 涨幅 + HBM4 谈判 + SK Hynix 当日表现 → 三个 sub-bullet）
  - 整段 PM 60 秒内能扫完，看到当日要做什么决策

- **3 分（凑合）**：
  - 数据齐但密度太高需要二次阅读（如 `5/13 V1` 现状 —— 一条信息塞一段，没拆 sub-bullet）
  - 或拆得太散，逻辑链断了（每个数据一个 bullet，没有 headline 收拢）

- **1 分（不及格）**：
  - dense 段落（`5/11 V2 native` 那种）—— 每条 100+ 字密度段落 + ✅/⚠️ 双行子 bullet，PM 扫不快
  - 或完全没有 TL;DR（`2026-05-13_daily_digest.md` 现状）

Anchor:
- **强**：`evals/tldr_samples.md` 中 `5/13 V1` 的方向 + sub-bullet 化（用户给 4/5，期望"细分 bullet point 显得更清楚易读"）
- **弱**：`5/11 V2 native`（用户给 1/5："内容冗长，加强/减弱标记看着很累"）

### Axis A2: 信号选择 + 排序

**重要性优先级**（用户 5/13 重排）：
1. **AI 模型 / capex / 算力需求**（mega-cap pull-forward 头号信号 —— 如 Anthropic 估值跳升、OpenAI Stargate 250GW、字节 capex +25%）
2. **NVDA 供应链 / 半导体大趋势**（与上条可合并 —— 如 NVDA $95.2B commitments + Jensen 访华团）
3. **存储 / 半导体核心议题**（super-cycle / 罢工 / pricing）
4. **光通信 / 设备 / 产业链拐点**
5. **CPU TAM / 长尾估值重估**
6. **Software 分化** 排末位

- **5 分**：
  - 前 1-2 条命中 AI/算力 + mega-cap pull-forward 类信号（对全市场预期有影响）
  - 相关相邻信号可合并（如 NVDA 供应链 + 模型算力需求可成一条）
  - 排序遵循上面优先级；分歧空间体现为合并而非堆叠

- **3 分**：
  - 重要信号都在但顺序错（如把 Software 分化排前 NVDA capex）
  - 或漏了 1-2 个明显应该入选的（如 Sam Altman 250GW 这种对市场预期有影响的）

- **1 分**：
  - 选了不该入选的（如 5/11 中 "Analog 二轮提价" 这种非市场级影响的入了 top 5）
  - 或 top 5 里有重复 / 同主题被拆成多条

Anchor 提示：
- 用户对 5/13 重排：`AI模型+NVDA算力 / 存储 / 光 / CPU / 软件`
- 用户对 5/11 异议：`Analog 二轮提价不是特别重要`，不该排前 5
- 重要性判据：**对全市场预期的影响 > mega-cap 含量 > 新进展（非常规跟踪）> 股价异动**

### Axis A3: 相关 ticker 列出齐全 — "每条是否把涉及的公司 / ticker 列全？"

> **不要** 加 ✅/⚠️ 也 **不要** long/short tag。只要把当条信号涉及的相关 ticker 列出来即可。

- **5 分**：
  - 每条 headline 末尾或 sub-bullet 里清楚列出 2-5 个相关 ticker（如 "long HBM/DRAM/NAND（SK Hynix、Micron、闪迪、兆易）"），但**不带 long/short 字眼**
  - 中外股票都覆盖到位（如光通信主题应有 LITE/COHR/中天/亨通）

- **3 分**：
  - 有 ticker 但只列 1-2 个核心代表（漏了周边受益方）
  - 或者 ticker 列在密度段落里读者要自己挑出来

- **1 分**：
  - 完全没列具体 ticker，只说 "long memory" 或 "看好半导体"
  - 或者明明是 5 条 TL;DR 写得很长但每条只有 1 个 ticker

### Axis A4: 措辞自然度 — "有没有 AI 味儿 / 研报套话？"

> 用户原话："还是有一些 AI 味道"，举例：
>
> ❌ `AMD 指 2030 CPU TAM >$120B、份额 35%+；久谦测算位于 Base/Bull 之间，2027 估值仍有上修；INTC YTD +250% 转为 "forced to own"，但 MT 基本面与估值脱节`
>
> ✅ `AMD 给出 2030...; ...; JPM 提出 INTC...，但中期基本面与估值脱节`

- **5 分**：
  - 短句、中文连接词为主，英文术语只保留 industry-fixed 的（buy-side、guide、ramp）
  - 缩写说人话（"MT" → "中期"，"NN ARR" → "净新增 ARR"）
  - 主语清楚（"AMD 给出..."、"JPM 指..."），不堆 "..., 但..., 同时..." 长串

- **3 分**：
  - 偶尔出现 "..., 但..., 同时..." 长串
  - 个别缩写没展开（如 "MT 基本面"）
  - 个别中英夹杂日常词（"其实 fine"、"easily better than"）

- **1 分**：
  - 整段堆砌 "..., 但..., 同时..."
  - 大量未展开的 sell-side jargon（"setup"、"derisked"、"bogey"）
  - "我们持续看好"、"维持关注"、"建议重点跟踪" 等研报套话

---

## Part B — Sector rubric（对每个 `## sector` 独立评分）

> 评分对象：`## AI 模型与平台`、`## 半导体与硬件` 等每个 sector section。Judge 会逐个 sector 跑这套 rubric。

> **整体风格定调（来自用户对 sector samples 的评价）**：
> - **段落 flow > sub-bullets**（V1 4/5 vs V2 2/5）—— sector 内容偏好 V1 的 flowing paragraph 而非 V2 的 sub-bullet 拆碎
> - **但每个 #### 要有 V2 风格的 headline 句**：`公司名 — 当日表现 + 一句核心论点`（V2 这部分用户明确说"保留，V2 格式就很好"）
> - **理想 = V1 paragraph body + V2 headline 句 hybrid**
> - **Preamble 放主题开头**（V1 默认，用户没异议）
> - **表格**（≥3 实体 × ≥2 维度）用户认可，保留
> - **每个 ticker 都要有标识**：major ticker 用 `####`，minor ticker 用 bold bullet 前缀（如 "- **SNDK / MU**: ..."），**不要把多个 minor ticker 揉成一段没有 ticker 标识的散文**
> - **同 ticker 跨段重复 → 合并到一处**（不是加 cross-ref，是直接整合内容到主 #### 段）

### Axis B1: Theme 内 Ticker 排序 — "lead ticker 是当日最该读的吗？"

**排序优先级（修订）**：

1. **公司 fundamental 重要性 + AI 时代相关性**（**主排序**，不是 tie-breaker）：
   - mega-cap：NVDA, AMZN, GOOGL, META, AAPL, MSFT, TSLA, BABA
   - AI 时代关键中盘：AMD, AVGO, MU, SK Hynix, Samsung Electronics, TSMC, Anthropic/OpenAI proxies (MSFT/GOOGL holders), DDOG, ServiceNow 等基础设施/应用领头羊
   - 这一档公司**即使当日没有大动作也应靠前**——它们是 PM 每日必读的 anchor
2. **当日 mover / 事件强度**（次排序，在档内细分）：股价 ±5%+ / 财报 / guide change / 罢工 / 多源覆盖
3. **信息密度 / 深度拆解**（meritco 纪要、买方独家数据）
4. **次要 / 单源 niche ticker**

**关键修订（来自用户 spot-check）**：**公司重要性 > 当日动作**。Mercari +10% 当日是 mover，但 AMZN/BABA mega-cap 应排前。NOW 当 lead 合理（公司本身重要），不必让位于 DDOG ATH / HUBS -19%。

**评分时的 B5 排除规则**：评 B1 不要把 B5-错位的 ticker 当作反例引用。先 mentally 排除"不该在这 section"的 ticker（如 CRCL 不该在 `## AI 模型与平台`），再判断剩余 ticker 的排序。

- **5 分**：lead 是 mega-cap 或 AI 时代关键中盘，且其当日有动作（财报/事件/股价）；后续按"重要性 > 当日 mover"递减
- **3 分**：lead 是 sector 内重要 ticker（合理）但选错了细分（如 lead 选了 mega-cap 但当日完全没动作而忽略了一个真正在动的 mega-cap）；或者后续 ordering 按 source 顺序
- **1 分**：lead 是单源 niche / 私募公司 / 非 sector 主流 ticker，盖过明显应该领衔的 mega-cap

Anchor：
- 用户原话："按 V2 逻辑排序，同时考虑公司的重要性"（5/13 存储 theme）+ "BABA/AMZN 这些 AI 时代更重要的放在前面"（5/13 互联网）
- 5/11 软件 NOW 当 lead = **合理**（公司本身重要），不应扣分

### Axis B2: #### 写法（headline + paragraph flow）

**理想格式**：

```
#### {公司名} — {当日股价 / 关键数字} + {一句核心论点}

{段落 1：事件 / 数据展开}

**{粗体小标题}**：{段落 2：另一个维度的论证}

[必要时插入表格 / 数据]

{段落 3：含义 / cross-source 共识 / 估值结论} [链接]
```

例 5 分（V2 headline + V1 body 的 hybrid）：
> #### Samsung Electronics — 盘中蒸发 $66B 后收复，罢工反成 pricing 催化
>
> 劳资谈判破裂为当日核心事件，但市场对长期停工概率定价已显著回落。
>
> **事件链**：政府调解破裂，NSEU 罢工 5/21-6/7（18 天、~50k 人参与）... [3 个链接]
>
> **JPM 量化测算**（buy the dip）：
>
> | 情景 | DRAM | NAND | ... |
> | ... | ... | ... | ... |
>
> JPM 关键交叉信号：2Q26 memory 合约价格远超预期（DRAM +58-63% q/q）... 完全对冲...

- **5 分**：headline 句直接打数字 + 论点；body 是段落 flow 不是 sub-bullet 散点；粗体小标题（**事件链** / **JPM 量化测算**）切分大段但保持论证连贯；表格触发条件命中时才用
- **3 分**：有 headline 但 body 被切成太多 sub-bullets（V2 那种过碎）；或 body 有段落感但 headline 缺失，读者得自己提炼
- **1 分**：无 headline + flat paragraph 一段读不完（V1 缺失 headline 状态）；或全部用 sub-bullets 拆散没有段落论证

Anchor：
- V2 的 `公司名 — 当日表现 + 一句核心论点` headline = 5 分组成部分
- V1 的 flowing paragraph body = 5 分组成部分
- "..., 但..., 同时..." 长串 / 研报套话（"我们持续看好"、"维持关注"）= 直接降分

### Axis B3: 覆盖完整性 — "当日 mega-cap / 多源共识 / 财报 / guide change 有没有被错过？"

> 此 axis 需要 judge 对照源邮件才能精准评分；当前先按 judge 的常识打。后续可接入 source-email packet。

**B5 chain 规则（关键）**：评 B3 时**先 mentally 排除 B5-错位的内容**——错位 ticker / 主题出现在该 section 不算"覆盖到位"。例：宏观 section 里塞满半导体/光纤/机器人久谦内容，**不能因为内容多就给 B3 高分**——这些内容属于其他 sector 的覆盖范围，本 section 实际的宏观覆盖反而可能很弱。

- **5 分**：当日**该 sector 真正属于的** mega-cap 财报 / guide change / 多源覆盖事件都有出现；新进展（vs 前日）被点出；没靠错位内容"凑数"
- **3 分**：主要事件覆盖到，但漏了某个 mega-cap 跟踪或多源信号；或部分覆盖来自错位内容
- **1 分**：明显的当日 mover（±5%+ 股价 / 财报）没出现；或大部分内容都是错位塞过来的"虚假覆盖"

### Axis B4: 反冗余 — "同 ticker 跨段重复有没有合并？"

> 用户原话："可以合并到一处，其他部分该提就提"。意思：**主信息合并到一处**（通常是 ticker 自己的 #### section），**其他段需要时才简短提及做 context**。

- **5 分**：SK Hynix 类 ticker 的核心信息合并到自己的 #### 段；其他 #### 段（如 Samsung）提到 SK Hynix 时只一句话做 context（不重复价格 / 归因），不需要 "详见上文 X 段" 这种 explicit cross-ref
- **3 分**：核心信息基本合并但有 1-2 处重复（同一 +7.7% 解释出现在 2 个段落）
- **1 分**：同 ticker 的实质性信息散落 3+ 处（5/13 baseline 状态：SK Hynix 在 preamble / 自己 #### / Samsung #### / 其他存储相关 都有实质内容）

### Axis B5: Theme 归类正确性 — "ticker 是不是放在了正确的 theme？"

> 用户在 5/13 sector samples 评价中发现：**NBIS 被算在存储 theme，但它是 GPU cloud（neocloud），应该归在 `### 先进 AI 算力 / GPU 供应链` 而不是 `### 存储超级周期`**。
>
> 这是 theme integrity 问题：theme 划得不对 → 读者 mental model 错位。

- **5 分**：每个 ticker 都在它"业务定位"的 theme 里；如果有 read-through 关系（NVDA 投资 GLW → APH bear narrative），按"被影响的板块"放，不按"事件源板块"
- **3 分**：1 个 ticker 归类略偏但还能理解（如把 ASML 放在 Foundry 主题 vs 单独设备主题，可接受）
- **1 分**：明显错位 —— NBIS 在存储 theme（它是 GPU cloud）/ TSLA Robotaxi 数据放在半导体（应在互联网）/ 久谦机器人放在半导体（应在 `## 其他`）

Anchor：
- **错例 1**（用户实际发现）：5/13 NBIS 出现在 `### 存储超级周期 + LTA 重估 / #### 其他存储相关`，应迁移到 `### 先进 AI 算力 / GPU 供应链`
- **正例**：5/13 NVIDIA 在 GPU 供应链 theme 而不是 AI 模型 theme（它做硬件不做模型）

---

## Part C — Weights（可选）

如果某些 axis 比其他重要，写出来（默认全 1.0）：

- TL;DR axes: A1=__  A2=__  A3=__
- Sector axes: B1=__  B2=__  B3=__  B4=__

---

## Part D — Calibration set（填完 Part A/B 后操作）

填完后，你手工给以下 3 份 digest 按 rubric 打分（每份 ~10 分钟）：

- `output/daily/2026-05-11_daily_digest.md` —— 你的 gold standard
- `output/daily/2026-05-12_daily_digest.md` —— 中等
- `output/daily/2026-05-13_daily_digest.md` —— 当前 weak

每份产出一个 `section × axis` 的打分矩阵。Claude 然后跑 judge 对同样 3 份打分，调整 judge prompt 直到 judge 每个 cell 跟你的分差 ≤ 1 分。校准完，judge 后续 iteration 自动跑。

---

## Part E — Open thoughts（自由发挥）

> 想到任何关于 digest 质量、但不属于上面任何 axis 的偏好 / 红线 / 个人喜好，写在这里。Claude 会判断是 encode 进 judge 还是塞进 digest prompt 本身。
