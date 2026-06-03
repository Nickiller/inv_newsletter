"""Sync a generated daily digest (+ its images) into the wiki vault.

The wiki lives at summarization.wiki_sync_dir — an Obsidian vault under OneDrive
that syncs to the cloud automatically, so no git is involved here; a plain file
copy is enough. The digest markdown references images with relative paths
`{date}/IMG_XX.ext`, so we copy both the .md and its sibling `{date}/` image
directory to keep those links working inside the vault.
"""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def sync_digest_to_wiki(digest_path: Path, wiki_dir: Path | str | None) -> Path | None:
    """Copy ``digest_path`` (and its ``{date}/`` image dir) into ``wiki_dir``.

    Returns the destination .md path, or ``None`` if the sync was skipped
    (no wiki_dir configured, source missing, or target dir absent).

    Never raises — a sync failure must not break the summarize/publish pipeline.
    """
    if not wiki_dir:
        return None

    digest_path = Path(digest_path)
    wiki_dir = Path(wiki_dir).expanduser()

    if not digest_path.exists():
        logger.warning(f"Wiki sync skipped: digest not found: {digest_path}")
        return None
    if not wiki_dir.exists():
        logger.warning(f"Wiki sync skipped: target dir does not exist: {wiki_dir}")
        return None

    try:
        dest_md = wiki_dir / digest_path.name
        shutil.copy2(digest_path, dest_md)

        # Copy the sibling image dir: output/daily/{date}/ -> wiki/{date}/
        # date = the filename up to the first "_daily_digest" (handles suffixes
        # like "_v2" by leaving them on the .md while images stay under {date}/).
        date_str = digest_path.stem.split("_daily_digest")[0]
        src_img_dir = digest_path.parent / date_str
        n_imgs = 0
        if src_img_dir.is_dir():
            dest_img_dir = wiki_dir / date_str
            dest_img_dir.mkdir(parents=True, exist_ok=True)
            for img in src_img_dir.iterdir():
                if img.is_file():
                    shutil.copy2(img, dest_img_dir / img.name)
                    n_imgs += 1

        logger.info(f"Wiki sync: {dest_md} (+{n_imgs} image(s))")
        print(f"📚 Synced to wiki: {dest_md}" + (f" (+{n_imgs} images)" if n_imgs else ""))
        return dest_md
    except Exception as e:
        logger.error(f"Wiki sync failed (continuing): {e}")
        return None
