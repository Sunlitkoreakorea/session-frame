"""API 없이 돌아가는 도구들.

- parse_ai_output(): 챗 앱에서 복사한 문항 텍스트를 문항 목록으로 쪼갠다.
  번호 매김, ①~⑤ 또는 1)~5) 보기, '정답:', '해설:' 줄을 알아본다. 완벽하지 않으므로 원문은 항상 같이 저장한다.
- assign_objectives_local(): 글자 n-gram 겹침으로 문항을 학습목표에 근사 배정한다. LLM 태깅의 대용이며 '근사'라고 표시한다.
- local_metrics(): 진행 페이지의 검사 화면에 쓰는 지표 묶음.
"""
from __future__ import annotations

import re

from .metrics import FORMATS, build_ngram_index, char_ngrams, classify_format, containment, distribution, tv_distance

CIRCLED = "①②③④⑤"
_NUM = re.compile(r"^\s*(?:\*\*)?(?:#+\s*)?(?:문제|문항|Q|q)?\s*(\d{1,2})\s*(?:[\.\)\]번:：]|\*\*)\s*(.*)$")
_OPT = re.compile(r"^\s*(?:\*\*)?(?:[\(\[]?([1-5])[\)\]\.]|([①②③④⑤]))\s*(?:\*\*)?\s*(.+)$")
_ANS = re.compile(r"^\s*(?:\*\*)?(?:정답|답)\s*(?:\*\*)?\s*[:：]?\s*(?:\*\*)?\s*(.*)$")
_ANS_NUM = re.compile(r"[\(\[]?([1-5])[\)\]]?\s*번?|([①②③④⑤])")
_EXPL = re.compile(r"^\s*(?:\*\*)?(?:해설|풀이|설명|근거)\s*(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*(.*)$")
_MODEL = re.compile(r"^\s*(?:\*\*)?(?:모범\s*답안|예시\s*답안|모범답)\s*(?:\*\*)?\s*[:：]?\s*(?:\*\*)?\s*(.*)$")
_SECTION = re.compile(r"^\s*(?:#+\s*|\*\*|\[|【)?\s*(객관식|서술형|선택형|주관식)", re.I)
_META = re.compile(r"^\s*(?:난이도|유형|출제\s*의도|관련\s*단원|사고\s*수준)\s*[:：]")


def _clean(s: str) -> str:
    return re.sub(r"\*\*|__|`", "", s).strip()


_INLINE_MARK = re.compile(r"(?:(?<=\s)|^)(?:[\(\[]([1-5])[\)\]]|([①②③④⑤]))\s*")


def _explode_lines(text: str) -> list[str]:
    """'(1) C (2) CO₂ (3) CuO ...' 처럼 보기가 한 줄에 몰린 경우 줄로 나누고, '정답: (3) 해설: ...' 도 두 줄로 나눈다."""
    out = []
    for raw in text.replace("\r", "").split("\n"):
        line = raw.rstrip()
        if re.search(r"(정답|답)\s*[:：]", line) and "해설" in line:
            a, b = re.split(r"(?=해설\s*[:：])", line, maxsplit=1)
            out.extend([a.rstrip(), b])
            continue
        marks = list(_INLINE_MARK.finditer(line))
        if len(marks) >= 3:
            # 문제 번호와 발문이 같은 줄에 있으면 그 부분은 그대로 남기고 보기만 줄로 나눈다
            head = line[: marks[0].start()].rstrip()
            if head:
                out.append(head)
            for i, m in enumerate(marks):
                end = marks[i + 1].start() if i + 1 < len(marks) else len(line)
                label = m.group(1) or m.group(2)
                out.append(f"{label}) {line[m.end():end].strip()}" if m.group(1) else f"{label} {line[m.end():end].strip()}")
            continue
        out.append(line)
    return out


