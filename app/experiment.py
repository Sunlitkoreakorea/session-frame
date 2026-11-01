"""참가자 진행 페이지. API를 쓰지 않는다.

실행: streamlit run app/experiment.py  (mockgap/ 폴더에서)
실습실에서는 연구자 노트북에서 띄우고 같은 와이파이의 주소(Network URL)로 참가자가 접속한다.
참가자는 번호로 들어오고, 진행 상태는 data/experiment/participants/<번호>.json 에 저장되므로 새로고침해도 이어진다.
연구자 모드: 사이드바에 data/experiment/config.json 의 researcher_code 를 넣으면 진행 현황과 CSV 내보내기가 보인다.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mockgap.config import load_config, slug  # noqa: E402
from mockgap.local_tools import local_metrics, parse_ai_output  # noqa: E402
from mockgap.metrics import FORMATS, classify_format  # noqa: E402
from mockgap.textbook import load_units, unit_text  # noqa: E402

st.set_page_config(page_title="진행 페이지", layout="centered")

cfg = load_config()
EXP_DIR = Path(cfg["data_dir"]) / "experiment"
with open(EXP_DIR / "config.json", encoding="utf-8") as f:
    EXP = json.load(f)
UNITS = load_units(cfg["textbook_dir"])
STAGES = ["pre", "s1_source", "s1_warning", "s1_practice", "s1_judge", "s1_test",
          "s2_source", "s2_warning", "s2_practice", "s2_judge", "s2_test", "post", "done"]


# ---------- 저장과 조회 ----------

def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_assignments() -> dict:
    p = EXP_DIR / "assignments.csv"
    if not p.exists():
        # 배정표가 없으면(예: 클라우드 호스팅) 기본 60명 배정표를 만든다
        from mockgap.make_assignments import main as make
        make(["--n", "60"])
    with open(p, encoding="utf-8-sig", newline="") as f:
        return {r["id"].strip().upper(): r for r in csv.DictReader(f)}


def rec_path(pid: str) -> Path:
    d = EXP_DIR / "participants"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{pid}.json"


def load_rec(pid: str) -> dict | None:
    p = rec_path(pid)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_rec(rec: dict) -> None:
    rec["updated"] = now()
    with open(rec_path(rec["id"]), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)


def new_rec(pid: str, a: dict) -> dict:
    return {"id": pid, "group": a["group"], "order": a["order"], "stage": "pre", "created": now(),
            "pre_survey": {}, "sessions": {"A": {}, "B": {}}, "post_survey": {}, "events": []}


def advance(rec: dict, to: str) -> None:
    rec["events"].append({"ts": now(), "from": rec["stage"], "to": to})
    rec["stage"] = to
    save_rec(rec)
    st.rerun()


def session_key(stage: str) -> str:
    return "A" if stage.startswith("s1") else "B"


def session_source(rec: dict, key: str) -> str:
    first = "ai" if rec["order"] == "ai_first" else "exam"
    return first if key == "A" else ("exam" if first == "ai" else "ai")


def unit_of(key: str) -> str:
    return EXP["units"][key]


def short_name(unit: str) -> str:
    return unit.split(" ", 1)[1] if " " in unit else unit


def pages_of(unit: str) -> str:
    u = UNITS[unit]
    return f"{u['start']}~{u['end']}"


def prompt_for(unit: str) -> str:
    return EXP["prompt_template"].format(unit=short_name(unit), pages=pages_of(unit))


def load_set(kind: str, unit: str) -> list[dict]:
    p = EXP_DIR / kind / f"{slug(unit)}.json"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f).get("items", [])


def objectives_for(unit: str) -> list[dict]:
    for name in (f"{slug(unit)}.manual.json", f"{slug(unit)}.json"):
        p = Path(cfg["data_dir"]) / "objectives" / name
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)["objectives"]
    return []


def past_formats_for(unit: str) -> list[str]:
    p = Path(cfg["data_dir"]) / "past_exams" / f"{slug(unit)}.csv"
    if not p.exists():
        return []
    df = pd.read_csv(p, encoding="utf-8-sig").fillna("")
    return [f if f in FORMATS else classify_format(s, "", o) for f, s, o in zip(df["format"], df["stem"], df.get("options", [""] * len(df)))]


def next_after_test(stage: str) -> str:
    return "s2_source" if stage == "s1_test" else "post"


# ---------- 연구자 모드 ----------

def researcher_sidebar() -> None:
    with st.sidebar:
        code = st.text_input("연구자 코드", type="password", key="researcher_code")
        if code and code == EXP.get("researcher_code"):
            st.markdown("**진행 현황**")
            rows = []
            for p in sorted((EXP_DIR / "participants").glob("*.json")) if (EXP_DIR / "participants").exists() else []:
                with open(p, encoding="utf-8") as f:
                    r = json.load(f)
                rows.append({"번호": r["id"], "집단": r["group"], "순서": r["order"], "단계": r["stage"], "갱신": r.get("updated", "")})
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.caption("아직 참가자가 없습니다.")
            if st.button("CSV 내보내기"):
                from mockgap.export_participants import export
                out = export(cfg)
                st.success(f"저장: {out}")


# ---------- 화면 ----------

def page_login() -> None:
    st.title(EXP["title"])
    st.write("연구자가 알려 준 참가자 번호를 입력하고 시작을 누르세요. 중간에 창이 닫혀도 같은 번호로 다시 들어오면 이어서 할 수 있습니다.")
    with st.form("login"):
        pid = st.text_input("참가자 번호 (예: P001)", key="login_pid")
        ok = st.form_submit_button("시작")
    if ok:
        pid = (pid or "").strip().upper()
        a = load_assignments()
        if pid not in a:
            st.error("등록되지 않은 번호입니다. 연구자에게 번호를 다시 확인해 주세요.")
            return
        if load_rec(pid) is None:
            save_rec(new_rec(pid, a[pid]))
        st.session_state["pid"] = pid
        st.rerun()


def page_pre(rec: dict) -> None:
    st.subheader("시작 전 짧은 설문")
    with st.form("pre"):
        apps = st.multiselect("평소 공부할 때 쓰는 AI (모두 고르세요)", EXP["ai_options"], key="pre_apps")
        other = st.text_input("'기타'를 골랐다면 이름", key="pre_other")
        main_app = st.selectbox("가장 자주 쓰는 AI", EXP["ai_options"], key="pre_main")
        freq = st.select_slider("AI를 공부에 쓰는 빈도", ["거의 안 씀", "한 달에 몇 번", "일주일에 몇 번", "거의 매일"], value="일주일에 몇 번", key="pre_freq")
        trust = st.slider("AI가 알려 주는 공부 내용을 믿는 편이다 (1 전혀 아니다 ~ 7 매우 그렇다)", 1, 7, 4, key="pre_trust")
        verify = st.slider("AI 답을 교과서나 다른 자료로 확인하는 편이다", 1, 7, 4, key="pre_verify")
        conf = st.slider("통합과학 과목에 자신이 있다", 1, 7, 4, key="pre_conf")
        ok = st.form_submit_button("저장하고 다음")
    if ok:
        rec["pre_survey"] = {"apps": apps, "other": other, "main_app": main_app, "freq": freq, "trust": trust, "verify": verify, "confidence": conf, "ts": now()}
        advance(rec, "s1_source")


def page_source(rec: dict, stage: str) -> None:
    key = session_key(stage)
    unit = unit_of(key)
    src = session_source(rec, key)
    n = 1 if key == "A" else 2
    st.subheader(f"{n}번째 공부: {short_name(unit)} 단원")
    sess = rec["sessions"].get(key) or {}
    if src == "ai":
        st.markdown(
            "1. 평소 쓰는 AI 앱을 열고 **새 대화**를 시작하세요.\n"
            "2. 아래 문장을 그대로 복사해서 보내세요 (오른쪽 위 복사 버튼).\n"
            "3. AI가 준 답 **전체**를 복사해서 아래 칸에 붙여 넣으세요. 답이 중간에 끊기면 '이어서 보여줘'라고 한 뒤 이어 붙이세요."
        )
        st.code(prompt_for(unit), language=None)
        with st.form(f"src_{key}"):
            app = st.selectbox("어떤 AI를 썼나요?", EXP["ai_options"], key=f"app_{key}")
            app_other = st.text_input("'기타'이면 이름", key=f"app_other_{key}")
            model = st.text_input("모델 이름 (화면에 보이면 적어 주세요. 몰라도 됩니다)", key=f"model_{key}")
            raw = st.text_area("AI가 준 답 전체 붙여넣기", height=320, key=f"raw_{key}")
            force = st.checkbox("문항 수가 부족해도 그대로 진행 (연구자 확인 후에만 체크)", key=f"force_{key}")
            ok = st.form_submit_button("저장하고 다음")
        if ok:
            if not raw.strip():
                st.error("붙여 넣은 내용이 없습니다.")
                return
            items = parse_ai_output(raw)
            n_items = len(items)
            if n_items < EXP["min_items"] and not force:
                st.warning(f"문항이 {n_items}개만 인식됐습니다. AI에게 '20문항을 모두 다시 보여줘'라고 요청해서 전체를 다시 붙여 넣어 주세요. 문항이 분명히 다 있는데도 이 말이 나오면 연구자를 불러 주세요.")
                return
            metrics = local_metrics(items, unit_text(cfg["textbook_dir"], unit), objectives_for(unit), past_formats_for(unit))
            rec["sessions"][key] = {
                "unit": unit, "source": "ai", "ai_app": app, "ai_app_other": app_other, "ai_model": model,
                "raw": raw, "parsed": items, "n_parsed": n_items, "parse_ok": n_items >= 10, "forced": bool(force),
                "metrics": {k: v for k, v in metrics.items() if k != "rows"}, "metric_rows": metrics["rows"],
                "warning": {"shown": rec["group"] == "warn"}, "practice": {}, "judge": {}, "test": {}, "ts": now(),
            }
            advance(rec, f"s{n}_warning" if rec["group"] == "warn" else f"s{n}_practice")
    else:
        st.write("이번 단원은 연구자가 준비한 연습 문제로 공부합니다. 다음을 누르면 문제가 나옵니다.")
        if st.button("다음", key=f"exam_next_{key}"):
            rec["sessions"][key] = {"unit": unit, "source": "exam", "warning": {"shown": False}, "practice": {}, "judge": {}, "test": {}, "ts": now()}
            advance(rec, f"s{n}_practice")


def page_warning(rec: dict, stage: str) -> None:
    key = session_key(stage)
    sess = rec["sessions"][key]
    m = sess["metrics"]
    n = 1 if key == "A" else 2
    if not sess["warning"].get("shown_at"):
        sess["warning"]["shown_at"] = now()
        sess["warning"]["_t0"] = time.time()
        save_rec(rec)
    st.subheader("받은 문제 세트 검사 결과")
    st.write("붙여 넣은 문제를 교과서 범위와 시험 형식에 비추어 확인한 결과입니다. 읽고 나서 아래 버튼을 누르면 연습이 시작됩니다.")
    c1, c2, c3 = st.columns(3)
    c1.metric("교과서 문장 겹침", f"{m['mean_overlap4']:.2f}", help="문항 글자의 몇 %가 교과서 문장에 그대로 있는지. 1에 가까우면 책 문장을 그대로 묻는 문항.")
    c2.metric("학습목표 덮임(근사)", "-" if "coverage_ratio" not in m else f"{m['coverage_ratio']*100:.0f}%")
    c3.metric("기출과 형식 거리", "-" if "format_tv_vs_past" not in m else f"{m['format_tv_vs_past']:.2f}")
    notes = []
    if m["mean_overlap4"] > 0.6 or m["high_overlap_ratio"] > 0.3:
        notes.append("교과서 문장을 거의 그대로 묻는 문항이 많습니다. 다른 표현으로 나오는 문제에도 답할 수 있는지 스스로 확인해 보세요.")
    if m.get("missing_objectives"):
        names = "; ".join(o["text"] for o in m["missing_objectives"][:6])
        notes.append(f"이 세트가 다루지 않은 학습목표: {names}")
    if m.get("format_short"):
        notes.append("기출에 비해 부족한 형식: " + ", ".join(m["format_short"]))
    if m["textbook_mentions"]:
        notes.append(f"'교과서에 나온 것은?'처럼 교과서 자체를 가리키는 문항 {m['textbook_mentions']}: 실제 시험에는 나오지 않는 형태입니다.")
    if m["missing_answers"]:
        notes.append(f"정답이 안 보이는 문항 {m['missing_answers']}")
    if m["n_mc"] < 16 or m["n_sa"] < 4:
        notes.append(f"인식된 문항: 객관식 {m['n_mc']}개, 서술형 {m['n_sa']}개")
    if notes:
        for t in notes:
            st.warning(t)
    else:
        st.info("눈에 띄는 점은 없습니다. 그래도 정답과 해설이 맞는지는 보장되지 않습니다.")
    if st.button("확인했습니다. 연습 시작", key=f"warn_ok_{key}"):
        t0 = sess["warning"].pop("_t0", None)
        sess["warning"]["confirmed_at"] = now()
        sess["warning"]["dwell_s"] = round(time.time() - t0, 1) if t0 else None
        advance(rec, f"s{n}_practice")


def render_items(items: list[dict], show_answers: bool = True) -> None:
    for it in items:
        st.markdown(f"**{it['id']}.** {it['stem']}")
        if it.get("options"):
            st.markdown("  \n".join(f"&nbsp;&nbsp;{i}) {o}" for i, o in enumerate(it["options"], 1)))
        if show_answers:
            with st.expander("정답과 해설"):
                st.write(f"정답: {it.get('answer', '') or '(없음)'}")
                if it.get("explanation"):
                    st.write(f"해설: {it['explanation']}")


def page_practice(rec: dict, stage: str) -> None:
    key = session_key(stage)
    sess = rec["sessions"][key]
    unit = sess["unit"]
    n = 1 if key == "A" else 2
    pr = sess.setdefault("practice", {})
    if not pr.get("started_at"):
        pr["started_at"] = now()
        pr["_t0"] = time.time()
        pr["confirm_count"] = 0
        save_rec(rec)
    elapsed_min = (time.time() - pr.get("_t0", time.time())) / 60
    st.subheader(f"연습: {short_name(unit)} 단원 ({EXP['practice_minutes']}분)")
    st.caption(f"시작 {pr['started_at'][11:16]} · 지금까지 약 {elapsed_min:.0f}분 · 문제를 풀고 '정답과 해설'을 열어 확인하세요. 연습 중에는 AI에게 질문하지 않습니다.")
    cols = st.columns([1, 1])
    if cols[0].button(f"교과서를 찾아봤다 (+1) · 현재 {pr.get('confirm_count', 0)}회", key=f"confirm_{key}"):
        pr["confirm_count"] = pr.get("confirm_count", 0) + 1
        save_rec(rec)
        st.rerun()
    if cols[1].button("연습 끝내기", key=f"end_{key}"):
        pr["ended_at"] = now()
        pr["elapsed_min"] = round(elapsed_min, 1)
        pr.pop("_t0", None)
        advance(rec, f"s{n}_judge")
    st.divider()
    if sess["source"] == "ai":
        if sess.get("parse_ok"):
            render_items(sess["parsed"])
        else:
            st.info("문항을 자동으로 나누지 못해 받은 답을 그대로 보여 줍니다.")
            st.text_area("받은 답", sess["raw"], height=500, disabled=True, key=f"rawview_{key}")
    else:
        render_items(load_set("practice_sets", unit))


def page_judge(rec: dict, stage: str) -> None:
    key = session_key(stage)
    sess = rec["sessions"][key]
    n = 1 if key == "A" else 2
    st.subheader("연습을 마친 뒤의 생각")
    st.write("곧 이 단원의 시험을 봅니다. 20문항이고 100점 만점입니다.")
    with st.form(f"judge_{key}"):
        predicted = st.slider("이 단원 시험에서 몇 점을 받을 것 같나요?", 0, 100, 50, step=5, key=f"pred_{key}")
        readiness = st.slider("이 단원 시험 준비가 됐다고 느낀다 (1 전혀 ~ 7 매우)", 1, 7, 4, key=f"ready_{key}")
        similar = st.slider("방금 푼 연습 문제가 실제 시험과 비슷할 것 같다", 1, 7, 4, key=f"sim_{key}")
        key_trust = st.slider("연습 문제의 정답과 해설을 믿었다", 1, 7, 4, key=f"ktrust_{key}")
        ok = st.form_submit_button("저장하고 시험 시작")
    if ok:
        sess["judge"] = {"predicted": predicted, "readiness": readiness, "similar": similar, "key_trust": key_trust, "ts": now()}
        advance(rec, f"s{n}_test")


def page_test(rec: dict, stage: str) -> None:
    key = session_key(stage)
    sess = rec["sessions"][key]
    unit = sess["unit"]
    items = load_set("tests", unit)
    st.subheader(f"시험: {short_name(unit)} 단원 ({EXP['test_minutes']}분)")
    st.caption("교과서, 필기, AI는 쓰지 않습니다. 모든 객관식에 답해야 제출됩니다.")
    with st.form(f"test_{key}"):
        answers = {}
        for it in items:
            if it["type"] == "객관식":
                choice = st.radio(f"{it['id']}. {it['stem']}", [f"{i}) {o}" for i, o in enumerate(it["options"], 1)], index=None, key=f"t_{key}_{it['id']}")
                answers[str(it["id"])] = choice.split(")")[0] if choice else ""
            else:
                answers[str(it["id"])] = st.text_area(f"{it['id']}. {it['stem']}", key=f"t_{key}_{it['id']}", height=100)
        ok = st.form_submit_button("제출")
    if ok:
        missing = [it["id"] for it in items if it["type"] == "객관식" and not answers.get(str(it["id"]))]
        if missing:
            st.error(f"답하지 않은 객관식: {missing}")
            return
        mc = [it for it in items if it["type"] == "객관식"]
        correct = sum(1 for it in mc if answers.get(str(it["id"])) == str(it["answer"]))
        sess["test"] = {"answers": answers, "mc_correct": correct, "mc_total": len(mc),
                        "mc_pct": round(100 * correct / max(1, len(mc)), 1), "n_sa": len(items) - len(mc), "ts": now()}
        advance(rec, next_after_test(stage))


def page_post(rec: dict) -> None:
    st.subheader("마지막 설문")
    with st.form("post"):
        saw = st.radio("AI가 만든 문제 중에 틀렸거나 이상한 문항이 있었다고 생각하나요?", ["예", "아니오", "잘 모르겠다", "AI 문제를 받지 않았다"], index=None, key="post_saw")
        which = st.text_input("있었다면 몇 번이었나요? (기억나는 대로)", key="post_which")
        used_ai = st.radio("연습 중에 AI에게 질문한 적이 있나요? (솔직하게 답해도 불이익이 없습니다)", ["없다", "한두 번", "여러 번"], index=None, key="post_used")
        comment = st.text_area("공부하면서 느낀 점 (자유롭게)", key="post_comment")
        ok = st.form_submit_button("제출")
    if ok:
        if saw is None or used_ai is None:
            st.error("두 질문에 모두 답해 주세요.")
            return
        rec["post_survey"] = {"saw_errors": saw, "which": which, "used_ai_in_practice": used_ai, "comment": comment, "ts": now()}
        advance(rec, "done")


def page_done(rec: dict) -> None:
    st.success("참여해 주셔서 고맙습니다. 모든 과정이 끝났습니다.")
    st.markdown("**연구 설명**")
    st.write(EXP["debrief"])
    st.caption("이 창은 닫아도 됩니다.")


# ---------- 흐름 ----------

researcher_sidebar()
if "pid" not in st.session_state:
    page_login()
    st.stop()

pid = st.session_state["pid"]
rec = load_rec(pid)
if rec is None:
    st.session_state.pop("pid", None)
    st.rerun()

idx = STAGES.index(rec["stage"]) if rec["stage"] in STAGES else 0
st.progress((idx + 1) / len(STAGES), text=f"참가자 {pid} · 진행 {idx + 1}/{len(STAGES)}")
stage = rec["stage"]
if stage == "pre":
    page_pre(rec)
elif stage.endswith("_source"):
    page_source(rec, stage)
elif stage.endswith("_warning"):
    page_warning(rec, stage)
elif stage.endswith("_practice"):
    page_practice(rec, stage)
elif stage.endswith("_judge"):
    page_judge(rec, stage)
elif stage.endswith("_test"):
    page_test(rec, stage)
elif stage == "post":
    page_post(rec)
else:
    page_done(rec)
