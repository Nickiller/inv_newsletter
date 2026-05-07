# Few-Shot Examples — Staging（暂未接入 system）

> **状态**：留存草案，**当前未注入 user message**。
> **激活方式**：未来在 `summarizer.py:_build_content_blocks()` 头部插入一个 text block，包裹本文件内容并加 `cache_control: ephemeral`。
> **注入时必须加免责框架**：
> > 以下是历史 digest 中精选的优质表达范例，**仅供参考结构、信息密度与表达手法**。**严禁复用其中的具体公司、数字、结论** —— 本日 digest 内容必须基于本日邮件。

---

## 范例 1 — 二元 thesis 子分组（财报反应）

**示范规则**：§4.B 二元对立 thesis 用粗体小标题分组
**形态**：财报后即时反应 + "市场担心 vs 实际 miss" 拆解
**改编自**：2026-04-28 SPOT Q1（原版平铺难读，改写为二元子分组）

> **SPOT —— 盘前 -12%，crowded long 典型回调。核心矛盾不在 MAU，在 margin。**
>
> **实际 miss（pricing / margin 端）**
> - Q2 GM 33.1%：与 Street in-line，但低于 buy-side 33.3-33.5% 区间（市场期望 US 提价更快传导）
> - Q2 EBIT €630M vs Street €675-712M，miss 7%（GM 不及预期是主因）
>
> **原本担心但其实过关（user metrics 端）**
> - Q1 net adds 3M（vs buy-side 4M），但 Q1 GM 33.0% beat guide 20bps
> - MAU guide +17M QoQ（明显好于此前担忧，Street +15M）
>
> Bernstein 视 -12% 跌幅为行业龙头的极具吸引力的入场点。

**关键观察**：标题句直接抛 thesis（"核心矛盾不在 MAU，在 margin"），两个粗体子标题让结构本身承担分析意图，读者不需要自己重排数据。

---

## 范例 2 — 跨实体对比表格（cross-company synthesis）

**示范规则**：§4.A ≥3 实体 × ≥2 维度时考虑表格 + 必接 commentary
**形态**：跨公司主题汇总
**改编自**：2026-04-30 Hyperscaler Capex（原版 5 个并列 bullet，改写为表格）

> **2026 主要 hyperscaler capex 合计 >$700B**（JPM Harlan Sur 测算），各家中值普遍上修，memory / HBM 元器件涨价穿透各家成本结构。
>
> | 厂商 | 2026 区间 | 此前 / Street | 关键变化 |
> | --- | --- | --- | --- |
> | META | $125-145B | 中值 +$10B 上调 | memory 涨价为主；上调幅度超 GOOGL |
> | GOOGL | $180-190B | 此前 $175-185B | **2027 将"显著高于" 2026**，买方测 ~$280B (+50%) |
> | MSFT | ~$190B (CY26) | FY27 Street $150-160B；买方原预期 $190-200B | 含 $25B 元器件涨价；料需上修 |
> | AMZN | 保持不变 | — | "AWS 增长越快，短期 capex 就越多" |
>
> **关键引语（META Q1 call）**："Our experience so far has been that we have continued to underestimate our compute needs, even as we have been ramping capacity significantly."

**关键观察**：4 家 × 3 维度（区间 / 此前 / 关键变化）触发表格条件；表格后必接 commentary（共性归因 + CFO 原话），表格不孤立。

---

## 范例 3 — 单句最大密度（数字序列 + 显式乘法）

**示范规则**：§4.C 数字趋势优先级（序列 > 乘法 > delta > 区间 > 单点）
**形态**：单句最大密度
**原文出处**：2026-04-15 Memory 板块 / Michael Dell 原话

> Michael Dell：H100 时代每颗加速器 ~80GB HBM → 当前 288GB → 明年 1TB → 后年 2TB，加速器数量提升 ~25x，memory 需求为 **625x**。新建 memory 厂通常需 4 年，2023 年行业巨亏 $400 亿令厂商至今偏谨慎。

**关键观察**：一行字带 4 个时间点的等比序列 + 一个乘法推理（25x × 25x = 625x）+ 供给侧约束（4 年建厂 + $400B 亏损记忆）。这是单句呈现"现状 → 趋势 → 含义"完整论点的标杆。

---

## 范例 4 — 单 Ticker 时间序列模型

**示范规则**：§4.C 时间序列 + §3 信息密度
**形态**：单 Ticker 动态轨迹 + 失速归因 + 竞品定位
**原文出处**：2026-04-28 MSFT Copilot seat

> - **FundaAI 与四位专家交流重建的 Copilot seat 模型**：总席位从 2024/12 的 630 万 → 2025/3 的 960 万 → 2025/6 的 1240 万 → 2025/9 的 1510 万 → 2025/12 的 1810 万 → **2026/3 约 2200 万**。FY26Q3 未达目标（Copilot Cowork 4 月才发布、M365 续约集中 6-7 月、企业裁员拖累 seat）
> - 久谦渠道专家称本季度环比新增约 500 万席位（上季度仅 +300 万），预计 FY26Q4（今年 Q2）可达 3000 万（+700 万）
> - **E7 许可预计 5/1 推出，定价 $99**（vs E5 $57 / E3 $36），最大卖点为 Copilot Workspace。调研显示 Copilot Workspace 评分约 3/5（vs Claude Workspace 4.5/5），差距在调度层而非底层模型

