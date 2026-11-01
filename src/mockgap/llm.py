"""세 모델 제공자(anthropic, openai, google)를 같은 모양으로 부르는 얇은 래퍼.

- complete_json(): 프롬프트를 보내고 JSON 객체를 돌려받는다.
- 같은 요청은 data/cache 에 저장해 두 번 돈을 쓰지 않는다.
- MOCKGAP_MOCK=1 이면 API 없이 가짜 응답을 만들어 파이프라인 전체를 시험할 수 있다.
- 모든 호출은 data/logs/llm_calls.jsonl 에 기록된다 (비용 추정용).
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
from pathlib import Path

SCHEMA_NOTE = "반드시 JSON 객체 하나만 출력한다. 앞뒤 설명, 코드 블록 표시(```)는 넣지 않는다."

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_text(text: str) -> dict:
    """모델이 코드 블록이나 군더더기를 붙여도 JSON 객체를 찾아낸다."""
    t = _FENCE.sub("", (text or "").strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start : end + 1])
        raise


class LLM:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.mock = bool(cfg.get("mock", False))
        self.cache_dir = Path(cfg["data_dir"]) / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = Path(cfg["data_dir"]) / "logs" / "llm_calls.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.rng = random.Random(cfg.get("seed", 0))
        self._clients: dict[str, object] = {}
        self._mock_backend = MockBackend(self.rng)

    # ---------- 공개 메서드 ----------

    def provider_model(self, provider: str) -> str:
        return self.cfg["providers"][provider]["model"]

    def complete_json(
        self,
        provider: str,
        prompt: str,
        schema: dict,
        task: str,
        system: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        max_tokens: int = 16000,
        mock_ctx: dict | None = None,
        use_cache: bool = True,
    ) -> dict:
        model = model or self.provider_model(provider)
        key = hashlib.sha256(
            "\x1f".join([provider, model, system or "", prompt, json.dumps(schema, sort_keys=True, ensure_ascii=False)]).encode("utf-8")
        ).hexdigest()
        cache_file = self.cache_dir / f"{key}.json"

        if self.mock:
            data = self._mock_backend.run(task, mock_ctx or {}, schema)
            self._log(provider, model, task, {}, 0.0, cached=False, mock=True)
            return data

        if use_cache and cache_file.exists():
            with open(cache_file, encoding="utf-8") as f:
                data = json.load(f)
            self._log(provider, model, task, {}, 0.0, cached=True)
            return data

        last_err: Exception | None = None
        for attempt in range(3):
            t0 = time.time()
            try:
                if provider == "anthropic":
                    data, usage = self._anthropic(model, system, prompt, schema, effort, max_tokens)
                elif provider == "openai":
                    data, usage = self._openai(model, system, prompt, schema)
                elif provider == "google":
                    data, usage = self._google(model, system, prompt, schema)
                else:
                    raise ValueError(f"모르는 provider: {provider}")
                self._log(provider, model, task, usage, time.time() - t0, cached=False)
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=1)
                return data
            except Exception as e:  # 재시도 후 위로 올린다
                last_err = e
                time.sleep(2**attempt + self.rng.random())
        raise RuntimeError(f"{provider}/{model} 호출 실패 ({task}): {last_err}")

    # ---------- 제공자별 구현 ----------

    def _anthropic(self, model, system, prompt, schema, effort, max_tokens):
        import anthropic

        client = self._clients.setdefault("anthropic", anthropic.Anthropic())
        pcfg = self.cfg["providers"].get("anthropic", {})
        effort = effort or pcfg.get("effort", "medium")
        kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
        if system:
            kwargs["system"] = system
        # 서버 쪽 대체 모델: 안전 분류기가 거절하면 같은 요청을 다른 모델이 이어서 처리한다.
        use_fallback = bool(pcfg.get("fallbacks", False)) and model.startswith(
            ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable")
        )
        try:
            if use_fallback:
                with client.beta.messages.stream(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                ) as stream:
                    msg = stream.get_final_message()
            else:
                with client.messages.stream(**kwargs) as stream:
                    msg = stream.get_final_message()
        except anthropic.BadRequestError as e:
            text = str(e).lower()
            if use_fallback and ("fallback" in text or "beta" in text):
                with client.messages.stream(**kwargs) as stream:
                    msg = stream.get_final_message()
            else:
                raise
        if msg.stop_reason == "refusal":
            detail = getattr(msg, "stop_details", None)
            raise RuntimeError(f"모델이 요청을 거절함: {detail}")
        text = next(b.text for b in msg.content if b.type == "text")
        usage = {"input": msg.usage.input_tokens, "output": msg.usage.output_tokens}
        return parse_json_text(text), usage

    def _openai(self, model, system, prompt, schema):
        from openai import OpenAI

        client = self._clients.setdefault("openai", OpenAI())
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append(
            {
                "role": "user",
                "content": prompt + "\n\n" + SCHEMA_NOTE + "\nJSON 스키마:\n" + json.dumps(schema, ensure_ascii=False),
            }
        )
        resp = client.chat.completions.create(model=model, messages=messages, response_format={"type": "json_object"})
        text = resp.choices[0].message.content
        usage = {}
        if getattr(resp, "usage", None):
            usage = {"input": resp.usage.prompt_tokens, "output": resp.usage.completion_tokens}
        return parse_json_text(text), usage

    def _google(self, model, system, prompt, schema):
        from google import genai
        from google.genai import types

        client = self._clients.setdefault("google", genai.Client())
        config = types.GenerateContentConfig(response_mime_type="application/json", system_instruction=system or None)
        resp = client.models.generate_content(
            model=model,
            contents=prompt + "\n\n" + SCHEMA_NOTE + "\nJSON 스키마:\n" + json.dumps(schema, ensure_ascii=False),
            config=config,
        )
        usage = {}
        um = getattr(resp, "usage_metadata", None)
        if um is not None:
            usage = {"input": getattr(um, "prompt_token_count", None), "output": getattr(um, "candidates_token_count", None)}
        return parse_json_text(resp.text), usage

    # ---------- 기록 ----------

    def _log(self, provider, model, task, usage, elapsed, cached=False, mock=False):
        rec = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "provider": provider,
            "model": model,
            "task": task,
            "usage": usage,
            "elapsed_s": round(elapsed, 2),
            "cached": cached,
            "mock": mock,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


class MockBackend:
    """API 없이 그럴듯한 응답을 만든다. 파이프라인 점검용이지 연구 자료가 아니다."""

    DIFF = ["하", "중", "상"]
    BLOOM = ["기억", "이해", "적용", "분석"]

    def __init__(self, rng: random.Random):
        self.rng = rng

    def run(self, task: str, ctx: dict, schema: dict) -> dict:
        fn = getattr(self, f"_{task}", None)
        if fn is None:
            raise ValueError(f"모의 모드가 모르는 task: {task}")
        return fn(ctx)

    def _objectives(self, ctx):
        out, k = [], 1
        for sec, sents in ctx.get("sentences_by_section", {}).items():
            for s in sents[:2]:
                out.append({"id": f"O{k}", "section": sec, "text": f"{s[:40]}을(를) 설명할 수 있다."})
                k += 1
        return {"objectives": out}

    def _generate(self, ctx):
        sents = [s for s in ctx.get("sentences", []) if len(s) >= 15] or ["내용이 없다."]
        n = ctx.get("n", 20)
        n_mc = ctx.get("mix", {}).get("객관식", 16)
        items = []
        for i in range(1, n + 1):
            base = self.rng.choice(sents)
            if i <= n_mc:
                opts = [base[:40]] + [self.rng.choice(sents)[:40] for _ in range(4)]
                items.append(
                    {
                        "id": i,
                        "type": "객관식",
                        "stem": f"다음 중 {base[:30]}에 대한 설명으로 옳은 것은?",
                        "options": opts,
                        "answer": "1",
                        "explanation": base,
                        "difficulty": self.rng.choice(self.DIFF),
                        "bloom": self.rng.choice(self.BLOOM),
                    }
                )
            else:
                items.append(
                    {
                        "id": i,
                        "type": "서술형",
                        "stem": f"{base[:25]}에 대해 서술하시오.",
                        "options": [],
                        "answer": base,
                        "explanation": base,
                        "difficulty": self.rng.choice(self.DIFF),
                        "bloom": self.rng.choice(self.BLOOM),
                    }
                )
        return {"items": items}

    def _tag(self, ctx):
        objs = ctx.get("objective_ids", ["O1"])
        return {
            "assignments": [
                {"id": i, "objective_id": "none" if self.rng.random() < 0.1 else self.rng.choice(objs)}
                for i in ctx.get("item_ids", [])
            ]
        }

    def _solve(self, ctx):
        out = []
        for i, key in zip(ctx.get("item_ids", []), ctx.get("keys", [])):
            if self.rng.random() < 0.75:
                out.append({"id": i, "answer": str(key)})
            else:
                others = [str(o) for o in range(1, 6) if str(o) != str(key)]
                out.append({"id": i, "answer": self.rng.choice(others)})
        return {"answers": out}

    def _grade(self, ctx):
        corrupted = ctx.get("corrupted", False)
        p_accept = 0.4 if corrupted else 0.9
        verdict = "맞음" if self.rng.random() < p_accept else "틀림"
        return {"verdict": verdict, "correct_answer": str(ctx.get("true_key", "1")), "reason": "모의 응답"}

    def _parse_items(self, ctx):
        lines = [l.strip() for l in ctx.get("text", "").splitlines() if l.strip()]
        items, cur = [], None
        for l in lines:
            m = re.match(r"^(\d+)[\.\)]\s*(.+)", l)
            if m:
                if cur:
                    items.append(cur)
                cur = {"id": int(m.group(1)), "type": "객관식", "stem": m.group(2), "options": [], "answer": "", "explanation": ""}
            elif cur and re.match(r"^[①②③④⑤]|^\(?[1-5]\)", l):
                cur["options"].append(re.sub(r"^[①②③④⑤]\s*|^\(?[1-5]\)\s*", "", l))
            elif cur:
                cur["stem"] += " " + l
        if cur:
            items.append(cur)
        for it in items:
            if not it["options"]:
                it["type"] = "서술형"
        return {"items": items}
