# 변경 기록

**한국어** | [English](CHANGELOG.en.md)

## 0.3.0 (작업 중)

### 새 기능

- **결과가 어느 요청의 것인지 알 수 있습니다** (request correlation).
  - `order()`가 **request_id**를 돌려줍니다. delivery Action이 `request_id` 인자를 선언하면 같은 값을 받습니다.
  - `order(..., meta={...})`: 결과와 함께 돌려받을 작은 값(예: `session_id`). cache key와 IAM에 쓰지 않으므로, 같은 질문은 한 번만 계산하고 사용자마다 따로 배달합니다.
  - `order(..., idempotency_key="...")`: 같은 키로 다시 보내도 run을 새로 만들지 않습니다.
  - `on_fail`이 `error`(실패 원인 마지막 줄)를 받을 수 있습니다.
  - 웹 UI 실행 상세에 meta와 idempotency_key가 보입니다.

### 바뀐 것

- **`order()`의 반환값이 lineage_key에서 request_id로 바뀌었습니다.** `delete()`는 둘 다 받습니다.
- DB 스키마 v3 (시작할 때 자동 변환, 백업 남김).

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
