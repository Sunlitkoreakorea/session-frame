"""정답지를 일부 바꾼 뒤 모델별 채점 결과를 비교한다.

사용 예:
  python -m mockgap.self_preference
  python -m mockgap.self_preference --per-cell 5
  python -m mockgap.self_preference --only-consensus   # 교차 풀이에서 모든 모델이 정답지와 일치한 문항만 사용
출력: data/self_preference/results.csv, summary.json
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import pandas as pd

from .config import data_path, load_config, setup_stdout
from .llm import LLM
from .measure import load_sets

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["맞음", "틀림"]},
        "correct_answer": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "correct_answer", "reason"],
    "additionalProperties": False,
}


def grade_prompt(unit: str, it: dict, shown_key: str) -> str:
    opts = "\n".join(f"  {i}) {o}" for i, o in enumerate(it["options"], 1))
    return (
        f"학생이 AI에게 받은 고등학교 통합과학2 '{unit}' 단원 예상문제와 정답지다. 정답지가 맞는지 판정하라.\n"
        f"[문항]\n{it['stem']}\n{opts}\n[정답지] {shown_key}번\n"
        "verdict에 '맞음' 또는 '틀림'을 쓰고, correct_answer에 네가 생각하는 정답 번호를 '1'~'5'로 쓰고, reason에 근거를 한 문장으로 쓴다."
    )


def main(argv=None):
    setup_stdout()
    ap = argparse.ArgumentParser(description="자기 선호 실험")
    ap.add_argument("--units")
    ap.add_argument("--providers", help="생성 모델 (기본: 전부)")
    ap.add_argument("--graders", help="채점 모델 (기본: 전부)")
    ap.add_argument("--per-cell", type=int, help="단원×생성모델 칸마다 뽑을 문항 수")
    ap.add_argument("--only-consensus", action="store_true", help="measured/items.csv 에서 모든 모델이 정답지와 일치한 문항만")
    args = ap.parse_args(argv)

    cfg = load_config()
    llm = LLM(cfg)
    rng = random.Random(cfg.get("seed", 0))
    sp = cfg.get("self_preference", {})
    per_cell = args.per_cell or sp.get("items_per_cell", 20)
    corrupt_ratio = float(sp.get("corrupt_ratio", 0.5))
    units = [u.strip() for u in args.units.split(",")] if args.units else cfg["units"]
    gens = [p.strip() for p in args.providers.split(",")] if args.providers else list(cfg["providers"].keys())
    graders = [p.strip() for p in args.graders.split(",")] if args.graders else list(cfg["providers"].keys())

    consensus = None
    if args.only_consensus:
        p = Path(cfg["data_dir"]) / "measured" / "items.csv"
        if not p.exists():
            raise SystemExit("먼저 python -m mockgap.measure 를 실행해야 --only-consensus 를 쓸 수 있다.")
        df = pd.read_csv(p, encoding="utf-8-sig")
        ok = df[(df["type"] == "객관식") & (df["n_solved"] > 0) & (df["n_agree_key"] == df["n_solved"])]
        consensus = set(zip(ok["unit"], ok["provider"], ok["set_no"], ok["item_id"]))

    # 칸별 표본
    pool = {}
    for unit, provider, set_no, data in load_sets(cfg, units, gens):
        for it in data["items"]:
            if it["type"] != "객관식" or len(it.get("options", [])) < 2:
                continue
            if consensus is not None and (unit, provider, set_no, it["id"]) not in consensus:
                continue
            pool.setdefault((unit, provider), []).append((set_no, it, int(data["meta"].get("with_text", True))))

    rows = []
    for (unit, gen), items in pool.items():
        sample = rng.sample(items, min(per_cell, len(items)))
        for set_no, it, with_text in sample:
            true_key = str(it["answer"])
            corrupted = rng.random() < corrupt_ratio
            if corrupted:
                others = [str(i) for i in range(1, len(it["options"]) + 1) if str(i) != true_key]
                shown = rng.choice(others)
            else:
                shown = true_key
            for grader in graders:
                try:
                    res = llm.complete_json(
                        grader,
                        grade_prompt(unit, it, shown),
                        GRADE_SCHEMA,
                        task="grade",
                        system="너는 고등학교 과학 교사다. 정답지를 꼼꼼히 검토한다.",
                        mock_ctx={"corrupted": corrupted, "true_key": true_key},
                    )
                except Exception as e:
                    print(f"  [경고] {grader} 채점 실패: {e}")
                    continue
                rows.append(
                    {
                        "unit": unit,
                        "generator": gen,
                        "grader": grader,
                        "same_model": int(gen == grader),
                        "with_text": with_text,
                        "set_no": set_no,
                        "item_id": it["id"],
                        "true_key": true_key,
                        "shown_key": shown,
                        "corrupted": int(corrupted),
                        "verdict": res.get("verdict", ""),
                        "accepted": int(res.get("verdict", "") == "맞음"),
                        "grader_answer": str(res.get("correct_answer", "")).strip(),
                        "grader_matches_true": int(str(res.get("correct_answer", "")).strip() == true_key),
                    }
                )
        print(f"[{unit}] 생성 {gen}: {len(sample)}문항 × {len(graders)}채점자")

    out_dir = data_path(cfg, "self_preference", "x").parent
    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "results.csv", index=False, encoding="utf-8-sig")

    summary = {}
    if len(df):
        bad = df[df["corrupted"] == 1]
        good = df[df["corrupted"] == 0]
        summary["wrong_key_pass_through"] = {
            "same_model": None if bad[bad.same_model == 1].empty else round(bad[bad.same_model == 1]["accepted"].mean(), 3),
            "other_model": None if bad[bad.same_model == 0].empty else round(bad[bad.same_model == 0]["accepted"].mean(), 3),
            "by_generator": bad.groupby(["generator", "same_model"])["accepted"].mean().round(3).reset_index().to_dict("records"),
        }
        summary["correct_key_false_rejection"] = {
            "same_model": None if good[good.same_model == 1].empty else round(1 - good[good.same_model == 1]["accepted"].mean(), 3),
            "other_model": None if good[good.same_model == 0].empty else round(1 - good[good.same_model == 0]["accepted"].mean(), 3),
        }
        summary["n_rows"] = int(len(df))
        summary["only_consensus"] = bool(args.only_consensus)
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("저장 위치:", out_dir)


if __name__ == "__main__":
    main()
