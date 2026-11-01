"""설정 파일과 경로를 읽는다."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # mockgap/


def setup_stdout() -> None:
    """윈도우 콘솔에서 한글이 깨지지 않게 한다."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def load_config(path: Path | None = None) -> dict:
    load_dotenv(ROOT / ".env")
    path = path or ROOT / "config.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_root"] = ROOT
    cfg["textbook_dir"] = (ROOT / cfg["textbook_dir"]).resolve()
    cfg["data_dir"] = (ROOT / cfg["data_dir"]).resolve()
    # 모의 실행이 실제 자료와 섞이지 않게 MOCKGAP_DATA_DIR 로 자료 폴더를 바꿀 수 있다
    if os.environ.get("MOCKGAP_DATA_DIR"):
        cfg["data_dir"] = Path(os.environ["MOCKGAP_DATA_DIR"]).resolve()
    cfg["mock"] = os.environ.get("MOCKGAP_MOCK", "0") == "1"
    return cfg


def slug(name: str) -> str:
    """단원 이름을 폴더 이름으로 쓸 수 있게 바꾼다. 예: 'I-2 화학 변화' -> 'I-2_화학_변화'"""
    return re.sub(r"[^\w\-]+", "_", name).strip("_")


def data_path(cfg: dict, *parts: str) -> Path:
    p = Path(cfg["data_dir"]).joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
