# 설정 파일

> **현재 상태: 구현 전.** 아래 문법은 목표하는 형태이며 구현 중에 바뀔 수 있습니다.

MSDF의 설정은 YAML 파일 세 종류입니다. 셋은 각자 다른 것만 압니다. 이 경계 덕분에 서비스끼리 서로를 모를 수 있습니다.

| 파일 | 아는 것 | 모르는 것 |
| --- | --- | --- |
| 코드의 데코레이터 | 내 Action의 슬롯, params, version, retries, fresh\_for | 누구와 연결되는지, 어디에 저장되는지 |
| DAG 파일 (`dags/*.yaml`) | 슬롯끼리의 연결, 결과, 배달 지점 | 권한, 저장소 |
| IAM 파일 (`iam.yaml`) | 계층과 허용 규칙 | 어떤 DAG와 데이터가 있는지 |
| `resolvers.yaml` | 슬롯별 저장소 | 흐름, 권한 |

세 파일은 모두 `msdf up`을 실행하는 엔진 쪽에만 둡니다. 서비스 프로세스에는 필요 없습니다.

## DAG 파일

결과물 하나를 만드는 방법을 파일 하나에 적습니다. DAG는 웹 UI에서도 만들고 볼 수 있으며, 결과는 이 형식의 파일로 저장되므로 git으로 관리할 수 있습니다.

```yaml
# dags/search_result.yaml
order: search_result              # 서비스가 order()로 부르는 이름

nodes:                            # 노드 이름: {service, action, 옵션}
  fetch:  {service: search,     action: fetch, fresh_for: 1d}
  embed:  {service: embedding,  action: embed}
  refine: {service: processing, action: refine}

edges:                            # 노드.출력슬롯 → 노드.입력슬롯
  - {from: fetch.out, to: embed.docs}
  - {from: embed.out, to: refine.vectors}

result: refine.summary            # order의 결과가 되는 슬롯

deliveries:                       # 결과를 누구에게 돌려줄지
  - requester: chatbot
    on_success: chatbot.on_search_result
    on_fail:    chatbot.on_search_failed
```

| 키 | 뜻 |
| --- | --- |
| `order` | 계약 이름. 같은 이름이 두 DAG에 있으면 오류 |
| `nodes` | 단계 목록. 노드에 `fresh_for`, `retries` 같은 옵션을 적으면 데코레이터보다 우선 (단, `version`은 불가) |
| `edges` | 출력 슬롯을 입력 슬롯에 연결 |
| `result` | 요청한 서비스에 돌려줄 슬롯 |
| `deliveries` | 요청 서비스별 `on_success`, `on_fail` Action. `on_fail`은 필수 |

엔진은 `result`에서 거꾸로 올라가며 필요한 단계만 계산합니다. `result`에 쓰이지 않는 가지는 실행되지 않습니다.

## IAM 파일

누가 어떤 요청을 할 수 있고, 데이터가 어디서 어디로 흐를 수 있는지 정합니다. 프로젝트에 하나만 둡니다.

```yaml
# iam.yaml
layers:
  account: {kind: ordered, levels: [viewer, analyst, admin]}    # 순서 있는 계층
  service: {kind: flat, members: [chatbot, search, embedding, processing]}

rules:                              # 기본은 거부. 아래에 맞는 것만 허용
  - {type: order, account: ">=analyst", service: chatbot}
  - {type: flow, from: search.fetch,      to: embedding.embed,          account: ">=analyst"}
  - {type: flow, from: embedding.*,       to: processing.*,             account: ">=analyst"}
  - {type: flow, from: processing.refine, to: chatbot.on_search_result, account: any}
  - {type: delete, account: ">=admin", service: chatbot, target: processing.refine.*}
```

### 계층

