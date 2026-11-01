# ai-quiz-study-frame

AI 챗봇이 만든 예상문제 세트를 점검하는 도구와, 두 단원을 서로 다른 방법으로 공부하는 실험을 운영하는 Streamlit 페이지의 뼈대입니다. 연구 가설, 설계 문서, 수집된 자료, 교과서 본문은 들어 있지 않습니다. 코드와 설정 양식, 예시 문항만 있습니다.

## 들어 있는 것

```
config.yaml                설정 (단원, 모델, 세트 수)
sample_textbook/           단원 구조와 자리 표시용 본문. 실제 교과서 텍스트로 교체해서 쓴다
src/mockgap/
  generate.py              LLM API 로 예상문제 세트 생성 (--no-text 로 본문 없이 생성)
  measure.py               세트 측정: 교과서 문장 겹침, 학습목표 배정, 형식 분포, 교차 모델 불일치
  self_preference.py       정답지를 일부러 틀리게 바꾼 뒤 같은/다른 모델의 채점 통과율 비교
  local_tools.py           API 없이 도는 파서와 지표 (챗 앱 출력 → 문항 목록)
  import_manual.py         챗 앱에서 손으로 받은 세트 가져오기
  make_assignments.py      참가자 번호와 집단 배정표 생성
  export_participants.py   참가자 기록을 CSV 한 장으로
  metrics.py, textbook.py, llm.py, config.py, selftest.py
app/checker.py             세트 검사기 (Streamlit)
app/experiment.py          참가자용 실험 페이지 (Streamlit, API 없이 동작)
data/past_exams/           기출 CSV 양식과 입력 설명
data/experiment/           실험 설정, 예시 연습 세트와 시험 (SAMPLE)
```

## 설치

```powershell
pip install -r requirements.txt
pip install -e .
Copy-Item .env.example .env   # API 키를 쓸 때만
```

## 바로 돌려 보기 (키 없이)

```powershell
$env:MOCKGAP_MOCK="1"; $env:PYTHONIOENCODING="utf-8"
python -m mockgap.selftest
python -m mockgap.generate --sets 2 --n 5
python -m mockgap.measure
Remove-Item Env:MOCKGAP_MOCK
```

`MOCKGAP_MOCK=1` 이면 API 호출 없이 가짜 응답으로 전체 파이프라인이 돕니다. 실제 자료와 섞이지 않게 `MOCKGAP_DATA_DIR` 로 자료 폴더를 바꿀 수 있습니다.

## 실험 페이지

```powershell
python -m mockgap.make_assignments --n 60
streamlit run app/experiment.py
```

참가자는 번호로 들어와 사전 설문 → 세션 1 → 세션 2 → 사후 설문 순서로 진행합니다. 한 세션은 자기가 쓰는 AI 챗봇에 고정 프롬프트를 붙여 받은 예상문제를 붙여 넣는 방식이고, 다른 세션은 연구자가 준비한 연습 세트를 받습니다. 붙여 넣은 답은 `local_tools.parse_ai_output` 이 문항으로 나누고, 원문도 함께 저장됩니다. 진행 상태는 `data/experiment/participants/<번호>.json` 에 남아 새로고침해도 이어집니다. 사이드바에 `data/experiment/config.json` 의 `researcher_code` 를 넣으면 진행 현황과 CSV 내보내기가 보입니다.

`data/experiment/practice_sets/` 와 `data/experiment/tests/` 의 문항은 자리 표시용 예시입니다. 실제 운영 전에 교체하세요. `config.json` 의 설명문과 연구자 코드도 바꿔야 합니다.

## 검사기

```powershell
streamlit run app/checker.py
```

챗 앱에서 받은 예상문제를 붙여 넣으면 교과서 문장 겹침, 형식 분포, 교과서 자체를 가리키는 문항 같은 점검 결과를 보여 줍니다. 학습목표 배정과 교차 모델 검증은 API 키가 있을 때만 켜집니다.

## 교과서 텍스트

`sample_textbook/` 은 구조만 보여 주는 자리 표시입니다. 실제로 쓰려면 같은 형식(`units.json`, `unit_<단원>.txt`, `pages/pNNN.txt`)으로 교과서 텍스트를 추출해 넣고 `config.yaml` 의 `textbook_dir` 를 그 폴더로 바꿉니다. 교과서 본문은 저작권이 있으므로 저장소에 올리지 않습니다.

## 라이선스

MIT
