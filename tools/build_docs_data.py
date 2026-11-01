"""docs/data.js 를 만든다. 정적 페이지(docs/)가 쓰는 설정, 단원 구조, 연습 세트, 시험, 입력 텍스트를 한 파일에 담는다.

  python tools/build_docs_data.py
설정이나 문항 파일을 바꾸면 다시 실행하고 docs/data.js 를 함께 커밋한다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def slug(name: str) -> str:
    return re.sub(r"[^\w\-]+", "_", name).strip("_")


def main():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    textbook = (ROOT / cfg["textbook_dir"]).resolve()
    exp = json.loads((ROOT / "data/experiment/config.json").read_text(encoding="utf-8"))
    exp.setdefault("seed", cfg.get("seed", 1))
    exp.setdefault("max_participants", 200)
    units = json.loads((textbook / "units.json").read_text(encoding="utf-8"))
    data = {"config": exp, "units": units, "unit_text": {}, "practice_sets": {}, "tests": {}, "objectives": {}, "past_formats": {}}
    for name in exp["units"].values():
        p = textbook / f"unit_{slug(name)}.txt"
        data["unit_text"][name] = re.sub(r"^### p\d+\s*$", "", p.read_text(encoding="utf-8"), flags=re.M) if p.exists() else ""
        for kind in ("practice_sets", "tests"):
            q = ROOT / "data/experiment" / kind / f"{slug(name)}.json"
            data[kind][name] = json.loads(q.read_text(encoding="utf-8")).get("items", []) if q.exists() else []
        for cand in (f"{slug(name)}.manual.json", f"{slug(name)}.json"):
            o = ROOT / "data/objectives" / cand
            if o.exists():
                data["objectives"][name] = json.loads(o.read_text(encoding="utf-8"))["objectives"]
                break
        pe = ROOT / "data/past_exams" / f"{slug(name)}.csv"
        if pe.exists():
            import csv
            with open(pe, encoding="utf-8-sig", newline="") as f:
                data["past_formats"][name] = [r.get("format", "") for r in csv.DictReader(f) if r.get("format")]
    out = ROOT / "docs/data.js"
    out.write_text("window.FRAME_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    print("wrote", out, f"({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    sys.exit(main())
