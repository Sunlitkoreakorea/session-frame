"""5번 단계: 세 모델에 같은 범위 텍스트를 주고 예상문제 세트를 받아 저장한다.

사용 예:
  python -m mockgap.generate                      # config.yaml 대로 전부
  python -m mockgap.generate --sets 2 --n 5       # 작게 시험
  python -m mockgap.generate --units "I-2 화학 변화" --providers anthropic,openai
저장 위치: data/generated/<단원>/<provider>/set_01.json ...
이미 있는 세트는 건너뛰므로 중간에 끊겨도 다시 실행하면 이어서 한다.
"""
from __future__ import annotations

import argparse
import json
import time

from .config import data_path, load_config, setup_stdout, slug
from .llm import LLM
from .textbook import load_units, split_sentences, unit_text

GEN_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "type": {"type": "string", "enum": ["객관식", "서술형"]},
                    "stem": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "answer": {"type": "string"},
                    "explanation": {"type": "string"},
                    "difficulty": {"type": "string", "enum": ["하", "중", "상"]},
                    "bloom": {"type": "string", "enum": ["기억", "이해", "적용", "분석"]},
                },
                "required": ["id", "type", "stem", "options", "answer", "explanation", "difficulty", "bloom"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

SYSTEM = (
    "너는 한국 고등학교 통합과학 교사다. 학생이 단원 평가를 준비할 수 있도록 예상문제를 만든다. "
    "문항은 주어진 교과서 범위 안에서만 출제한다."
)


def build_prompt(unit: str, text: str, n: int, mix: dict, set_no: int, scope_line: str | None = None) -> str:
    """scope_line 이 주어지면 교과서 본문 없이 단원 이름과 쪽수만 알려 주는 '본문 없음' 프롬프트가 된다."""
    n_mc = mix.get("객관식", 16)
    n_sa = n - n_mc
    if scope_line:
        head = f"고등학교 통합과학2 교과서 '{unit}' 단원({scope_line}) 범위로 단원 평가 예상문제 {n}개를 만들어라.\n"
        tail = f"[범위]\n{scope_line}\n교과서 본문은 주어지지 않는다. 이 단원의 교육과정과 교과서 내용에 대한 네 지식으로 출제한다."
    else:
        head = f"다음은 고등학교 통합과학2 교과서 '{unit}' 단원의 본문이다. 이 범위로 단원 평가 예상문제 {n}개를 만들어라.\n"
        tail = f"[교과서 본문]\n{text}"
    rules = (
        f"- 객관식 {n_mc}개: 5지선다, options에 보기 5개를 넣고 answer에는 정답 보기의 번호를 '1'~'5' 문자열로 쓴다.\n"
        f"- 서술형 {n_sa}개: options는 빈 배열로 두고 answer에 모범답안을 쓴다.\n"
        "- 각 문항에 difficulty(하/중/상)와 bloom(기억/이해/적용/분석)을 붙인다.\n"
        "- explanation에는 정답 근거를 한두 문장으로 쓴다.\n"
        "- id는 1부터 차례로 붙인다.\n"
        f"- 이것은 {set_no}번째 세트다. 단원 전체를 고르게 다루고 문항 유형을 다양하게 섞어라.\n\n"
    )
    return head + rules + tail


def scope_line_for(units_all: dict, unit: str) -> str:
    u = units_all[unit]
    return f"교과서 {u['start']}~{u['end']}쪽, 소단원: {', '.join(u['sections'].keys())}"


def validate_items(items: list[dict], n: int) -> list[dict]:
    ok = []
    for k, it in enumerate(items, 1):
        it = dict(it)
        it["id"] = k
        it.setdefault("options", [])
        it.setdefault("explanation", "")
        it["type"] = "객관식" if it.get("options") else "서술형"
        if it["type"] == "객관식":
            it["options"] = [str(o) for o in it["options"]][:5]
            a = str(it.get("answer", "")).strip()
            if a not in {"1", "2", "3", "4", "5"}:
                # 보기 본문으로 정답을 적은 경우 번호로 바꾼다
                idx = next((i for i, o in enumerate(it["options"], 1) if o.strip() == a), None)
                a = str(idx) if idx else "1"
            it["answer"] = a
        it["difficulty"] = it.get("difficulty") if it.get("difficulty") in ("하", "중", "상") else "중"
        it["bloom"] = it.get("bloom") if it.get("bloom") in ("기억", "이해", "적용", "분석") else "이해"
        ok.append(it)
    return ok[:n]


def generate_set(cfg: dict, llm: LLM, unit: str, provider: str, set_no: int, n: int, mix: dict, scope_line: str | None = None) -> dict:
    text = unit_text(cfg["textbook_dir"], unit)
    prompt = build_prompt(unit, text, n, mix, set_no, scope_line)
    data = llm.complete_json(
        provider,
        prompt,
        GEN_SCHEMA,
        task="generate",
        system=SYSTEM,
        mock_ctx={"sentences": split_sentences(text), "n": n, "mix": mix, "unit": unit},
        use_cache=False,  # 세트마다 다른 표본이 필요하므로 캐시를 쓰지 않는다
    )
    items = validate_items(data.get("items", []), n)
    return {
        "meta": {
            "unit": unit,
            "provider": provider,
            "model": llm.provider_model(provider),
            "set_no": set_no,
            "n_requested": n,
            "n_items": len(items),
            "with_text": scope_line is None,
            "mock": llm.mock,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "items": items,
    }


def main(argv=None):
    setup_stdout()
    ap = argparse.ArgumentParser(description="예상문제 세트 생성")
    ap.add_argument("--units", help="쉼표로 구분한 단원 이름 (기본: config.yaml)")
    ap.add_argument("--providers", help="쉼표로 구분 (기본: config.yaml 의 providers 전부)")
    ap.add_argument("--sets", type=int, help="단원당 모델당 세트 수")
    ap.add_argument("--n", type=int, help="세트당 문항 수")
    ap.add_argument("--model", help="이번 실행에서만 쓸 모델 이름 (한 provider만 지정했을 때 사용)")
    ap.add_argument("--no-text", action="store_true", help="교과서 본문 없이 단원 이름과 쪽수만 주고 생성 (notext/ 하위 폴더에 저장)")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.model:
        for p in (args.providers or "").split(","):
            if p.strip() in cfg["providers"]:
                cfg["providers"][p.strip()]["model"] = args.model
    llm = LLM(cfg)
    units_all = load_units(cfg["textbook_dir"])
    units = [u.strip() for u in args.units.split(",")] if args.units else cfg["units"]
    providers = [p.strip() for p in args.providers.split(",")] if args.providers else list(cfg["providers"].keys())
    sets = args.sets or cfg["sets_per_unit_per_model"]
    n = args.n or cfg["questions_per_set"]
    mix = dict(cfg["format_mix"])
    if n != cfg["questions_per_set"]:
        n_mc = round(n * mix.get("객관식", 16) / max(1, cfg["questions_per_set"]))
        mix = {"객관식": n_mc, "서술형": n - n_mc}

    for unit in units:
        if unit not in units_all:
            raise SystemExit(f"units.json 에 없는 단원: {unit}")
        scope = scope_line_for(units_all, unit) if args.no_text else None
        for provider in providers:
            for k in range(1, sets + 1):
                parts = ["generated", slug(unit), provider] + (["notext"] if args.no_text else []) + [f"set_{k:02d}.json"]
                out = data_path(cfg, *parts)
                if out.exists():
                    continue
                t0 = time.time()
                res = generate_set(cfg, llm, unit, provider, k, n, mix, scope)
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(res, f, ensure_ascii=False, indent=1)
                print(f"[{unit}] {provider} set {k:02d}: {res['meta']['n_items']}문항 ({time.time() - t0:.1f}s)")
    print("생성 끝. 저장 위치:", data_path(cfg, "generated"))


if __name__ == "__main__":
    main()
