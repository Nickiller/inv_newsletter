"""digest_v3 — chunk-level 路由 + 渐进式披露多 prompt 日报生成（原型阶段 Claude Code 驱动）。

判断 stage（规整/路由/生成/catalyst/TL;DR）由 Claude Code 在 session 内做，prompt 在 prompts/。
确定性部分：chunk.py（切块）、assemble.py（拼接 + 图片嵌入 + TLDR 前置）。
"""
