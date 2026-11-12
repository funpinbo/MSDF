# 기여 안내

현재 버전: **0.1.0.** 다음에 할 일은 [docs/roadmap.md](docs/roadmap.md)의 "다음에 할 것"에 있습니다.

## 시작하기

```bash
git clone https://github.com/funpinbo/MSDF
cd MSDF
uv sync --all-extras
uv run pytest
cd frontend && npm install && npm run build   # 웹 UI (빌드 결과는 커밋하지 않음)
```

## 먼저 읽을 것

1. [docs/concepts.md](docs/concepts.md) — 무엇을 하는가
2. [docs/how-it-works.md](docs/how-it-works.md) — 어떻게 동작하는가
3. [docs/roadmap.md](docs/roadmap.md) — 어디까지 왔고 어디로 가는가

문서에 적힌 동작을 바꾸려면 이슈를 먼저 열어 주세요. 하나를 바꾸면 다른 쪽이 따라 바뀌는 결정이 많습니다.

## 코드 지도

| 위치 | 내용 |
| --- | --- |
| `ms_dataflow/decorators.py` | 사용자 API: `service`, `action`, `order`, `context`, `delete` |
| `ms_dataflow/client.py` | `start()`, 엔진으로 가는 HTTP |
| `ms_dataflow/ids.py` | 모든 해시 (Planner와 Resolver가 같이 쓴다) |
| `ms_dataflow/registry/` | `ast` 분석, 소속 판정 |
| `ms_dataflow/config/` | DAG, IAM, resolvers 로딩과 검증 |
| `ms_dataflow/planner.py` | 순수 함수. DB에 쓰지 않는다 |
| `ms_dataflow/execute/engine.py` | 큐, 결과 등록, 재시도, 실패 전파 (단일 스레드) |
| `ms_dataflow/execute/scheduler.py`, `worker.py` | HTTP 서버 양쪽 |
| `ms_dataflow/execute/local.py` | 프로세스 하나로 돌리는 `LocalRunner` (테스트용) |
| `ms_dataflow/ops.py` | 삭제, hot/cold 보관, 계보 조회 |
| `ms_dataflow/ui/` | 웹 UI가 읽는 JSON API와 빌드 결과 서빙 |
| `ms_dataflow/metrics.py`, `dag_store.py` | UI용 집계와 로그 조회, 편집기의 DAG 검증·저장 |
| `frontend/` | 웹 UI 소스 (Vue 3 + Vue Flow). [frontend/README.md](frontend/README.md) |
| `tests/fixtures/calc/` | 도메인 없는 검증용 서비스. 프레임워크 테스트는 이것으로 한다 |

테스트는 `tests/fixtures/calc`의 최소 서비스로 프레임워크 동작만 검증합니다. `examples/`는 사용자에게 보여 주는 예시이며,
`tests/test_examples.py`는 예제가 깨지지 않았는지만 확인합니다.

## 테스트에서 먼저 지켜야 할 것

다음 다섯 가지는 깨지면 조용히 잘못된 데이터가 나갑니다. 관련 코드를 건드리면 테스트를 함께 확인해 주세요.

1. **해시 결정성** — 같은 입력이면 항상 같은 `lineage_key`와 `artifact_id`
2. **Planner와 Resolver의 ID 일치** — `planned_id`와 Resolver 발급 값이 같아야 한다
3. **version 정규화** — 주석·공백만 다르면 같은 version, 로직이 다르면 다른 version
4. **소속 판정** — 두 서비스가 같은 Action에 닿으면 로딩 오류
5. **재시작 안전성** — Worker를 실행 중에 죽여도 단계가 다시 배정된다 (`tests/test_distributed.py`).
   Scheduler 자체를 임의 시점에 죽였다 살리는 테스트는 아직 없습니다.

## 코드 스타일

```bash
uv run ruff check . --fix
uv run ruff format .
uv run mypy ms_dataflow
```

## 설계 원칙 (리뷰 기준)

- 사용자 코드에 `artifact_id`, `lineage_key`, 큐, lease, HTTP, 직렬화 포맷이 새어 나오면 추상화가 깨진 것입니다.
- 런타임에 터지게 두지 말고 로딩 때 막습니다. 에러 메시지에는 파일, 줄, 선언 원문, 이유, 고칠 방법 다섯 가지를 모두 담습니다.
- 레이어 하나는 데이터에 대해 책임 하나만 집니다.
- 판단이 헷갈리면 이 문장으로 돌아옵니다. **서비스 간 데이터 이동의 권한·실패·추적을 쉽게 하는 계층이지, 서비스 전체를 관리하는 시스템이 아니다.**

## 라이선스

기여한 코드는 MIT로 배포됩니다.
