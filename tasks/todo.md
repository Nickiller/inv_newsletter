# Email .md 预处理与清洗

## 目标
1. 自动剥离卖方邮件末尾的 disclaimer / 合规条款 / 销售联系人块（噪音占比常>50%）
2. 对结构特别糟糕的发件人（首要案例：JPM Tech Sketch）做内容重排，提升可读性
3. 与 `fomo_format.py` 同层组织，统一作为"邮件 .md 数据预处理与清洗"模块

## 设计

### 模块划分
```
src/inv_newsletter/preprocess/
  __init__.py          — 公开入口 preprocess_email(content, sender_address) -> str
  disclaimer.py        — strip_disclaimer(content) 通用 disclaimer 切除
  fomo_format.py       — 现有逻辑迁入（不改实现，仅移位置）
  jpm_format.py        — JPM Tech Sketch 重排（Phase 2）
```

`storage.py` 调用单一入口：
```python
from inv_newsletter.preprocess import preprocess_email
md_content = preprocess_email(md_content, email.sender_address)
```

### Phase 1 — 通用 disclaimer 切除 (universal)

**逻辑**：在 markdown 正文中找到最早出现的"硬切点"标记，从该位置截断到文档末尾。Frontmatter + `# 标题` 之上的所有内容全部保留。

**硬切点正则（大小写不敏感）**——LLM 抽样后总结：

| Pattern | 来源 | 备注 |
|---|---|---|
| `\bDisclaimers?:` | JPM (Tech Sketch + Chips for Breakfast)，所有 JPM 邮件都出现 | 最强信号 |
| `Sales & Trading Disclaimer:?` | JPM 二段 | 偶尔单独出现 |
| `FOR INSTITUTIONAL & PROFESSIONAL CLIENTS ONLY` | JPM | 兜底 |
| `The information provided herein was prepared by` | Bernstein | 100% 命中 |
| `This communication is not a research report` | Bernstein backup | |
| `Link to Disclaimer:` | Jefferies（直发 + ETNAlabs 转发） | 在 events 之后、italic 法律段之前，是 Jefferies 的清晰切点 |
| `\*?This material is a product of .+ Sales and Trading` | Jefferies italic 法律段 | ETNAlabs 转发版的兜底 |
| `^Disclaimer:\s*\[?http` | Jefferies 直发末尾 | 行首 `Disclaimer:` 后跟链接 |
| `© 20\d{2} .+ All rights reserved` | 通用版权行 | |
| `IMPORTANT (DISCLOSURES?\|DISCLAIMERS?)` | 通用 | |
| `Tech Sector Specialists:` | JPM | 在 `Disclaimers:` 之前，可选更紧的切点（去掉 sales contact 块） |

**Stratechery / FOMO / Meritco** 不命中上述任何 pattern，安全。

**安全防护**：
- 切点之后被去掉的内容必须 < 当前正文的 70%（防止误切：如果切点出现在文档前 30%，说明命中了正文里某个引用，不切）
- 切点之前必须有 ≥ 200 字符正文（防止整个邮件变空）
- 同时找到多个切点时取最早的

**测试样本**：
- JPM (`1208-jpm-tech-sketch...`) — 期望切到 `Tech Sector Specialists:` 之前
- Jefferies (`1119-jefferies-tech...`) — 期望切到末尾 disclaimer
- Bernstein (`1222-bernstein-tmt...`) — 期望切到 `The information provided herein was prepared by` 之前
- ETNAlabs/Conor (`0859-fw-while-you-were-sleeping...`) — Jefferies 引用一遍，但用 italic 包了 disclaimer 在开头；不应被误切（开头切点会触发"切除 >70% 内容"防护）

### Checkpoint 1
- 在三封 sample 邮件上跑预处理，把 before/after diff 给用户审阅
- 用户确认后再进入 Phase 2

### Phase 2 — JPM Tech Sketch 重排 (sender-specific)

**触发条件**：sender_address 以 `@jpmorgan.com` 结尾 且 subject 含 `JPM TECH SKETCH`

**问题**：HTML 是单 td 包裹，markdown 输出整段塌缩为一行 ~10000 字符

