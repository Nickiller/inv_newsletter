# Evidence Rules

本文件定义**多源交叉、链接保留、图片引用**的硬性规则。所有 Stage B 板块起草调用必读此文件。

## 1. 多源交叉（共识 vs 分歧）

同一 Ticker 有多家卖方 / 久谦覆盖时，**必须**显式标出共识或分歧，**不要**把不同来源观点平铺成两组无关 bullet。

- **分歧时**点明分歧点：
  > `Jefferies 看多 vs. JPM 谨慎，分歧主要在 Q3 guidance 假设的合理性`
- **共识时**也明确标出"两家共识"：
  > `Jefferies 与 JPM 均强调 NRR 见底，差异仅在节奏`

**写作时必须诚实**——只有 packets 中 cross_source 标记为 ≥2 源时才能写"两家共识 / 多家覆盖 / 卖方分歧"等措辞。Stage C 会跑 validator 核对，错误声明会被标记。

## 2. 链接保留与格式

### 2.1 必须保留的链接类型

原邮件中出现的**所有链接都必须保留**，包括：

a. **主流媒体**：WSJ、Bloomberg、CNBC、Reuters、FT、Digitimes、TheRegister 等
b. **社区/博客**：TMTB Chat、Tae Kim、Semianalysis、FundaAI、Substack、x.com 等
c. **卖方研报正文链接 ⚠️ 最重要**：
   - Jefferies: `https://jefferies.email.streetcontxt.net/...` 或 `javatar.bluematrix.com/...`
   - JPM: `https://markets.jpmorgan.com/research/email/...` 或 `morganmarkets.com/...`
   - Bernstein / MS / GS 等其他卖方的 research portal 链接
   - **锚文本陷阱**：原邮件常以 inline 短词承载，如 `[notes](...)`, `[here](...)`, `[link](...)`, `[report](...)`, `[preview](...)`, `[piece](...)`, `[更多](...)`。**不要**因为锚文本看起来像导航词就丢弃 URL——这些恰恰是研报正文链接，对读者最有价值。
d. **公司官网/IR**：press release、blog、SEC filing 等

### 2.2 链接格式

- 紧跟在对应内容 bullet 末尾，**用有意义的来源名而不是原始锚文本**
- 例：原文 `Brent [notes](https://jefferies...)` → 总结中写 `... [Jefferies 研报](https://jefferies...)` 或 `... [Jefferies — Brent](https://jefferies...)`
- 同一条内容若有多个来源链接，全部并排列在该 bullet 末尾

### 2.3 严禁

- **严禁**单独起一个 bullet 只列链接（例如 `- [CNBC](...) [WSJ](...)` 这种是错的）；链接永远和具体内容在同一行
- **如果已有具体链接，不需要再附加** `*来源：XXX (MM/DD)*`；只有在没有任何具体链接时，才在末尾加 `*来源：{邮件标题简称} ({日期})*`

### 2.4 示例

正确 ✅：
```
- DeepSeek 发布 V4 预览版，外媒普遍视为中国 AI 竞争升温的标志 [CNBC](https://...) [WSJ](https://...)
- 加剧模型层竞争和价格压力，企业采购更愿意保留多模型选项
```

错误 ❌：
```
- DeepSeek 发布 V4 预览版
- 加剧模型层竞争和价格压力
- [CNBC](https://...) [WSJ](https://...)      ← 禁止：链接不能独立成 bullet
```

无链接：
```
分析师认为软件名义将滞后 *来源：Jefferies (04/01)*
```

### 2.5 久谦论坛纪要

每条纪要都附带 `source_url`（meritco-group.com 链接）和 `date`。归类到对应 Ticker 下时**必须**引用 source_url，格式：

```
[久谦纪要 — {专家简称}](source_url) *(MM/DD)*
```

例：
```
Agent 试点占比 45% [久谦 — Cognizant 离职专家](https://research.meritco-group.com/forum?forumType=2&forumId=3114) *(04/23)*
```

纪要为专家 Q&A 格式，提取关键数据点和结论即可，不需要保留问答原文。

## 3. 图片引用三条硬性规则

每张图片都有唯一 ID（如 `IMG_01`），完整可用清单会在 user message 末尾给出。

1. **严禁引用清单外的 ID**（如清单只到 IMG_06，禁止写 IMG_07/IMG_08...）
2. **每个 IMG_XX 在整个输出中至多引用一次**，禁止换 caption 重复使用同一 ID
3. **caption 必须与图片视觉内容一致**（看图本身判断，不能因为临近的文字段落是某个主题就硬塞 ID）

找不到内容匹配的真实图片时，用纯文字描述数据点替代，不要硬塞图片引用。

### 3.1 图片嵌入格式

当某张**实际可用**的图表对分析有价值时，用 markdown 图片语法嵌入：

```
![简短描述](IMG_01)
📊 Mag7 composite sentiment 当前约 -0.7，接近 max bearish（-1），为 2023 年以来最低。
```

紧跟一段文字描述图表关键数据点（具体数字、百分比）和趋势。

### 3.2 不嵌入的图片类型

不要嵌入 logo、签名、广告等无信息量的图片，只嵌入图表、数据表格、定价截图等有分析价值的图片。
