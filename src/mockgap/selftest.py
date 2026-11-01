"""API 없이 지표 함수와 모의 백엔드가 제대로 도는지 확인한다.  python -m mockgap.selftest"""
from __future__ import annotations

import random

from .config import setup_stdout
from .llm import MockBackend, parse_json_text
from .metrics import (
    best_sentence_lcs,
    build_ngram_index,
    classify_format,
    containment,
    coverage,
    distribution,
    lcs_len,
    normalize,
    tv_distance,
)
from .textbook import split_sentences


def main():
    setup_stdout()
    text = "산소는 우리 주변에 항상 존재하며, 다른 물질과 쉽게 반응하는 성질이 있다. 철은 자연 상태에서 대부분 산화 철 형태로 존재한다. 중화 반응에서는 물이 생성된다."
    idx = build_ngram_index(text, 4)

    assert normalize("산소는 우리, 주변에.") == "산소는우리주변에"
    assert containment("철은 자연 상태에서 대부분 산화 철 형태로 존재한다.", idx) > 0.95, "베낀 문장은 1에 가까워야"
    assert containment("광합성은 빛에너지를 화학 에너지로 바꾼다.", idx) < 0.2, "무관한 문장은 낮아야"
    assert lcs_len("abcde", "ace") == 3
    sents = split_sentences(text)
    assert len(sents) == 3, sents
    r, s = best_sentence_lcs("철은 자연 상태에서 대부분 산화 철로 존재한다", sents)
    assert r > 0.8 and "철은" in s

    assert classify_format("다음 표는 어떤 수용액의 온도 변화를 나타낸 것이다. 옳은 것은?") == "자료 해석"
    assert classify_format("0.1 M 염산 50 mL 를 완전히 중화하는 데 필요한 수산화 나트륨의 질량은?") == "계산"
    assert classify_format("산화와 환원의 뜻을 서술하시오.", "서술형") == "서술형"
    assert classify_format("다음 중 산화 반응인 것은?") == "개념 확인"
    assert classify_format("온도가 반응 속도에 미치는 영향을 알아보는 실험을 설계하시오.") == "탐구 설계"

    d1 = distribution(["개념 확인", "개념 확인", "계산"])
    d2 = distribution(["자료 해석", "계산"])
    assert abs(tv_distance(d1, d1)) < 1e-9 and 0 < tv_distance(d1, d2) <= 1

    cov = coverage(["O1", "O1", "O3", "none"], ["O1", "O2", "O3"])
    assert abs(cov["covered_ratio"] - 2 / 3) < 1e-9 and cov["missing"] == ["O2"] and cov["unassigned"] == 1

    assert parse_json_text('```json\n{"a": 1}\n```')["a"] == 1
    assert parse_json_text('설명: {"a": [1,2]} 끝')["a"] == [1, 2]

    mb = MockBackend(random.Random(1))
    gen = mb.run("generate", {"sentences": sents * 5, "n": 5, "mix": {"객관식": 4, "서술형": 1}}, {})
    assert len(gen["items"]) == 5 and gen["items"][0]["type"] == "객관식" and len(gen["items"][0]["options"]) == 5
    tag = mb.run("tag", {"item_ids": [1, 2], "objective_ids": ["O1", "O2"]}, {})
    assert len(tag["assignments"]) == 2
    sol = mb.run("solve", {"item_ids": [1, 2, 3], "keys": ["1", "2", "3"]}, {})
    assert all(a["answer"] in {"1", "2", "3", "4", "5"} for a in sol["answers"])
    gr = mb.run("grade", {"corrupted": True, "true_key": "2"}, {})
    assert gr["verdict"] in {"맞음", "틀림"}

    print("selftest OK: 지표 함수와 모의 백엔드 정상")


if __name__ == "__main__":
    main()
