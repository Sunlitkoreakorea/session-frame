"""참가자 번호와 배정표를 만든다 (집단 × 순서, 4명씩 블록 무작위).

  python -m mockgap.make_assignments --n 60 --seed 20261101
출력: data/experiment/assignments.csv  (id, group, order)
  group: warn(경고 집단) / ctrl(통제 집단)
  order: ai_first(세션 1이 AI 단원) / exam_first(세션 1이 기출 단원)
번호는 P001 부터. 이 표는 연구자만 본다.
"""
from __future__ import annotations

import argparse
import csv
import random

from .config import data_path, load_config, setup_stdout


def main(argv=None):
    setup_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int)
    args = ap.parse_args(argv)
    cfg = load_config()
    rng = random.Random(args.seed if args.seed is not None else cfg.get("seed", 0))
    cells = [("warn", "ai_first"), ("warn", "exam_first"), ("ctrl", "ai_first"), ("ctrl", "exam_first")]
    rows = []
    k = 1
    while len(rows) < args.n:
        block = cells[:]
        rng.shuffle(block)
        for g, o in block:
            if len(rows) >= args.n:
                break
            rows.append({"id": f"P{k:03d}", "group": g, "order": o})
            k += 1
    out = data_path(cfg, "experiment", "assignments.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "group", "order"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)}명 배정표 저장: {out}")


if __name__ == "__main__":
    main()
