"""입력 텍스트 폴더를 읽고 문장, 소단원, 학습목표를 꺼낸다."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import data_path, slug

_PAGE_MARK = re.compile(r"^### p\d+\s*$", re.MULTILINE)
_SENT_SPLIT = re.compile(r"(?<=[\.\?\!])\s+")


def load_units(textbook_dir: Path) -> dict:
    with open(Path(textbook_dir) / "units.json", encoding="utf-8") as f:
        return json.load(f)


def unit_text(textbook_dir: Path, unit: str) -> str:
    p = Path(textbook_dir) / f"unit_{slug(unit)}.txt"
    if not p.exists():
        raise FileNotFoundError(f"단원 텍스트가 없다: {p}")
    return _PAGE_MARK.sub("", p.read_text(encoding="utf-8"))


def page_text(textbook_dir: Path, page: int) -> str:
    p = Path(textbook_dir) / "pages" / f"p{page:03d}.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def split_sentences(text: str, min_len: int = 8) -> list[str]:
    """줄바꿈으로 끊긴 문장을 잇고 마침표 기준으로 나눈다."""
    joined = re.sub(r"\s*\n\s*", " ", text)
    out = []
    for s in _SENT_SPLIT.split(joined):
        s = s.strip()
        hangul = sum(1 for c in s if "가" <= c <= "힣")
        if len(s) >= min_len and hangul >= 4:
            out.append(s)
    return out


def section_names(units: dict, unit: str) -> list[str]:
    return list(units[unit]["sections"].keys())


def section_texts(textbook_dir: Path, units: dict, unit: str) -> dict[str, str]:
    out = {}
    for name, (a, b) in units[unit]["sections"].items():
        out[name] = _PAGE_MARK.sub("", "\n".join(page_text(textbook_dir, p) for p in range(a, b + 1)))
    return out


OBJ_SCHEMA = {
    "type": "object",
    "properties": {
        "objectives": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "section": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["id", "section", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["objectives"],
    "additionalProperties": False,
}


def get_objectives(cfg: dict, llm, unit: str) -> list[dict]:
    """단원의 학습목표 목록. 수동 파일 > 캐시 > LLM 추출 순으로 쓴다.

    수동 파일: data/objectives/<slug>.manual.json (같은 형식). 교사 검토 결과를 여기에 넣는다.
    """
    manual = data_path(cfg, "objectives", f"{slug(unit)}.manual.json")
    auto = data_path(cfg, "objectives", f"{slug(unit)}.json")
    for p in (manual, auto):
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)["objectives"]

    units = load_units(cfg["textbook_dir"])
    secs = section_texts(cfg["textbook_dir"], units, unit)
    names = list(secs.keys())
    prompt = (
        f"아래는 고등학교 통합과학2 교과서 '{unit}' 단원의 본문이다. 소단원은 {', '.join(names)} 이다.\n"
        "이 단원의 학습목표를 소단원별로 2~4개씩 뽑아라. 학습목표는 '...을 설명할 수 있다', '...을 구할 수 있다'처럼 "
        "학생이 할 수 있어야 하는 것을 한 문장으로 쓴다. id는 O1, O2, ... 순서로 붙이고 section에는 소단원 이름을 그대로 쓴다.\n\n"
        + "\n\n".join(f"[{n}]\n{t[:12000]}" for n, t in secs.items())
    )
    tcfg = cfg["tagger"]
    data = llm.complete_json(
        tcfg["provider"],
        prompt,
        OBJ_SCHEMA,
        task="objectives",
        system="너는 한국 고등학교 과학 교사이며 교육과정 성취기준에 맞게 학습목표를 쓴다.",
        model=tcfg["model"],
        effort=tcfg.get("effort"),
        mock_ctx={"sentences_by_section": {n: split_sentences(t) for n, t in secs.items()}},
    )
    objs = data["objectives"]
    for k, o in enumerate(objs, 1):
        o.setdefault("id", f"O{k}")
    with open(auto, "w", encoding="utf-8") as f:
        json.dump({"unit": unit, "objectives": objs}, f, ensure_ascii=False, indent=1)
    return objs
