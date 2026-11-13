# 변경 기록

**한국어** | [English](CHANGELOG.en.md)

## 0.5.0 — 2026-11-13

### 새 기능

- **슬롯 타입 검사**: DAG로 이은 출력과 입력(결과와 `on_success` 입력 포함)의 타입 힌트가 `list` → `dict`처럼 명백히 다르면 `msdf check`, `msdf up`, DAG 편집기가 실행 전에 오류로 알려 줍니다(양쪽 파일과 줄 포함). 코드를 실행하지 않고 힌트 글자만 비교하며, 판단할 수 없는 힌트(사용자 클래스, `Any`, 추상 타입)나 힌트가 없으면 검사하지 않습니다. `int` → `float`처럼 파이썬이 받아 주는 것은 허용합니다.
- **오래 비어 있는 구독 끝내기**: 요청 서비스가 `--subscription-idle`(기본 600초) 동안 연결되지 않으면 그 구독을 끝냅니다(사유 `requester_gone`). 그 전에 돌아오면 이어집니다.

### 고친 것

- 0.3 이전 DB를 0.4로 올릴 때처럼, 아직 없는 표에 열을 더하는 변환 단계가 있으면 시작이 실패할 수 있었습니다. 그런 단계는 건너뛰고 표를 새로 만들 때 열을 함께 만듭니다.

### 바뀐 것

- DB 스키마 v6 (`subscription.idle_since`). 시작할 때 자동 변환, 백업 남김.
- 엔진↔서비스 메시지의 `ActionSpec`에 `arg_types`, `returns`가 추가되었습니다(기본값이 있어 0.4 서비스도 붙습니다).

## 0.4.0 — 2026-11-13

### 새 기능

- **구독 (`subscribe`)**: `order(..., subscribe="30m")`. 그동안 결과가 기대는 source가 `invalidate()`되면 엔진이 바뀐 단계부터 다시 계산해 **같은 배달 Action으로, 처음 request_id와 meta 그대로** 다시 보냅니다(data change 2단계).
  - 몇 번째인지는 배달 Action의 `refresh` 인자(0, 1, 2, …)로 압니다.
  - 다시 계산한 결과가 지난번과 같으면 보내지 않습니다(배달 단계는 `skipped`).
  - 한 구독에 refresh는 한 번에 하나, 최소 간격 `--refresh-min-gap`(기본 1초). refresh 도중 또 바뀌면 한 번 더.
  - refresh마다 IAM 재검사. 권한이 없어지면 구독을 끝내고 `on_fail`에 `"cancelled"`와 이유.
  - 기간 만료, `cancel()`, DAG 변경으로 끝납니다. 살아 있는 구독 수 상한 `--max-subscriptions`(기본 1000).
- **`cancel(request_id)`**: 서비스 코드에서 자기 요청을 멈추거나 구독을 끝냅니다. 공개 함수가 여덟 개가 되었습니다.
- 웹 UI: 로그 › 구독 탭, 실행 상세의 refresh 표시와 "구독 끝내기". API `GET /api/subscriptions`.
- 예시 챗봇: 대화마다 `subscribe="10m"`로 묻고, `search.py`가 `sample_docs.json`이 바뀌면 `invalidate()`합니다. 새 질문을 하면 지난 질문의 구독은 `cancel()`합니다.

### 바뀐 것

- `on_fail`의 `error`는 이제 **엔진이 정한 사유 문장**(다섯 가지)만 받습니다. 다른 서비스의 예외 문구는 넘어오지 않습니다(0.3에서는 마지막 줄이 넘어왔습니다).
- 서비스는 다른 서비스를 알 수 없습니다: 거부된 `order()`의 `PermissionDenied.blocked`에는 자기 order 규칙만, `ServiceUnavailable`에는 서비스 이름이 없습니다. 서비스의 `invalidate()`는 새 version만, `cancel()`은 성공 여부만 돌려줍니다. 상세는 엔진 로그와 웹 UI에서 봅니다. CI guard(`test_isolation.py`)가 확인합니다.
- DB 스키마 v5 (`subscription` 표, `run.subscription_id`, `run.refresh_no`). 시작할 때 자동 변환, 백업 남김.
- 엔진↔서비스 메시지에 `OrderRequest.subscribe`, `StepTask.refresh`, `CancelRequest`가 추가되었습니다(모두 기본값이 있어 0.3 서비스도 붙습니다).

## 0.3.1 — 2026-11-13

### 고친 것

- **Action 버전이 파이썬 버전마다 달랐습니다.** 같은 코드라도 3.11, 3.12, 3.13에서 다른 버전이 나와, 엔진과 서비스를 다른 파이썬으로 띄우면 "다른 코드로 이미 등록"되었다며 거부되거나 파이썬만 올려도 cache가 무효가 될 수 있었습니다. 이제 버전 해시가 파이썬 버전과 무관합니다.
  - 그 대신 **모든 Action의 버전이 한 번 바뀌어, 기존 cache가 한 번 다시 계산됩니다.**
- `msdf up --no-ui`에서 JSON API까지 빠져 `msdf status`, `runs`, `cancel`이 동작하지 않았습니다. 이제 `--no-ui`는 웹 화면만 끕니다.

### 기여자를 위해

