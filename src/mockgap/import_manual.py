"""손으로 받은 문항 텍스트를 파이프라인 세트로 저장한다.

사용 예:
  python -m mockgap.import_manual --unit "I-2 화학 변화" --provider openai --file 받은답.txt --model "ChatGPT 앱 2026-11-01"
  python -m mockgap.import_manual --unit "I-2 화학 변화" --provider google --file 받은답.json

- 파일이 JSON이면 그대로 읽고, 아니면 본문에서 JSON 객체를 찾아 읽는다.
- JSON이 전혀 없으면 번호 매긴 문항 텍스트를 대충 쪼개어 저장한다 (정답과 라벨이 비어 있을 수 있음).
- 저장 위치: data/generated/<단원>/<provider>/set_NN.json (다음 번호로 자동 저장)
- provider 이름은 config.yaml 의 providers 키(anthropic, openai, google)와 같게 쓴다. 그래야 교차 검증과 자기 선호가 맞물린다.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from .config import data_path, load_config, setup_stdout, slug
from .generate import validate_items
from .llm import MockBackend, parse_json_text


def main(argv=None):
    setup_stdout()
    ap = argparse.ArgumentParser(description="손으로 받은 예상문제 가져오기")
    ap.add_argument("--unit", required=True)
    ap.add_argument("--provider", required=True, help="anthropic / openai / google")
    ap.add_argument("--file", required=True, help="챗 앱 답을 저장한 텍스트 또는 JSON 파일")
    ap.add_argument("--model", default="", help="메모용. 예: 'ChatGPT 앱 기본 모델 2026-11-01'")
    ap.add_argument("--no-text", action="store_true", help="교과서 본문 없이(단원 이름과 쪽수만 주고) 받은 세트일 때. notext/ 하위 폴더에 저장")
    args = ap.parse_args(argv)

    cfg = load_config()
    raw = Path(args.file).read_text(encoding="utf-8")
    source = "json"
    try:
        data = parse_json_text(raw)
        items = data.get("items", data if isinstance(data, list) else [])
    except Exception:
        source = "naive_text"
        items = MockBackend(random.Random(0)).run("parse_items", {"text": raw}, {})["items"]
        print("[경고] JSON을 찾지 못해 텍스트를 대충 쪼갰다. 정답과 난이도 라벨이 비어 있을 수 있으니 파일을 열어 확인할 것.")
    items = validate_items(items, cfg["questions_per_set"] * 5)
    if not items:
        raise SystemExit("문항을 하나도 읽지 못했다.")

    parts = ["generated", slug(args.unit), args.provider] + (["notext"] if args.no_text else []) + ["x"]
    d = data_path(cfg, *parts).parent
    existing = sorted(d.glob("set_*.json"))
    k = (int(existing[-1].stem.split("_")[1]) + 1) if existing else 1
    out = d / f"set_{k:02d}.json"
    res = {
        "meta": {
            "unit": args.unit,
            "provider": args.provider,
            "model": args.model or f"manual/{args.provider}",
            "set_no": k,
            "n_requested": cfg["questions_per_set"],
            "n_items": len(items),
            "with_text": not args.no_text,
            "mock": False,
            "manual": True,
            "source_file": str(Path(args.file).resolve()),
            "parsed_as": source,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "items": items,
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    n_mc = sum(1 for it in items if it["type"] == "객관식")
    print(f"저장: {out}  (문항 {len(items)}개, 객관식 {n_mc}, 서술형 {len(items) - n_mc})")


if __name__ == "__main__":
    main()
