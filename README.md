# session-frame

Streamlit 기반 진행 페이지와 텍스트 세트 분석 스크립트의 뼈대입니다. 설정값, 설명문, 예시 자료는 모두 자리 표시자이며, 실제 용도와 내용은 이 저장소에 적지 않습니다.

## 설치

```powershell
pip install -r requirements.txt
pip install -e .
Copy-Item .env.example .env
```

## 실행

```powershell
$env:MOCKGAP_MOCK="1"          # API 없이 가짜 응답으로 동작 확인
python -m mockgap.selftest
python -m mockgap.generate --sets 2 --n 5
python -m mockgap.measure
Remove-Item Env:MOCKGAP_MOCK

python -m mockgap.make_assignments --n 60
streamlit run app/experiment.py
streamlit run app/checker.py
```

## 구조

```
config.yaml              전체 설정
sample_textbook/         입력 텍스트 구조 예시 (자리 표시)
src/mockgap/             생성, 측정, 파서, 가져오기, 배정, 내보내기 스크립트
app/experiment.py        참가자 진행 페이지
app/checker.py           세트 검사 페이지
data/                    양식과 예시 자료 (SAMPLE)
```

`.gitignore` 에 적힌 폴더(수집 자료, 생성 결과, 캐시, 키)는 저장소에 올리지 않습니다.

## 라이선스

MIT
