"""6번 단계: 생성된 예상문제 세트를 잰다.

문항별: 원문 베끼기 점수(4-gram 포함률), 가장 비슷한 교과서 문장과의 LCS 비율, 형식(규칙 분류),
        학습목표 배정(LLM 태깅), 교차 모델 풀이 결과와 정답지 불일치, LLM 난이도/사고수준 라벨
세트별: 범위 적합도(덮인 학습목표 비율, 몰림 지니), 평균 베끼기 점수, 형식 분포, 기출 형식 분포와의 거리, 불일치율

사용 예:
  python -m mockgap.measure                 # 전부
  python -m mockgap.measure --no-api        # API 없이 로컬 지표만 (베끼기, 형식)
  python -m mockgap.measure --units "I-2 화학 변화"
출력: data/measured/items.csv, sets.csv, summary.json
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from .config import data_path, load_config, setup_stdout, slug
from .llm import LLM
from .metrics import (
    FORMATS,
    best_sentence_lcs,
    build_ngram_index,
    classify_format,
    containment,
    coverage,
    distribution,
    tv_distance,
)
from .textbook import get_objectives, load_units, split_sentences, unit_text

TAG_SCHEMA = {
    "type": "object",
    "properties": {
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "objective_id": {"type": "string"}},
                "required": ["id", "objective_id"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["assignments"],
    "additionalProperties": False,
}

SOLVE_SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "answer": {"type": "string"}},
                "required": ["id", "answer"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["answers"],
    "additionalProperties": False,
}


def load_sets(cfg: dict, units: list[str], providers: list[str]):
    base = Path(cfg["data_dir"]) / "generated"
    for unit in units:
        for provider in providers:
            d = base / slug(unit) / provider
            if not d.exists():
                continue
            # 본문 있음(set_*.json)과 본문 없음(notext/set_*.json)을 모두 읽는다. meta.with_text 로 구분된다.
            for p in sorted(d.glob("set_*.json")) + sorted((d / "notext").glob("set_*.json")):
                with open(p, encoding="utf-8") as f:
                    yield unit, provider, int(p.stem.split("_")[1]), json.load(f)


def load_past_exam(cfg: dict, unit: str) -> pd.DataFrame | None:
    p = Path(cfg["data_dir"]) / "past_exams" / f"{slug(unit)}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, encoding="utf-8-sig").fillna("")
    return df if len(df) else None


def item_text(it: dict) -> str:
    return (it.get("stem") or "") + " " + " ".join(it.get("options") or [])


def tag_items(cfg: dict, llm: LLM, unit: str, objectives: list[dict], items: list[dict]) -> dict[int, str]:
    obj_lines = "\n".join(f"{o['id']}: [{o['section']}] {o['text']}" for o in objectives)
    item_lines = "\n".join(
        f"{it['id']}. {it['stem']}" + (f" (보기: {' / '.join(it['options'][:5])})" if it.get("options") else "")
        for it in items
    )
    prompt = (
        f"'{unit}' 단원의 학습목표 목록과 예상문제 목록이다. 각 문항이 주로 묻는 학습목표의 id를 하나 배정하라. "
        "어느 목표에도 해당하지 않거나 단원 범위를 벗어나면 'none'으로 쓴다.\n\n[학습목표]\n"
        + obj_lines
        + "\n\n[문항]\n"
        + item_lines
    )
    t = cfg["tagger"]
    data = llm.complete_json(
        t["provider"],
        prompt,
        TAG_SCHEMA,
        task="tag",
        model=t["model"],
        effort=t.get("effort"),
        mock_ctx={"item_ids": [it["id"] for it in items], "objective_ids": [o["id"] for o in objectives]},
    )
    return {int(a["id"]): str(a["objective_id"]) for a in data.get("assignments", [])}


def solve_items(cfg: dict, llm: LLM, provider: str, unit: str, items_mc: list[dict]) -> dict[int, str]:
    lines = []
    for it in items_mc:
        opts = "\n".join(f"  {i}) {o}" for i, o in enumerate(it["options"], 1))
        lines.append(f"{it['id']}. {it['stem']}\n{opts}")
    prompt = (
        f"고등학교 통합과학2 '{unit}' 단원의 객관식 문항이다. 각 문항의 정답 보기 번호를 '1'~'5' 문자열로 답하라. "
        "문항에 오류가 있어 정답이 없다고 판단되면 가장 가까운 번호를 고르되 반드시 번호를 적는다.\n\n" + "\n\n".join(lines)
    )
    data = llm.complete_json(
        provider,
        prompt,
        SOLVE_SCHEMA,
        task="solve",
        system="너는 고등학교 과학 교사다. 교과서 지식에 근거해 정확히 푼다.",
        mock_ctx={"item_ids": [it["id"] for it in items_mc], "keys": [it["answer"] for it in items_mc]},
    )
    return {int(a["id"]): str(a["answer"]).strip() for a in data.get("answers", [])}


def main(argv=None):
    setup_stdout()
    ap = argparse.ArgumentParser(description="예상문제 세트 측정")
    ap.add_argument("--units")
    ap.add_argument("--providers")
    ap.add_argument("--no-api", action="store_true", help="LLM 태깅과 교차 풀이를 건너뛴다")
    args = ap.parse_args(argv)

    cfg = load_config()
    llm = LLM(cfg)
    units_all = load_units(cfg["textbook_dir"])
    units = [u.strip() for u in args.units.split(",")] if args.units else cfg["units"]
    providers = [p.strip() for p in args.providers.split(",")] if args.providers else list(cfg["providers"].keys())
    solvers = cfg.get("solver_providers", providers)

    # 단원별 준비물: n-gram 색인, 문장, 학습목표, 기출
    prep = {}
    for unit in units:
        text = unit_text(cfg["textbook_dir"], unit)
        objs = [] if args.no_api else get_objectives(cfg, llm, unit)
        past = load_past_exam(cfg, unit)
        past_fmt = None
        past_overlap = None
        school_dists = {}
        between_tv = None
        idx = build_ngram_index(text, 4)
        if past is not None:
            opts = past["options"] if "options" in past.columns else [""] * len(past)
            fmts = [f if f in FORMATS else classify_format(s, "", o) for f, s, o in zip(past["format"], past["stem"], opts)]
            past["_fmt"] = fmts
            past_fmt = distribution(fmts)
            past_overlap = float(sum(containment(s, idx) for s in past["stem"]) / max(1, len(past)))
            if "school" in past.columns:
                for sch, g in past.groupby("school"):
                    if str(sch).strip():
                        school_dists[str(sch)] = {"n": int(len(g)), "format_dist": distribution(list(g["_fmt"]))}
                names = list(school_dists)
                pairs = [tv_distance(school_dists[a]["format_dist"], school_dists[b]["format_dist"]) for i, a in enumerate(names) for b in names[i + 1 :]]
                between_tv = round(sum(pairs) / len(pairs), 3) if pairs else None
        prep[unit] = {
            "ngrams": idx,
            "sentences": split_sentences(text),
            "objectives": objs,
            "past": past,
            "past_fmt": past_fmt,
            "past_overlap": past_overlap,
            "school_dists": school_dists,
            "between_school_tv": between_tv,
        }

    item_rows, set_rows = [], []
    for unit, provider, set_no, data in load_sets(cfg, units, providers):
        P = prep[unit]
        items = data["items"]
        items_mc = [it for it in items if it["type"] == "객관식" and it.get("options")]
        tags = {} if args.no_api or not P["objectives"] else tag_items(cfg, llm, unit, P["objectives"], items)
        solved = {}
        if not args.no_api:
            for s in solvers:
                try:
                    solved[s] = solve_items(cfg, llm, s, unit, items_mc) if items_mc else {}
                except Exception as e:  # 한 모델이 죽어도 나머지는 계속
                    print(f"  [경고] {s} 풀이 실패 ({unit} {provider} set {set_no}): {e}")
                    solved[s] = {}

        fmt_labels, disagree_flags, assigned = [], [], []
        for it in items:
            fmt = classify_format(it["stem"], it["type"], " ".join(it.get("options") or []))
            ov = containment(item_text(it), P["ngrams"], 4)
            lcs, _ = best_sentence_lcs(it["stem"], P["sentences"])
            row = {
                "unit": unit,
                "provider": provider,
                "source": "manual" if data["meta"].get("manual") else "api",
                "with_text": int(data["meta"].get("with_text", True)),
                "model": data["meta"].get("model", ""),
                "set_no": set_no,
                "item_id": it["id"],
                "type": it["type"],
                "format_rule": fmt,
                "difficulty_llm": it.get("difficulty", ""),
                "bloom_llm": it.get("bloom", ""),
                "overlap4": round(ov, 4),
                "stem_lcs": round(lcs, 4),
                "objective_id": tags.get(it["id"], ""),
                # 발문이 '교과서에 제시된', '교과서에서 정의한'처럼 교과서 자체를 가리키면 실제 시험에서는 성립하지 않는 문항이다
                "mentions_textbook": int("교과서" in it["stem"]),
                "key": it.get("answer", ""),
                "stem": it["stem"],
            }
            n_agree, n_solved = 0, 0
            for s in solvers:
                a = solved.get(s, {}).get(it["id"], "")
                row[f"ans_{s}"] = a
                if it["type"] == "객관식" and a:
                    n_solved += 1
                    n_agree += int(a == str(it.get("answer", "")))
            row["n_solved"] = n_solved
            row["n_agree_key"] = n_agree
            row["disagree"] = int(n_solved > 0 and n_agree < n_solved)
            item_rows.append(row)
            fmt_labels.append(fmt)
            assigned.append(row["objective_id"])
            if n_solved:
                disagree_flags.append(row["disagree"])

        fdist = distribution(fmt_labels)
        cov = coverage(assigned, [o["id"] for o in P["objectives"]]) if P["objectives"] else None
        set_rows.append(
            {
                "unit": unit,
                "provider": provider,
                "source": "manual" if data["meta"].get("manual") else "api",
                "with_text": int(data["meta"].get("with_text", True)),
                "model": data["meta"].get("model", ""),
                "set_no": set_no,
                "n_items": len(items),
                "mean_overlap4": round(sum(r["overlap4"] for r in item_rows[-len(items) :]) / max(1, len(items)), 4),
                "mean_stem_lcs": round(sum(r["stem_lcs"] for r in item_rows[-len(items) :]) / max(1, len(items)), 4),
                "coverage_ratio": None if cov is None else round(cov["covered_ratio"], 3),
                "coverage_gini": None if cov is None else cov["gini"],
                "n_unassigned": None if cov is None else cov["unassigned"],
                "missing_objectives": "" if cov is None else ";".join(cov["missing"]),
                "format_tv_vs_past": None if P["past_fmt"] is None else round(tv_distance(fdist, P["past_fmt"]), 3),
                "disagree_rate": None if not disagree_flags else round(sum(disagree_flags) / len(disagree_flags), 3),
                **{f"fmt_{k}": round(v, 3) for k, v in fdist.items()},
            }
        )
        print(f"[{unit}] {provider} set {set_no:02d}: overlap {set_rows[-1]['mean_overlap4']:.2f}, "
              f"coverage {set_rows[-1]['coverage_ratio']}, disagree {set_rows[-1]['disagree_rate']}")

    out_dir = data_path(cfg, "measured", "x").parent
    items_df = pd.DataFrame(item_rows)
    sets_df = pd.DataFrame(set_rows)
    items_df.to_csv(out_dir / "items.csv", index=False, encoding="utf-8-sig")
    sets_df.to_csv(out_dir / "sets.csv", index=False, encoding="utf-8-sig")

    # 요약: 단원×모델
    summary = {}
    if len(sets_df):
        num_cols = [c for c in sets_df.columns if c not in ("unit", "provider", "source", "with_text", "model", "set_no", "missing_objectives")]
        g = sets_df.groupby(["unit", "provider", "source", "with_text"])[num_cols].mean(numeric_only=True).round(3)
        summary["by_unit_provider_source_text"] = {
            f"{u} | {p} | {s} | {'본문있음' if t else '본문없음'}": r.dropna().to_dict() for (u, p, s, t), r in g.iterrows()
        }
    if len(items_df) and "disagree" in items_df:
        # LLM 난이도 라벨이 교차 모델 불일치(실측 난이도의 대리 지표)와 얼마나 가는지
        mc = items_df[items_df["type"] == "객관식"]
        if len(mc):
            summary["disagree_by_llm_difficulty"] = mc.groupby("difficulty_llm")["disagree"].mean().round(3).to_dict()
            summary["disagree_by_llm_bloom"] = mc.groupby("bloom_llm")["disagree"].mean().round(3).to_dict()
    summary["past_exam_baseline"] = {
        u: {
            "overlap4_mean": P["past_overlap"],
            "format_dist": P["past_fmt"],
            "n_items": int(len(P["past"])),
            "schools": P["school_dists"],
            # 학교 간 형식 분포 거리의 평균. AI 세트의 format_tv_vs_past 가 이보다 크면 'AI 세트는 어떤 학교 시험과도 다르다'
            "between_school_tv_mean": P["between_school_tv"],
        }
        for u, P in prep.items()
        if P["past"] is not None
    }
    summary["objectives_used"] = {u: P["objectives"] for u, P in prep.items()}
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("측정 끝. 저장 위치:", out_dir)


if __name__ == "__main__":
    main()