**重排逻辑**：
1. 按 ` --- ` 分隔符切段（每段一个主题）
2. 段内识别 SHOUTY CAPS section labels（如 `NEWS – DESK COLOR – RESEARCH HIGHLIGHTS`、`JPM TECH RESEARCH`、`JPM TMT EVENT CALENDAR`、`SCHILSKY'S SENTIMENT MONITORS`、`TMT CORPORATE EVENT CALENDAR`）→ 提升为 `## heading`
3. 段内 sub-section（`INTERNET:`、`SOFTWARE:`、`MEDIA & TELECOM:`）→ `### heading`
4. 行内 ` - ` 列表项切回真正的换行 markdown bullet
5. 保留所有 `[link](url)` 不动

**Checkpoint 2**：JPM sample diff 给用户审阅

### Wire-up
- `storage.py:save_email` 改一行：把当前 `is_fomo_email(...) → reformat_content(...)` 替换为统一 `preprocess_email(md_content, email.sender_address)`
- 顺序：disclaimer 切除 → 发件人专用重排（fomo / jpm / ...）

### CLI（可选 deferred）
- 加 `inv-newsletter --reprocess [--date YYYY-MM-DD]`：对已有 .md 重新跑 preprocess
- 让用户能在已有历史邮件上验证效果，不必等新邮件

## 任务清单

- [ ] **Phase 1: 通用 disclaimer 切除**
  - [ ] 新建 `src/inv_newsletter/preprocess/__init__.py`、`disclaimer.py`
  - [ ] 把 `fomo_format.py` 移到 `preprocess/fomo_format.py`，更新 `storage.py` 的 import
  - [ ] 实现 `strip_disclaimer(content)` + 安全防护
  - [ ] 在 JPM/Jefferies/Bernstein/ETNAlabs 四封 sample 上手动 dry-run，把 diff 给用户审阅
  - [ ] 🛑 **Checkpoint 1**：用户确认后才接入 storage.py

- [ ] **Phase 2: JPM Tech Sketch 重排**
  - [ ] 新建 `preprocess/jpm_format.py`
  - [ ] sender + subject 触发条件
  - [ ] 实现 ` --- ` 切段 + section heading 提升 + bullet 切行
  - [ ] 在 JPM sample 上 dry-run，diff 给用户审阅
  - [ ] 🛑 **Checkpoint 2**：用户确认

- [ ] **Wire-up + 提交**
  - [ ] `storage.py` 调用 `preprocess_email`
  - [ ] commit

## Deferred candidates (不提前承诺，按需启动)
- 其他卖方发件人的专用重排（Jefferies、Bernstein 目前可读性已可接受）
- `--reprocess` CLI 命令对历史 .md 重处理
- Signature 块切除（"Jeffrey Favuzza / Equities Trading / ..." 这种）

## Review

### 完成项
- `preprocess/__init__.py` 统一入口 `preprocess_email(content, sender_address)`
- `preprocess/disclaimer.py`：通用 disclaimer 切除 + signature/logo backward-trim
- `preprocess/jpm_format.py`：JPM 邮件 ` --- ` 切段 + H2/H3 lift + 行内 bullet 切回换行
- `preprocess/fomo_format.py`：迁入（git rename），逻辑未改
- `storage.py:save_email`：调统一入口
- `tools/dryrun_disclaimer.py` + `tools/dryrun_jpm.py`：dry-run 工具

### 验证结果
- 188 封邮件全量跑：127 命中 disclaimer 切除 + sig trim
- JPM Tech Sketch（2 封）：` --- ` 切 36 段→过滤噪音后 ~15 段；SCHILSKY'S SNAPSHOT / JPM TECH RESEARCH / TMT CORPORATE EVENT CALENDAR 等 H2 + INTERNET/SOFTWARE/MEDIA H3 全部正确 lift
- Jefferies / Bernstein：disclaimer 切完后 sig trim 多吃 160 / 335 chars，contact 块和 BernsteinSG logo 都被切掉
- ETNAlabs 转发：开头 italic disclaimer 被守卫挡住（不切），末尾 disclaimer 正确切；conferences 列表保留
- Stratechery / FOMO / Meritco / 久谦论坛：no_safe_match，完全不动 ✓

### 已知遗留（deferred）
- Wolfe Research：邮件中没有显式 legal disclaimer 文字，整封 single-line，末尾联系人块没通用 anchor。要专门加 sender 规则。
- ETNAlabs 转发中间夹带的 Meghan Liu 签名：在 events 上方，处于文档中段，不在 backward-trim 范围。
- JPM 内的 events 表格：仍是单行 markdown table，未做表格切行重排。Phase 2 显式 skip。
- `--reprocess` CLI 命令对历史 .md 重处理：未实现，新抓的邮件自动走 preprocess。