**关键观察**：6 个时间点 seat 数 + miss 原因（产品发布节奏 / 续约 / 裁员）+ 价格阶梯（$36/$57/$99）+ 用户评分对比（3 vs 4.5）。一个 Ticker 写出动态轨迹、失速归因、竞品定位三层。

---

## 范例 5 — 多源交叉（共识 vs 分歧）

**示范规则**：§2 多源交叉显式标共识/分歧
**形态**：卖方对立观点
**原文出处**：2026-04-30 META Q1 财报后 JPM 下调 + Bernstein 维持

> - Q1 Revenue 基本 in-line 但为 5 个季度来首次 miss 指引高端
> - **Capex 中值上调 $10B 至 $125-145B**（元器件成本涨价，memory 为主），超出 GOOGL 上调幅度
> - 买方 2027 EPS 由 $36-38 降至 $34-36（-5%）
> - **Doug（JPM）D/G 至 Neutral，PT 由 $825 降至 $725**：理由——Google / Amazon Cloud 显著加速（GCP backlog 环比近翻倍，AWS backlog 环比 +50%），提供多年 AI Capex ROIC 可见性；META 在广告之外的 AI Capex 回报路径更艰难
> - Bernstein 相反观点：Mark Shmulik 仍买 dip，理由 1）收入杠杆已现 2）Spark Muse 已上线 3）Susan 重申 META 若需可下调 2027 Capex

**关键观察**：分歧不是"JPM 降评 / Bernstein 维持"两条平行 bullet，而是**直接点出对立的 thesis**：JPM = "META 没有 cloud-like ROIC 可见性"，Bernstein = "收入杠杆 + 产品上线 + capex 灵活性"。读者一行能看到双方的核心论据，自己判断站哪边。

---

## 范例 6 — 结构性 context（产业链知识图谱）

**示范规则**：§3 信息密度 + 久谦专家纪要的最佳形态
**形态**：供应链拆解（架构 → 产品代际 → 单位经济 → 市场结构 → 总需求）
**原文出处**：2026-04-28 欧陆通 PSU 久谦专家纪要

> - Google v7 采用 64 芯片机柜架构，单芯片 850-950W，整柜 ~100kW，配 21 个 5.5kW PSU（N+2 冗余）
> - **v8 已于本月发布**，训练性能与每瓦性能提升约两倍，电源效率达 97.5%，每柜 22 个 8kW 模块
> - 5.5kW 单模块售价 ~7500-7800 元（单瓦 ~1.4 元），v7 毛利率 ~26%；8kW 单模块 ~1 万元，v8 毛利率 ~30%
> - **欧陆通为 Google 二供**，当前份额 10%-15%（目标 20%），台达为一供占 70%-80%；v8 阶段份额预期降至 5%-10%
> - 今年 Google PSU 需求 5-8 万台，全年给 Google 供货 5-6 万台（框架协议，去年底签订），Q2 交付约 2 万台，Q3 约 3-4 万台
> - **行业两年增速 80%-90%**，内部预期 Google 2027 年约 1000 万颗
> - 越南现有 AI 产线 ~5 条（一期 2 条 + 二期 3 条在建），年产能峰值 80-100 万台，可扩至 40-50 条产线

**关键观察**：把整个 Google TPU 电源供应链画出来 —— 架构（机柜级电气参数）→ 产品代际（v7 → v8）→ 单位经济（单价 / 毛利）→ 市场结构（一供二供比例）→ 总需求（台数 / 产能）。这是 PM 看 sell-side 永远看不到的产业链深度。**久谦类型 bullet 的标杆。**

---

## 形态-规则映射速查

| 范例 | 主示范规则 | 触发场景 |
| --- | --- | --- |
| 1. SPOT 二元分组 | §4.B 二元 thesis 子分组 | 财报反应 + "市场担心 vs 实际 miss" |
| 2. Capex 表格 | §4.A ≥3 实体 × ≥2 维度 | 跨公司同主题对比 |
| 3. HBM 序列 | §4.C 序列 + 显式乘法 | 单句承载多步推理 |
| 4. MSFT seat | §4.C 时间序列 + §3 信息密度 | 单 Ticker 动态轨迹 |
| 5. META 分歧 | §2 多源交叉 | 卖方对立观点 |
| 6. 欧陆通 PSU | §3 信息密度（久谦类型） | 产业链知识图谱 |

---

## 启用 Checklist（未来接入时）

- [ ] 在 `summarizer.py:_build_content_blocks()` 顶部新增 text block，载入本文件
- [ ] block 加 `cache_control: {"type": "ephemeral"}`（独立 cache breakpoint）
- [ ] block 头部加免责框架（见本文件顶部引用）
- [ ] 跑 1-2 次 dry run，对比加 vs 不加范例的输出差异
- [ ] 观察是否出现过度锚定（具体公司 / 措辞被复用），如有则砍范例数量
