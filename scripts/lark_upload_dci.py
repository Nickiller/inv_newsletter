"""Clean each DCI .md and create a fresh Feishu doc, mirroring the local
01_thesis/02_notes/03_weekly subfolder structure.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lark_cleanup_dci import clean_file  # noqa: E402

ROOT = Path("/Users/zhangxypro/Code/Claude_Workspace/inv_newsletter/data/meritco_dci")

# subfolder name -> Feishu folder token
FOLDER_TOKENS = {
    "01_thesis": "Q2w9fTFYLlYAMPdcEqlcIIeKnAc",
    "02_notes": "MCyNf5EF2lnKDOd0f6ecKvSYngd",
    "03_weekly": "Bt4afhgD1liseYdg2yWcBajTnte",
}


def create_doc(title: str, markdown: str, folder_token: str) -> dict:
    cmd = [
        "lark-cli", "docs", "+create",
        "--title", title,
        "--folder-token", folder_token,
        "--markdown", markdown,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        return {"ok": False, "error": f"exit={r.returncode} stderr={r.stderr[:300]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"non-JSON: {r.stdout[:300]}"}


def main():
    results = []
    for subdir, token in FOLDER_TOKENS.items():
        files = sorted((ROOT / subdir).glob("*.md"))
        print(f"\n=== {subdir} ({len(files)} files) → {token} ===")
        for f in files:
            title = f.stem
            cleaned = clean_file(f)
            print(f"  uploading: {title}  ({len(cleaned)} chars)...", end=" ", flush=True)
            res = create_doc(title, cleaned, token)
            if res.get("ok"):
                doc_url = res.get("data", {}).get("doc_url", "")
                print(f"✓ {doc_url}")
                results.append({"subdir": subdir, "title": title, "url": doc_url, "ok": True})
            else:
                err = res.get("error") or res
                print(f"✗ {str(err)[:200]}")
                results.append({"subdir": subdir, "title": title, "ok": False, "err": str(err)[:300]})

    ok = sum(1 for r in results if r["ok"])
    print(f"\n=== DONE: {ok}/{len(results)} uploaded ===")
    (ROOT / "_lark_upload_log.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
