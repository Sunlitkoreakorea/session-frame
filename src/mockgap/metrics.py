"""API 없이 계산하는 지표들: 원문 베끼기 점수, 형식 분류, 분포 거리, 범위 적합도."""
from __future__ import annotations

import re
from collections import Counter

FORMATS = ["개념 확인", "자료 해석", "계산", "서술형", "탐구 설계"]

_PUNCT = re.compile(r"[\s\.,;:!?\(\)\[\]{}「」『』“”‘’\"'·…ㆍ\-–—/\\|~^*_=+<>①②③④⑤]")


def normalize(s: str) -> str:
    """공백과 문장부호를 빼서 글자만 남긴다."""
    return _PUNCT.sub("", s or "")


def char_ngrams(s: str, n: int) -> set[str]:
    s = normalize(s)
    if len(s) < n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def build_ngram_index(text: str, n: int = 4) -> set[str]:
    """단원 전체 텍스트의 글자 n-gram 집합."""
    return char_ngrams(text, n)


def containment(item_text: str, unit_ngrams: set[str], n: int = 4) -> float:
    """문항 글자 n-gram 중 단원 텍스트에 그대로 나오는 비율. 1에 가까울수록 책을 베낀 문항."""
    grams = char_ngrams(item_text, n)
    if not grams:
        return 0.0
    return sum(1 for g in grams if g in unit_ngrams) / len(grams)


def lcs_len(a: str, b: str) -> int:
    """두 문자열의 최장 공통 부분수열 길이 (O(len(a)*len(b)))."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0]
        for j, cb in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if ca == cb else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def best_sentence_lcs(stem: str, sentences: list[str], n: int = 3, top_k: int = 5) -> tuple[float, str]:
    """n-gram 겹침이 큰 문장 top_k 안에서 LCS 비율이 가장 높은 문장을 찾는다.
    반환: (LCS 길이 / 문항 글자 수, 그 문장)."""
    s = normalize(stem)
    if not s or not sentences:
        return 0.0, ""
    grams = char_ngrams(stem, n)
    scored = []
    for sent in sentences:
        sg = char_ngrams(sent, n)
        if not sg:
            continue
        ov = len(grams & sg) / max(1, len(grams))
        scored.append((ov, sent))
    scored.sort(key=lambda x: x[0], reverse=True)
    best, best_sent = 0.0, ""
    for _, sent in scored[:top_k]:
        r = lcs_len(s, normalize(sent)) / len(s)
        if r > best:
            best, best_sent = r, sent
    return best, best_sent


_UNIT_WORDS = re.compile(r"\d+(\.\d+)?\s*(g|kg|mg|mL|L|J|kJ|W|kW|kWh|%|℃|°C|mol|M|N|m|cm|km|s|초|분|년|배|개|ppm|V|A)\b")
_CALC_WORDS = ("구하시오", "계산", "몇 ", "얼마", "비율은", "효율은", "농도는", "질량은", "부피는", "에너지는 몇")
_DATA_WORDS = ("표", "그래프", "그림", "자료", "다음은", "다음과 같이", "실험 결과", "(가)", "(나)", "A~", "ㄱ.", "보기")
_DESIGN_WORDS = ("설계", "실험 방법", "탐구 과정", "가설을", "변인")


def classify_format(stem: str, item_type: str = "", options_text: str = "") -> str:
    """규칙 기반 형식 분류. LLM 없이 돌아간다.
    계산 여부는 발문과 보기를 함께 보고(숫자와 단위가 보기에만 있는 경우가 많다), 나머지는 발문만 본다."""
    s = stem or ""
    both = s + " " + (options_text or "")
    if any(w in s for w in _DESIGN_WORDS):
        return "탐구 설계"
    if item_type == "서술형" or any(w in s for w in ("서술하시오", "설명하시오", "서술하", "설명하")):
        if any(w in s for w in _DATA_WORDS):
            return "자료 해석"
        return "서술형"
    if _UNIT_WORDS.search(both) or any(w in s for w in _CALC_WORDS):
        return "계산"
    if any(w in s for w in _DATA_WORDS):
        return "자료 해석"
    return "개념 확인"


def distribution(labels: list[str], categories: list[str] | None = None) -> dict[str, float]:
    categories = categories or FORMATS
    c = Counter(labels)
    total = max(1, sum(c.values()))
    return {k: c.get(k, 0) / total for k in categories}


def tv_distance(p: dict[str, float], q: dict[str, float]) -> float:
    """두 분포의 총변동 거리. 0이면 같고 1이면 완전히 다르다."""
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def coverage(assigned: list[str], objective_ids: list[str]) -> dict:
    """학습목표별 문항 수와 덮인 비율."""
    c = Counter(a for a in assigned if a in objective_ids)
    covered = sum(1 for o in objective_ids if c.get(o, 0) > 0)
    n = max(1, len(objective_ids))
    counts = {o: c.get(o, 0) for o in objective_ids}
    total = max(1, sum(counts.values()))
    shares = sorted(v / total for v in counts.values())
    # 지니 계수: 문항이 몇 개 목표에 몰려 있는지 (0 고름, 1 몰림)
    gini = 0.0
    if len(shares) > 1 and total > 0:
        cum = 0.0
        for i, s in enumerate(shares, 1):
            cum += i * s
        gini = (2 * cum) / len(shares) - (len(shares) + 1) / len(shares)
    return {
        "covered_ratio": covered / n,
        "missing": [o for o in objective_ids if c.get(o, 0) == 0],
        "counts": counts,
        "gini": round(gini, 3),
        "unassigned": sum(1 for a in assigned if a not in objective_ids),
    }