- CI를 다섯 job으로 나눴습니다: lint, guards, test(3.11~3.13), e2e, install.
- `tests/guards/`: MSDF 철학, 구조, 호환성(cache key, Action 버전, DB 스키마), 문서(ko/en 짝, 링크, 예시 문법), 저장소 위생을 확인합니다. 실패하면 원칙, 이유, 고칠 방법을 알려 줍니다.
- `tests/e2e/`: "시작하기"를 사용자처럼 끝까지 실행합니다(`msdf init` → `up --token` → 서비스 → `invalidate`).
- Pull request 템플릿과 CONTRIBUTING의 "CI가 확인하는 것".

## 0.3.0 — 2026-11-13

### 새 기능

- **결과가 어느 요청의 것인지 알 수 있습니다** (request correlation).
  - `order()`가 **request_id**를 돌려줍니다. delivery Action이 `request_id` 인자를 선언하면 같은 값을 받습니다.
  - `order(..., meta={...})`: 결과와 함께 돌려받을 작은 값(예: `session_id`). cache key와 IAM에 쓰지 않으므로, 같은 질문은 한 번만 계산하고 사용자마다 따로 배달합니다.
  - `order(..., idempotency_key="...")`: 같은 키로 다시 보내도 run을 새로 만들지 않습니다.
  - `on_fail`이 `error`(실패 원인 마지막 줄)를 받을 수 있습니다.
  - 웹 UI 실행 상세에 meta와 idempotency_key가 보입니다.

- **`invalidate()`: source 데이터가 바뀌었다고 알립니다** (data change 1단계. 2단계 subscribe는 0.4).
  - 데이터를 읽는 서비스가 `invalidate("fetch", params={...}, data_version=...)`를 부르면, 다음 요청부터 그 Action과 하위 단계가 새로 계산됩니다. `data_version`이 cache key에 들어가는 방식이라 하위 단계는 저절로 따라옵니다.
  - 자기 Action만 지정할 수 있습니다. 운영자와 webhook은 `msdf invalidate`, `POST /api/invalidate`.
  - 예전 `data_version`으로 돌아가면 예전 cache를 다시 씁니다. 한 번도 invalidate하지 않은 Action의 cache는 그대로입니다.

### 바뀐 것

- **`order()`의 반환값이 lineage_key에서 request_id로 바뀌었습니다.** `delete()`는 둘 다 받습니다.
- DB 스키마 v4 (시작할 때 자동 변환, 백업 남김).

## 0.2.0 — 2026-11-12

### 새 기능

- **함수 없이 서비스 선언**: `service("search")` 한 줄. Action만 제공하는 서비스에 빈 `def search(): ...`를 둘 필요가 없습니다. `@service` 데코레이터도 그대로 됩니다.
- **버전이 도우미 코드를 따라갑니다**: Action이 부르는 프로젝트 안 함수, 클래스, 모듈 상수(같은 파일이든 import한 파일이든)가 바뀌면 그 Action의 버전이 바뀌어 다시 계산합니다. 도우미가 없는 Action의 버전은 0.1과 같습니다.
- **엔진 토큰**: `msdf up --token`(또는 `MSDF_TOKEN`). 서비스 → 엔진, 엔진 → 서비스, 웹 UI, CLI가 모두 같은 토큰을 보내야 합니다.
- **실행 취소**: 웹 UI의 실행 상세, `msdf cancel RUN_ID`, `POST /api/runs/{id}/cancel`. 요청한 서비스의 `on_fail`에 `"cancelled"`가 배달되고, 다른 요청이 함께 기다리는 단계는 계속 돕니다. run 상태 `cancelled`가 새로 생겼습니다.
- **웹 UI 권한 화면**: IAM 계층과 규칙을 표로 편집, 검증, 저장(엔진에 즉시 반영). 실행하지 않고 통과 여부를 보는 "권한 시험".
- **웹 UI 실시간 갱신**: 2초 폴링 대신 엔진이 `/api/stream`(SSE)으로 변경 신호를 보낼 때만 다시 읽습니다. 끊기면 폴링으로 돌아갑니다.
- **DB 자동 변환**: 옛 스키마의 `.msdf/msdf.db`를 시작할 때 변환하고 백업(`msdf.db.v<n>.bak`)을 남깁니다.
- **코드 분석 캐시**: 바뀌지 않은 파일은 다시 분석하지 않습니다(`.msdf/scan.cache`, `--no-cache`로 끔).
- **CLI**: `msdf init`(새 프로젝트 뼈대), `msdf status`, `msdf runs`, `msdf cancel`.

### 바뀐 것

- 도우미 함수를 쓰는 Action은 버전 계산 방식이 바뀌어, 0.1에서 만든 그 Action의 캐시는 한 번 다시 계산됩니다.
- `class` 안의 메서드에 붙인 `@action`은 이제 로딩 오류입니다(이전에는 최상위 함수로 잘못 취급될 수 있었음).
- 문서와 예시의 빈 `...` 본문을 실제 코드로 바꿨습니다.

## 0.1.0

첫 공개 버전. 엔진(`msdf up`)과 서비스 프로세스, Planner와 캐시, IAM, 삭제와 보관, 웹 UI(실시간 맵, DAG 편집기, 로그).
