# 로드맵

**한국어** | [English](en/roadmap.md)

## 현재 상태: 0.3.0

한 머신에서 엔진(`msdf up`)과 여러 서비스 프로세스로 동작합니다.

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 1 | ID 계산과 메타데이터 테이블 (SQLite) | 완료 |
| 2 | `@service`, `@action` 데코레이터와 버전 계산 (AST 정규화) | 완료 |
| 3 | 코드 분석(Action 수집, 소속 판정), DAG 로더, 로딩 검증 | 완료 |
| 4 | Planner (필요한 단계만, 캐시 제외, 진행 중 단계 합류) | 완료 |
| 5 | 로컬 Resolver (파일, SQLite)와 `resolvers.yaml` | 완료 |
| 6 | Scheduler와 서비스 수신 서버: lease, 심박, 재시도, 배달 | 완료 |
| 7 | `msdf up`, `msdf check` | 완료 |
| 8 | IAM 규칙 검사 (`order`, `flow`, `delete`), `@context` | 완료 |
| 9 | 삭제 요청과 보관 정책 (hot/cold) | 완료 |
| 10 | 웹 UI (Vue): 실시간 맵, DAG 편집기, 로그 | 완료 |
| 11 | 함수 없는 서비스 선언 `service("이름")` | 완료 (0.2) |
| 12 | 버전이 Action이 부르는 프로젝트 안 도우미 코드까지 반영 | 완료 (0.2) |
| 13 | 엔진·서비스·UI 토큰 인증 (`--token`, `MSDF_TOKEN`) | 완료 (0.2) |
| 14 | UI 실시간 갱신(SSE), IAM 편집 화면, 실행 취소 | 완료 (0.2) |
| 15 | DB 자동 변환, 코드 분석 캐시, `msdf init/status/runs/cancel` | 완료 (0.2) |
| 16 | Request correlation: `request_id`, `meta`, `idempotency_key`, `on_fail`의 `error` | 완료 (0.3) |
| 17 | Data change 1단계: `invalidate()`, `data_version`, `msdf invalidate` | 완료 (0.3) |

## 방향

MSDF가 지키려는 것은 한 문장입니다.

> **서비스 사이 데이터 이동의 권한, 실패, 추적을 쉽게 하는 계층이지, 서비스 전체를 관리하는 시스템이 아니다.**

이 방향에서 나오는 원칙:

- **사용자가 외울 것을 줄인다.** 함수 일곱 개와 YAML 세 개가 전부여야 합니다. 데이터 ID, 큐, HTTP, 직렬화 포맷이 사용자 코드에 나오면 설계를 되돌립니다.
- **틀린 것은 실행 전에 막는다.** 런타임에 터지기보다 로딩할 때 파일, 줄, 원문, 이유, 고칠 방법을 함께 알려 줍니다.
- **각 부분은 책임 하나만 진다.** 데이터는 Resolver, 출처는 Artifact 테이블, 권한은 IAM, 순서는 Planner.
- **로컬에서 먼저 쓸 수 있게 한다.** 지금은 한 머신, SQLite를 전제로 합니다. 여러 머신으로 퍼지는 기능은 그 다음입니다.

## 다음에 할 것

0.4의 중심은 **data change 2단계(subscribe)** 입니다. 설계는 정했습니다: refresh도 원래 request_id로 배달, 결과가 같으면 다시 배달하지 않음.

| 항목 | 내용 |
| --- | --- |
| **subscribe** (0.4) | `order(..., subscribe="30m")`. 결과가 기대는 source가 `invalidate()`되면 같은 params·meta로 다시 계산해 다시 배달. debounce, IAM 재검사, 만료 |
| 구독 화면 (0.4) | UI에 구독 목록, refresh 표시, invalidate 이력 |
| 슬롯 타입 검사 | DAG로 잇는 출력·입력 슬롯의 타입 힌트가 맞는지 로딩할 때 검사 |
| 서비스 코드에서 취소 | `cancel(request_id)`. 사용자가 질문을 바꾸면 이전 요청을 끊기 |
| 영어 메시지와 UI | 지금은 CLI 출력, 오류 메시지, 웹 UI가 한국어다 |
| 같은 서비스에서 이어지는 단계의 메모리 재사용 | 방금 저장한 출력을 다시 읽지 않기. 실시간 응답 지연을 줄인다. 측정 후 결정 |
| 큰 데이터·스트리밍 | Action 안에서 저장소를 직접 읽고 쓰는 `ctx.load()`, `ctx.save()` |
| 실행 중 단계 강제 중단, 사용자 Action 격리 | 서브프로세스 실행 옵션 |
| 추적 내보내기 | 계보와 단계 시간을 OpenTelemetry로 |
| PyPI 배포, 내장 PostgreSQL · S3 Resolver | 로컬에서 먼저, 그다음 |
| 여러 사용자·역할 | 지금 토큰은 하나(엔진 전체 공용)다 |

하지 않을 것: 주기 실행(cron), 서비스 배포·스케일링, LLM 전용 기능, DAG 안에 코드 넣기.

## 알려진 한계

- 버전 해시는 Action 본문과 그 Action이 부르는 프로젝트 안 코드까지 봅니다. 설치한 패키지의 변화나 `getattr` 등으로 동적으로 고른 함수는
  따라가지 못하므로 그럴 때는 `version=`으로 올려야 합니다.
- 동적 import(`importlib.import_module`)로 불러오는 모듈의 Action은 수집하지 못합니다(경고를 냅니다).
- 사용자 Action이 서비스 프로세스를 죽이면, 그 단계는 lease 만료 후 다른 인스턴스에서 다시 실행됩니다.
- Windows에서 파이썬 3.12 이하를 쓰고 프로젝트 경로에 한글이 있으면, 편집 가능 설치 후 시작할 때 오류가 납니다.
  [설치 › 문제가 생기면](installation.md#문제가-생기면)을 보세요.

## 기여하려면

[CONTRIBUTING.md](../CONTRIBUTING.md)를 보세요.