def parse_ai_output(text: str) -> list[dict]:
    items: list[dict] = []
    cur: dict | None = None
    hint = ""

    def new_item(n: int, stem: str):
        nonlocal cur
        cur = {"id": n, "type": "객관식", "stem": _clean(stem), "options": [], "answer": "", "explanation": "", "hint": hint}
        items.append(cur)

    for raw in _explode_lines(text):
        line = raw.rstrip()
        if not line.strip():
            continue
        if _SECTION.match(line) and len(_clean(line)) < 25:
            hint = "서술형" if ("서술" in line or "주관" in line) else "객관식"
            continue
        if _META.match(line):
            continue
        m_num = _NUM.match(line)
        m_opt = _OPT.match(line)
        if m_num:
            n = int(m_num.group(1))
            # '1) 보기' 처럼 생긴 줄은 보기이고, '2. 문제' 처럼 다음 번호가 오면 새 문항이다
            is_option = (
                cur is not None
                and m_opt is not None
                and not cur["answer"]
                and n <= 5
                and n == len(cur["options"]) + 1
                and (len(cur["options"]) > 0 or n == 1)
            )
            if not is_option and (cur is None or n > cur["id"] or n == 1):
                new_item(n, m_num.group(2))
                continue
        if cur is None:
            continue
        m_ans = _ANS.match(line)
        if m_ans:
            a = _clean(m_ans.group(1))
            m = _ANS_NUM.search(a)
            if cur["options"] and m:
                cur["answer"] = m.group(1) or str(CIRCLED.index(m.group(2)) + 1)
            else:
                cur["answer"] = a
            continue
        m_model = _MODEL.match(line)
        if m_model:
            cur["answer"] = _clean(m_model.group(1))
            cur["type"] = "서술형"
            continue
        m_expl = _EXPL.match(line)
        if m_expl:
            cur["explanation"] = (cur["explanation"] + " " + _clean(m_expl.group(1))).strip()
            continue
        if m_opt and not cur["answer"] and len(cur["options"]) < 5:
            cur["options"].append(_clean(m_opt.group(3)))
            continue
        # 이어지는 줄
        if cur["explanation"]:
            cur["explanation"] += " " + _clean(line)
        elif cur["answer"] and cur["type"] == "서술형":
            cur["answer"] += " " + _clean(line)
        elif cur["options"]:
            cur["options"][-1] += " " + _clean(line)
        else:
            cur["stem"] = (cur["stem"] + " " + _clean(line)).strip()

    for k, it in enumerate(items, 1):
        it["id"] = k
        if len(it["options"]) >= 2:
            it["type"] = "객관식"
            a = it["answer"]
            if a and a not in "12345":
                m = _ANS_NUM.search(a)
                it["answer"] = (m.group(1) or str(CIRCLED.index(m.group(2)) + 1)) if m else ""
        else:
            it["type"] = "서술형"
            it["options"] = []
        it.pop("hint", None)
    return [it for it in items if it["stem"]]


def assign_objectives_local(items: list[dict], objectives: list[dict], n: int = 3, min_score: float = 0.10) -> dict[int, str]:
    """문항 글자 n-gram이 학습목표 문장의 n-gram을 얼마나 덮는지로 배정한다. 근사치다."""
    obj_grams = {o["id"]: char_ngrams(o["text"], n) for o in objectives}
    out = {}
    for it in items:
        grams = char_ngrams(it["stem"] + " " + " ".join(it.get("options") or []), n)
        best, best_s = "none", 0.0
        for oid, og in obj_grams.items():
            if not og:
                continue
            s = len(grams & og) / len(og)
            if s > best_s:
                best, best_s = oid, s
        out[it["id"]] = best if best_s >= min_score else "none"
    return out


def local_metrics(items: list[dict], unit_text: str, objectives: list[dict] | None = None, past_formats: list[str] | None = None) -> dict:
    idx = build_ngram_index(unit_text, 4)
    rows = []
    for it in items:
        txt = it["stem"] + " " + " ".join(it.get("options") or [])
        rows.append(
            {
                "id": it["id"],
                "type": it["type"],
                "format": classify_format(it["stem"], it["type"], " ".join(it.get("options") or [])),
                "overlap4": round(containment(txt, idx, 4), 3),
                "mentions_textbook": int("교과서" in it["stem"]),
                "has_answer": int(bool(it.get("answer"))),
            }
        )
    fdist = distribution([r["format"] for r in rows])
    out = {
        "n_items": len(items),
        "n_mc": sum(1 for r in rows if r["type"] == "객관식"),
        "n_sa": sum(1 for r in rows if r["type"] == "서술형"),
        "mean_overlap4": round(sum(r["overlap4"] for r in rows) / max(1, len(rows)), 3),
        "high_overlap_ratio": round(sum(1 for r in rows if r["overlap4"] > 0.6) / max(1, len(rows)), 3),
        "textbook_mentions": [r["id"] for r in rows if r["mentions_textbook"]],
        "missing_answers": [r["id"] for r in rows if not r["has_answer"]],
        "format_dist": fdist,
        "rows": rows,
    }
    if past_formats:
        pf = distribution(past_formats)
        out["past_format_dist"] = pf
        out["format_tv_vs_past"] = round(tv_distance(fdist, pf), 3)
        out["format_short"] = [k for k in FORMATS if fdist.get(k, 0) - pf.get(k, 0) < -0.1]
    if objectives:
        tags = assign_objectives_local(items, objectives)
        covered = {oid for oid in tags.values() if oid != "none"}
        out["objective_tags"] = tags
        out["coverage_ratio"] = round(len(covered) / max(1, len(objectives)), 3)
        out["missing_objectives"] = [o for o in objectives if o["id"] not in covered]
    return out
