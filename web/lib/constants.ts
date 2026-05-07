// Sector order mirrors src/inv_newsletter/summarizer.py SYSTEM_PROMPT.
// Keep in sync with the LLM prompt; subsections under unknown sectors fall
// through to "其他".
export const SECTOR_ORDER = [
  "AI 模型与平台",
  "宏观与市场",
  "半导体与硬件",
  "互联网与数字广告",
  "软件与SaaS",
  "网络安全",
  "其他",
] as const;

export type SectorName = (typeof SECTOR_ORDER)[number];

export const CALENDAR_HEADING_MARKER = "本周关注催化剂";

// Tokens that look like tickers (uppercase A-Z runs) but are common acronyms
// that appear in sector/topic headings.
export const TICKER_NOISE = new Set([
  "AI", "API", "ARR", "ASP", "BI", "CEO", "CFO", "CIO", "CPO",
  "CRM", "DAU", "DDR", "DLP", "DSP", "EBITDA", "EPS", "ESG",
  "EU", "EV", "FX", "FY", "GAAP", "GDP", "GM", "GPU", "GPT",
  "HR", "ID", "IPO", "IR", "IRA", "IRR", "IT", "JPM", "KPI",
  "LLM", "LTA", "LTM", "MAU", "ML", "MOAT", "MOM", "NFLX",
  "OEM", "OKR", "OS", "OTA", "PT", "QOQ", "RAM", "RIF",
  "ROAS", "ROE", "ROI", "RSU", "SAAS", "SDK", "SEO", "SKU",
  "SMB", "SOTP", "SOX", "SOTA", "SSD", "TAM", "TCO", "TLC",
  "TPU", "TSMC", "TTM", "UI", "URL", "US", "USD", "UX",
  "VC", "VPN", "WACC", "WAU", "YOY", "YOY%", "YTD",
  // Common Chinese-context noise
  "RD", "QA", "QLC",
]);

// Tickers (kept short so we don't accidentally swallow words)
export const MAX_TICKER_LEN = 5;
export const MIN_TICKER_LEN = 1;
