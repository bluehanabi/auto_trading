# 언제어디로 (When&Where) – 시기 기반 해외여행 추천 AI Agent

> AI Bootcamp 최종 과제 — "날짜는 정해졌는데, 어디로 가지?"에 답하는 Multi-Agent 여행 큐레이터

여행 시기(월/기간)·예산·취향을 입력하면, 해당 시기의 **기후(우기/건기)·성수기 물가·축제·비행시간**을
종합해 최적의 해외 목적지를 근거와 함께 추천하고, 일자별 일정까지 설계해 주는 AI Agent 서비스입니다.

## 핵심 특징

- **역방향 추천**: 기존 OTA(목적지 → 상품 검색)와 반대로 **"날짜 → 목적지"** 를 추천
- **Multi-Agent (LangGraph Supervisor 패턴)**: Profiler / Destination / Planner / Live-Info / Writer Agent 협업
- **RAG**: 자체 구축 목적지 지식베이스(월별 기후·물가·축제·비자) + ChromaDB
- **Tool Calling**: 환율·날씨·웹검색 실시간 API 결합으로 환각 억제
- **Structured Output**: Pydantic 스키마 기반 추천 카드 (점수·이유·예상경비·주의사항)

## 문서

- 기획·설계 문서: [docs/PLANNING.md](docs/PLANNING.md)

## 기술 스택 (예정)

| 구분 | 기술 |
|---|---|
| Agent | LangChain / LangGraph (Supervisor Multi-Agent, ReAct, Memory) |
| RAG | text-embedding-3-small + ChromaDB |
| Backend | FastAPI |
| Frontend | Streamlit |
| 배포 | Docker / docker-compose (선택) |

## 프로젝트 구조 (예정)

```
├── app/
│   ├── agents/          # Supervisor, Profiler, Destination, Planner, Live-Info, Writer
│   ├── rag/             # 문서 로딩·청킹·임베딩·Retriever
│   ├── tools/           # 환율·날씨·웹검색 도구
│   ├── schemas/         # Pydantic Structured Output 스키마
│   └── api.py           # FastAPI 엔드포인트
├── data/destinations/   # 목적지 지식베이스 (MD/CSV)
├── ui/streamlit_app.py  # 채팅 UI
├── docs/PLANNING.md     # 기획·설계 문서
└── docker-compose.yml
```
