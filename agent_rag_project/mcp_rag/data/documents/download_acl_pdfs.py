from __future__ import annotations

import json
import time
from pathlib import Path

import requests
from tqdm import tqdm
from acl_anthology import Anthology


# ========= 可改配置 =========
YEARS = [2024, 2025]
VENUES = ["acl"]
INCLUDE_FINDINGS = False

# 本地 ACL Anthology data 目录
LOCAL_DATA_DIR = Path(r".\anthology_data\data").resolve()

# 输出目录
OUT_DIR = Path("data")
PDF_DIR = OUT_DIR / "pdfs"
META_FILE = OUT_DIR / "metadata.jsonl"

REQUEST_TIMEOUT = 30
SLEEP_SECONDS = 0.2
# ==========================


def safe_text(x) -> str:
    return "" if x is None else str(x).strip()


def build_pdf_url(full_id: str) -> str:
    return f"https://aclanthology.org/{full_id}.pdf"


def build_landing_url(full_id: str) -> str:
    return f"https://aclanthology.org/{full_id}/"


def author_names(paper) -> list[str]:
    names = []
    for a in getattr(paper, "authors", []) or []:
        try:
            names.append(safe_text(a.name))
        except Exception:
            names.append(safe_text(a))
    return names


def iter_main_papers(anthology: Anthology):
    """
    主会论文：
    例如 2023.acl / 2024.emnlp / 2025.naacl
    """
    for year in YEARS:
        for venue in VENUES:
            collection_id = f"{year}.{venue}"
            collection = anthology.get_collection(collection_id)
            if collection is None:
                print(f"[WARN] collection not found: {collection_id}")
                continue

            for volume in anthology.volumes(collection_id):
                volume_id = getattr(volume, "id", "")
                volume_full_id = f"{collection_id}-{volume_id}"

                for paper in anthology.papers(volume_full_id):
                    yield {
                        "source_type": "main",
                        "collection_id": collection_id,
                        "volume_id": volume_id,
                        "paper": paper,
                    }


def iter_findings_papers(anthology: Anthology):
    """
    Findings：
    例如 2023.findings-acl / 2024.findings-emnlp / 2025.findings-naacl
    """
    for year in YEARS:
        for venue in VENUES:
            volume_full_id = f"{year}.findings-{venue}"
            volume = anthology.get_volume(volume_full_id)
            if volume is None:
                continue

            for paper in anthology.papers(volume_full_id):
                yield {
                    "source_type": "findings",
                    "collection_id": f"{year}.findings",
                    "volume_id": venue,
                    "paper": paper,
                }


def download_file(url: str, out_path: Path) -> bool:
    if out_path.exists() and out_path.stat().st_size > 0:
        return True

    try:
        resp = requests.get(url, stream=True, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"[WARN] {resp.status_code} -> {url}")
            return False

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 64):
                if chunk:
                    f.write(chunk)
        return True
    except Exception as e:
        print(f"[WARN] download failed: {url} | {e}")
        return False


def main():
    if not LOCAL_DATA_DIR.exists():
        raise FileNotFoundError(
            f"本地 ACL Anthology data 目录不存在：{LOCAL_DATA_DIR}\n"
            f"请确认你已经把官方仓库里的 data 文件夹放到 .\\anthology_data\\data"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    print("[INFO] Loading ACL Anthology metadata from local folder...")
    print(f"[INFO] Local data dir: {LOCAL_DATA_DIR}")
    anthology = Anthology(datadir=str(LOCAL_DATA_DIR))
    anthology.load_all()

    rows = []
    seen = set()

    # 主会
    for item in tqdm(iter_main_papers(anthology), desc="Collecting main papers"):
        paper = item["paper"]
        full_id = getattr(paper, "full_id", None)
        local_id = getattr(paper, "id", None)

        if not full_id:
            continue
        if str(local_id) == "0":
            # 通常是封面或 front matter
            continue
        if full_id in seen:
            continue
        seen.add(full_id)

        row = {
            "full_id": full_id,
            "paper_id": safe_text(local_id),
            "title": safe_text(getattr(paper, "title", "")),
            "authors": author_names(paper),
            "source_type": item["source_type"],
            "collection_id": item["collection_id"],
            "volume_id": item["volume_id"],
            "pdf_url": build_pdf_url(full_id),
            "landing_url": build_landing_url(full_id),
            "pdf_path": str(PDF_DIR / f"{full_id}.pdf"),
        }
        rows.append(row)

    # Findings
    if INCLUDE_FINDINGS:
        for item in tqdm(iter_findings_papers(anthology), desc="Collecting findings papers"):
            paper = item["paper"]
            full_id = getattr(paper, "full_id", None)
            local_id = getattr(paper, "id", None)

            if not full_id:
                continue
            if str(local_id) == "0":
                continue
            if full_id in seen:
                continue
            seen.add(full_id)

            row = {
                "full_id": full_id,
                "paper_id": safe_text(local_id),
                "title": safe_text(getattr(paper, "title", "")),
                "authors": author_names(paper),
                "source_type": item["source_type"],
                "collection_id": item["collection_id"],
                "volume_id": item["volume_id"],
                "pdf_url": build_pdf_url(full_id),
                "landing_url": build_landing_url(full_id),
                "pdf_path": str(PDF_DIR / f"{full_id}.pdf"),
            }
            rows.append(row)

    print(f"[INFO] total papers collected: {len(rows)}")

    with META_FILE.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"[INFO] metadata saved to: {META_FILE}")

    ok = 0
    fail = 0

    for row in tqdm(rows, desc="Downloading PDFs"):
        out_path = Path(row["pdf_path"])
        success = download_file(row["pdf_url"], out_path)
        if success:
            ok += 1
        else:
            fail += 1
        time.sleep(SLEEP_SECONDS)

    print(f"[DONE] success={ok}, fail={fail}")
    print(f"[DONE] PDF folder: {PDF_DIR.resolve()}")
    print(f"[DONE] Metadata file: {META_FILE.resolve()}")


if __name__ == "__main__":
    main()