- 어떤 계층을 둘지는 사용자가 정합니다. `account`, `service`는 예시입니다.
- `ordered`는 등급처럼 순서가 있어 `">=analyst"` 같은 비교를 쓸 수 있습니다. `flat`은 이름 목록입니다.
- 계층 값은 서비스가 [`@context`](writing-services.md#context)로 알려 줍니다. 서비스 이름만은 엔진이 자동으로 채웁니다.

### 규칙 종류

| 종류 | 검사하는 것 |
| --- | --- |
| `order` | 이 계정·서비스가 order를 낼 수 있는가 |
| `flow` | 데이터가 이 Action에서 저 Action으로 흐를 수 있는가. `service.*`로 서비스 단위도 가능. `account`는 필수 (모든 계정이면 `any`) |
| `delete` | 이 계정·서비스가 이 Action이 만든 데이터를 지울 수 있는가 |

### 검사 방식

- order를 받는 순간 **DAG의 모든 연결**과 `on_success` 배달을 검사합니다. 캐시로 건너뛸 단계도 포함합니다.
- 하나라도 막히면 order 전체를 거부하고, 어느 연결이 막혔는지 `PermissionDenied`와 UI로 알려 줍니다.
- `on_fail`은 데이터를 넘기지 않으므로 `flow` 검사 대상이 아닙니다.
- "원본을 볼 수 있으면 파생 데이터도 볼 수 있다" 같은 상속은 하지 않습니다. 그런 정책이 필요하면 규칙마다 같은 계정 조건을 적습니다.

## resolvers.yaml

데이터가 어디에 저장될지를 `서비스.액션.슬롯` 단위로 정합니다. 서비스 코드는 이 파일을 모르므로, DB를 바꿔도 코드는 그대로입니다.

```yaml
search.fetch.out:          {backend: postgres, table: fetched_raw, dsn: "${PG_DSN}"}
processing.refine.summary: {backend: file, path: ./store/summary}
default:                   {backend: file, path: ./store}    # 매핑이 없으면 이것
```

- 내장 백엔드: `file`, `sqlite` (예정: `postgres`).
- 접속 정보는 `${PG_DSN}`처럼 환경 변수로 적습니다. 엔진이 풀어서 해당 서비스에만 내려 줍니다.
- 각 서비스는 자기가 읽고 쓰는 슬롯의 설정만 받습니다.
- 데이터 자체는 서비스와 저장소 사이에서만 오가고 엔진을 거치지 않습니다.

### 직접 만든 백엔드 쓰기

다른 패키지가 백엔드를 제공할 수 있습니다. 패키지의 `pyproject.toml`에 entry point를 등록하면 `backend:` 이름으로 쓸 수 있습니다.

```toml
[project.entry-points."msdf.resolvers"]
duckdb = "msdf_duckdb:DuckDBResolver"
```

```yaml
default: {backend: duckdb, path: ./store.duckdb}
```

백엔드는 `save`, `load`, `locate`, `delete`, `exists`, `close`를 구현합니다. 내장 백엔드도 같은 방식으로 등록되어 있습니다.

## 로딩할 때 검사하는 것

`msdf up`이 파일을 읽을 때 다음을 검사하고, 문제가 있으면 모두 모아서 보여 줍니다.

| 항목 | 결과 |
| --- | --- |
| DAG에 순환이 있다 | 오류 |
| 연결되지 않은 입력 슬롯이 있다 | 오류 |
| 코드에 없는 Action이나 슬롯을 DAG가 참조한다 | 오류 |
| 같은 `order` 이름이 여러 DAG에 있다 | 오류 |
| `result`, `on_success`, `on_fail`이 없는 Action·슬롯을 가리킨다 | 오류 |
| delivery에 `on_fail`이 없다 | 오류 |
| DAG 노드가 `version`을 덮어쓴다 | 오류 |
| IAM `flow` 규칙에 `account`가 없다 | 오류 |
| 두 서비스에서 동시에 닿는 Action이 있다 | 오류 |
| 어디에도 연결되지 않은 출력 슬롯이 있다 | 경고 |

서비스가 `start()`로 등록할 때도 몇 가지를 더 검사합니다. 같은 이름의 서비스가 다른 코드로 등록되면 거부하고, `@context`의 반환 키가 IAM 계층과 맞지 않아도 거부합니다.
