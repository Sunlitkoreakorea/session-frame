"""세트 검사 페이지.

실행:  streamlit run app/checker.py      (mockgap/ 폴더에서)
API 키가 없어도 베끼기 점수와 형식 분포는 계산된다. 범위 적합도와 교차 모델 검증은 'API 사용'을 켜야 한다.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mockgap.config import load_config, slug  # noqa: E402
from mockgap.generate import GEN_SCHEMA, validate_items  # noqa: E402
from mockgap.llm import LLM, MockBackend  # noqa: E402
from mockgap.measure import item_text, load_past_exam, solve_items, tag_items  # noqa: E402
from mockgap.metrics import (  # noqa: E402
    FORMATS,
    best_sentence_lcs,
    build_ngram_index,
    classify_format,
    containment,
    coverage,
    distribution,
    tv_distance,
)
from mockgap.textbook import get_objectives, load_units, split_sentences, unit_text  # noqa: E402

st.set_page_config(page_title="세트 검사기", layout="wide")
st.title("세트 검사기")
st.caption("붙여 넣은 문항 세트의 지표를 보여준다.")

cfg = load_config()
units_all = load_units(cfg["textbook_dir"])

with st.sidebar:
    unit = st.selectbox("단원", list(units_all.keys()), index=list(units_all.keys()).index(cfg["units"][0]) if cfg["units"][0] in units_all else 0)
    use_api = st.checkbox("API 사용 (범위 적합도, 교차 모델 검증)", value=False)
    solvers = st.multiselect("교차 검증에 쓸 모델", list(cfg["providers"].keys()), default=cfg.get("solver_providers", []))
    st.markdown("---")
    st.markdown("**읽는 법**\n- 베끼기 점수: 문항 글자 4-gram 중 교과서에 그대로 있는 비율. 1에 가까우면 책 문장을 그대로 묻는 문항.\n- 범위 덮임: 학습목표 중 문항이 하나라도 있는 비율.\n- 형식 거리: 기출 형식 분포와의 총변동 거리 (0 같음, 1 완전히 다름).")

tab_text, tab_json, tab_gen = st.tabs(["텍스트 붙여넣기", "JSON 업로드", "생성된 세트 고르기"])
items = None
with tab_text:
    raw = st.text_area("ChatGPT 등에서 받은 예상문제를 그대로 붙여 넣기", height=220, placeholder="1. 다음 중 ... ?\n① ... ② ... ③ ... ④ ... ⑤ ...\n정답: ②\n2. ...")
    if st.button("텍스트 분석") and raw.strip():
        if use_api:
            llm = LLM(cfg)
            t = cfg["tagger"]
            data = llm.complete_json(
                t["provider"],
                "다음 텍스트에서 문항을 추출해 JSON으로 정리하라. 객관식은 options에 보기를, answer에 정답 번호('1'~'5')를 쓴다. "
                "정답이 적혀 있지 않으면 네가 푼 답을 쓴다. 서술형은 options를 비우고 answer에 모범답안을 쓴다. "
                "difficulty와 bloom은 모르면 '중', '이해'로 둔다.\n\n" + raw,
                GEN_SCHEMA,
                task="parse_items",
                model=t["model"],
                effort=t.get("effort"),
                mock_ctx={"text": raw},
            )
            items = validate_items(data.get("items", []), 200)
        else:
            items = validate_items(MockBackend(random.Random(0)).run("parse_items", {"text": raw}, {})["items"], 200)
with tab_json:
    up = st.file_uploader("세트 JSON (items 배열)", type=["json"])
    if up is not None:
        data = json.load(up)
        items = validate_items(data.get("items", data if isinstance(data, list) else []), 200)
with tab_gen:
    gen_dir = Path(cfg["data_dir"]) / "generated" / slug(unit)
    choices = sorted(str(p.relative_to(gen_dir)) for p in gen_dir.glob("*/set_*.json")) if gen_dir.exists() else []
    pick = st.selectbox("data/generated 에 있는 세트", ["(선택)"] + choices)
    if pick != "(선택)":
        with open(gen_dir / pick, encoding="utf-8") as f:
            items = validate_items(json.load(f)["items"], 200)

if not items:
    st.info("왼쪽에서 단원을 고르고, 위에서 문항을 넣으면 분석한다.")
    st.stop()

# ---------- 로컬 지표 ----------
text = unit_text(cfg["textbook_dir"], unit)
idx = build_ngram_index(text, 4)
sents = split_sentences(text)
rows = []
for it in items:
    lcs, near = best_sentence_lcs(it["stem"], sents)
    rows.append(
        {
            "id": it["id"],
            "유형": it["type"],
            "형식": classify_format(it["stem"], it["type"], " ".join(it.get("options") or [])),
            "베끼기": round(containment(item_text(it), idx), 2),
            "유사문장LCS": round(lcs, 2),
            "정답": it.get("answer", ""),
            "발문": it["stem"],
            "가장 비슷한 교과서 문장": near[:80],
        }
    )
df = pd.DataFrame(rows)
fdist = distribution(df["형식"].tolist())
past = load_past_exam(cfg, unit)
past_fmt, past_overlap = None, None
if past is not None:
    pf = [f if f in FORMATS else classify_format(s) for f, s in zip(past["format"], past["stem"])]
    past_fmt = distribution(pf)
    past_overlap = sum(containment(s, idx) for s in past["stem"]) / max(1, len(past))

# ---------- API 지표 ----------
cov, disagree_ids, objectives = None, [], []
if use_api:
    llm = LLM(cfg)
    with st.spinner("학습목표 배정과 교차 풀이 중..."):
        objectives = get_objectives(cfg, llm, unit)
        tags = tag_items(cfg, llm, unit, objectives, items)
        df["학습목표"] = [tags.get(i, "") for i in df["id"]]
        cov = coverage(df["학습목표"].tolist(), [o["id"] for o in objectives])
        mc = [it for it in items if it["type"] == "객관식" and it.get("options")]
        answers = {}
        for s in solvers:
            try:
                answers[s] = solve_items(cfg, llm, s, unit, mc) if mc else {}
            except Exception as e:
                st.warning(f"{s} 풀이 실패: {e}")
        for s, a in answers.items():
            df[f"답_{s}"] = [a.get(i, "") for i in df["id"]]
        for it in mc:
            got = [answers[s].get(it["id"], "") for s in answers if answers[s].get(it["id"], "")]
            if got and any(g != str(it["answer"]) for g in got):
                disagree_ids.append(it["id"])
        df["정답갈림"] = df["id"].isin(disagree_ids)

# ---------- 요약 ----------
c1, c2, c3, c4 = st.columns(4)
c1.metric("평균 베끼기 점수", f"{df['베끼기'].mean():.2f}", help=None if past_overlap is None else f"기출 기준선 {past_overlap:.2f}")
c2.metric("범위 덮임", "-" if cov is None else f"{cov['covered_ratio']*100:.0f}%")
c3.metric("기출과 형식 거리", "-" if past_fmt is None else f"{tv_distance(fdist, past_fmt):.2f}")
c4.metric("정답 갈리는 문항", "-" if not use_api else str(len(disagree_ids)))

warnings = []
if df["베끼기"].mean() > 0.6:
    warnings.append("책 문장을 거의 그대로 묻는 문항이 많다. 풀리는 느낌은 좋지만 다른 표현으로 나오는 시험에는 약할 수 있다.")
if (df["베끼기"] > 0.8).mean() > 0.3:
    warnings.append(f"문항의 {int((df['베끼기'] > 0.8).mean()*100)}%가 교과서 문장을 거의 통째로 담고 있다.")
if cov is not None and cov["covered_ratio"] < 0.7:
    names = {o["id"]: o["text"] for o in objectives}
    warnings.append("빠진 학습목표: " + "; ".join(f"{m} {names.get(m, '')}" for m in cov["missing"]))
if cov is not None and cov["gini"] > 0.4:
    warnings.append("문항이 몇 개 학습목표에 몰려 있다.")
if past_fmt is not None and tv_distance(fdist, past_fmt) > 0.3:
    diff = {k: round(fdist.get(k, 0) - past_fmt.get(k, 0), 2) for k in FORMATS}
    low = [k for k, v in diff.items() if v < -0.1]
    warnings.append("기출에 비해 부족한 형식: " + (", ".join(low) if low else "없음") + f" (차이 {diff})")
tb = [it["id"] for it in items if "교과서" in it["stem"]]
if tb:
    warnings.append(f"발문이 교과서 자체를 가리키는 문항 {tb}: '교과서에 제시된 것은?' 같은 문항은 실제 시험에서는 나올 수 없다.")
if disagree_ids:
    warnings.append(f"다른 모델이 다른 답을 낸 문항 {disagree_ids}: 정답지를 그대로 믿지 말고 교과서로 확인할 것.")
if use_api and not disagree_ids and cov is not None:
    warnings.append("교차 검증에서 정답이 갈린 문항은 없다. 그래도 정답지가 맞다는 보장은 아니다.")

st.subheader("경고")
if warnings:
    for w in warnings:
        st.warning(w)
else:
    st.success("눈에 띄는 경고 없음. (API를 켜면 범위와 정답 검증도 본다.)")

calib = Path(cfg["data_dir"]) / "calibration_model.json"
st.subheader("보정 경고")
if calib.exists():
    with open(calib, encoding="utf-8") as f:
        m = json.load(f)
    est = m.get("intercept", 0) + m.get("b_overlap", 0) * df["베끼기"].mean() + (m.get("b_coverage", 0) * cov["covered_ratio"] if cov else 0)
    st.info(f"2단계 자료 기준으로, 이 세트로 연습하면 예상 점수가 실제보다 약 {est:.1f}점 부풀 수 있다.")
else:
    st.caption("2단계 사람 실험 자료가 쌓이면 여기에 '예상 점수 부풀림 추정치'가 표시된다. (data/calibration_model.json)")

st.subheader("형식 분포")
fd = pd.DataFrame({"이 세트": fdist, **({"기출": past_fmt} if past_fmt else {})})
st.bar_chart(fd)

if cov is not None:
    st.subheader("학습목표별 문항 수")
    st.dataframe(pd.DataFrame([{"id": o["id"], "소단원": o["section"], "학습목표": o["text"], "문항 수": cov["counts"].get(o["id"], 0)} for o in objectives]), use_container_width=True)

st.subheader("문항별")
st.dataframe(df, use_container_width=True)
