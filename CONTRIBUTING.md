# 기여 안내

**한국어** | [English](CONTRIBUTING.en.md)

현재 버전: **0.4.0.** 다음에 할 일은 [docs/roadmap.md](docs/roadmap.md)의 "다음에 할 것"에 있습니다.

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

문서는 한국어(`docs/`)와 영어(`docs/en/`) 두 벌입니다. 한쪽을 고치면 다른 쪽도 함께 고쳐 주세요.

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

## CI가 확인하는 것

Pull request를 올리면 GitHub Actions가 다섯 가지를 확인합니다. 실패한 job 이름이 무엇이 문제인지 알려 줍니다.

| job | 확인하는 것 | 실패하면 |
| --- | --- | --- |
| 1. lint | `ruff check`, `ruff format --check`, `mypy` (strict) | 아래 "코드 스타일" 명령을 실행 |
| 2. guards | MSDF 철학, 구조, 호환성, 문서 (`tests/guards/`) | 실패 메시지의 `[원칙] [이유] [고칠 방법]`을 따른다 |
| 3. test | 모든 기능. 파이썬 3.11, 3.12, 3.13 | 해당 테스트를 로컬에서 `uv run pytest -k 이름` |
| 4. e2e | "시작하기"를 사용자처럼 끝까지: `msdf init` → `check` → `up --token` → 서비스 → `invalidate` | `uv run pytest tests/e2e -v` |
| 5. install | 묶음 없는 설치(`msdf check`가 되는지), UI를 넣은 휠 | 핵심 모듈에 서버 라이브러리를 import했는지 확인 |

guard가 확인하는 원칙:

| 분류 | 원칙 |
| --- | --- |
| 철학 | 공개 함수는 여덟 개(`service`, `action`, `order`, `start`, `context`, `delete`, `invalidate`, `cancel`). 서비스 코드는 엔진 내부를 import하지 않고, 서비스끼리 import하지 않는다. 엔진이 서비스에 돌려주는 응답과 배달에는 다른 서비스의 이름·예외 문구·DAG 경로가 없다. 스케줄러·배포 도구·LLM 프레임워크 의존성을 넣지 않는다. `meta`는 cache key에 들어가지 않는다 |
| 구조 | 핵심 모듈(데코레이터, 레지스트리, 설정, Planner)은 서버 없이 동작한다. Planner는 순수 함수다. 메타데이터 DB에 쓰는 곳은 엔진뿐이다. 해시는 `ids.py`에서만. 라이브러리 코드는 `print`하지 않는다. 엔진↔서비스 메시지의 새 필드는 기본값을 가진다 |
| 호환성 | cache key와 Action 버전은 같은 입력이면 MSDF 버전·파이썬 버전과 무관하게 같다. `schema.sql`을 바꾸면 `SCHEMA_VERSION`과 변환(migration)을 함께 추가한다. 버전 번호는 세 곳이 같고, CHANGELOG(ko/en)에 그 버전 항목이 있다 |
| 문서 | 한국어와 영어 문서가 짝으로 있고 제목·코드 블록·표 수가 같다. 공개 함수와 `msdf` 명령이 모두 문서에 있다. 상대 링크가 깨지지 않았다. 파이썬 예시는 문법이 맞다 |
| 저장소 | 빌드 결과(`ui/dist`), 로컬 상태(`.msdf`), `design/`, 비밀 값, `breakpoint()`가 커밋되지 않았다 |

guard는 일부러 바꿀 수 있습니다. 원칙 자체를 바꾸는 기여라면 이슈에서 먼저 합의하고, 같은 PR에서 guard와 문서(ko/en), CHANGELOG를 함께 고쳐 주세요.

```bash
uv run pytest tests/guards -v     # guard만
uv run pytest                     # 전부 (e2e 포함, 약 30초)
```

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
