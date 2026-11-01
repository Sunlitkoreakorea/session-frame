"""참가자 기록(data/experiment/participants/*.json)을 분석용 CSV 한 장으로 모은다.

  python -m mockgap.export_participants
출력: data/experiment/export.csv  (참가자 한 줄)
- err_A, err_B: 그 세션의 (예상 점수 − 객관식 점수). 서술형은 교사 채점 뒤 따로 더한다.
- err_ai, err_exam: 출처별로 다시 이름 붙인 것.
- delta: err_ai − err_exam
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .config import load_config, setup_stdout


def flatten(rec: dict) -> dict:
    row = {"id": rec["id"], "group": rec["group"], "order": rec["order"], "stage": rec["stage"], "created": rec.get("created", "")}
    pre = rec.get("pre_survey", {})
    row.update({"main_app": pre.get("main_app", ""), "apps": "|".join(pre.get("apps", [])), "freq": pre.get("freq", ""),
                "pre_trust": pre.get("trust", ""), "pre_verify": pre.get("verify", ""), "pre_confidence": pre.get("confidence", "")})
    errs = {}
    for key in ("A", "B"):
        s = rec.get("sessions", {}).get(key) or {}
        m = s.get("metrics", {})
        j = s.get("judge", {})
        t = s.get("test", {})
        w = s.get("warning", {})
        p = s.get("practice", {})
        pred = j.get("predicted")
        pct = t.get("mc_pct")
        err = (pred - pct) if (pred is not None and pct is not None) else ""
        row.update({
            f"unit_{key}": s.get("unit", ""), f"source_{key}": s.get("source", ""),
            f"ai_app_{key}": s.get("ai_app", "") or s.get("ai_app_other", ""), f"ai_model_{key}": s.get("ai_model", ""),
            f"n_parsed_{key}": s.get("n_parsed", ""), f"parse_ok_{key}": s.get("parse_ok", ""),
            f"overlap4_{key}": m.get("mean_overlap4", ""), f"coverage_{key}": m.get("coverage_ratio", ""),
            f"format_tv_{key}": m.get("format_tv_vs_past", ""), f"textbook_mentions_{key}": len(m.get("textbook_mentions", []) or []),
            f"warning_dwell_s_{key}": w.get("dwell_s", ""), f"confirm_count_{key}": p.get("confirm_count", ""), f"practice_min_{key}": p.get("elapsed_min", ""),
            f"predicted_{key}": pred if pred is not None else "", f"readiness_{key}": j.get("readiness", ""), f"similar_{key}": j.get("similar", ""), f"key_trust_{key}": j.get("key_trust", ""),
            f"mc_correct_{key}": t.get("mc_correct", ""), f"mc_total_{key}": t.get("mc_total", ""), f"mc_pct_{key}": pct if pct is not None else "",
            f"err_{key}": err,
        })
        if s.get("source") in ("ai", "exam"):
            errs[s["source"]] = err
    row["err_ai"] = errs.get("ai", "")
    row["err_exam"] = errs.get("exam", "")
    row["delta"] = (errs["ai"] - errs["exam"]) if isinstance(errs.get("ai"), (int, float)) and isinstance(errs.get("exam"), (int, float)) else ""
    post = rec.get("post_survey", {})
    row.update({"saw_errors": post.get("saw_errors", ""), "used_ai_in_practice": post.get("used_ai_in_practice", "")})
    return row


def export(cfg: dict) -> Path:
    d = Path(cfg["data_dir"]) / "experiment" / "participants"
    rows = []
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        with open(p, encoding="utf-8") as f:
            rows.append(flatten(json.load(f)))
    out = Path(cfg["data_dir"]) / "experiment" / "export.csv"
    fields = list(rows[0].keys()) if rows else ["id"]
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return out


def main(argv=None):
    setup_stdout()
    cfg = load_config()
    out = export(cfg)
    print("저장:", out)


if __name__ == "__main__":
    main()
