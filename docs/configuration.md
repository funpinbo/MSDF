# 설정 파일

MSDF의 설정은 YAML 파일 세 종류입니다. 셋은 각자 다른 것만 압니다. 이 경계 덕분에 서비스끼리 서로를 모를 수 있습니다.

| 파일 | 아는 것 | 모르는 것 |
| --- | --- | --- |
| 코드의 데코레이터 | 내 Action의 슬롯, params, version, retries, fresh\_for | 누구와 연결되는지, 어디에 저장되는지 |
| DAG 파일 (`dags/*.yaml`) | 슬롯끼리의 연결, 결과, 배달 지점 | 권한, 저장소 |
| IAM 파일 (`iam.yaml`) | 계층과 허용 규칙 | 어떤 DAG와 데이터가 있는지 |
| `resolvers.yaml` | 슬롯별 저장소 | 흐름, 권한 |

세 파일은 모두 `msdf up`을 실행하는 엔진 쪽에만 둡니다. 서비스 프로세스에는 필요 없습니다.

## DAG 파일

결과물 하나를 만드는 방법을 파일 하나에 적습니다. `dags/` 폴더의 `*.yaml`을 모두 읽습니다.

```yaml
# dags/daily_stats.yaml
order: daily_stats                # 서비스가 order()로 부르는 이름

nodes:                            # 노드 이름: {service, action, 옵션}
  load:      {service: source,    action: load, fresh_for: 1h}
  clean:     {service: transform, action: clean}
  summarize: {service: transform, action: summarize}

edges:                            # 노드.출력슬롯 → 노드.입력슬롯
  - {from: load.rows,   to: clean.rows}
  - {from: clean.clean, to: summarize.rows}

result: summarize.stats           # order의 결과가 되는 슬롯

deliveries:                       # 결과를 누구에게 돌려줄지
  - requester: app
    on_success: app.on_stats
    on_fail:    app.on_stats_failed
```

| 키 | 뜻 |
| --- | --- |
| `order` | 계약 이름. 같은 이름이 두 DAG에 있으면 오류 |
| `nodes` | 단계 목록. `fresh_for`, `retries`, `retry_delay`를 적으면 데코레이터보다 우선 (`version`은 불가) |
| `edges` | 출력 슬롯을 입력 슬롯에 연결. 입력 슬롯 하나에는 엣지 하나 |
| `result` | 요청한 서비스에 돌려줄 슬롯 |
| `deliveries` | 요청 서비스별 `on_success`, `on_fail` Action. 둘 다 필수이고, 요청 서비스 자신의 Action이어야 함 |
| `layout` | (선택) 웹 UI 편집기의 노드 위치 `{노드: [x, y]}`. 실행에는 영향이 없음 |

DAG 파일은 손으로 써도 되고, 웹 UI의 [DAG 편집기](how-it-works.md#웹-ui)로 만들어도 됩니다. 편집기에서 저장하면 같은 형식의 파일을 쓰고 엔진에 바로 반영합니다(진행 중인 실행은 이미 세운 계획대로 끝납니다).

- `on_success` Action은 입력 슬롯이 정확히 하나여야 합니다(결과가 그 슬롯으로 들어옵니다).
- `on_fail` Action은 실패 사유(`"failed"` / `"cancelled"`)를 받을 인자 하나가 있어야 합니다.
- 엔진은 `result`에서 거꾸로 올라가며 필요한 단계만 계산합니다. `result`에 닿지 않는 가지는 실행되지 않습니다.

## IAM 파일

누가 어떤 요청을 할 수 있고, 데이터가 어디서 어디로 흐를 수 있는지 정합니다. 프로젝트에 하나만 둡니다.
**파일이 없으면 권한 검사를 하지 않습니다**(모든 요청 허용, `msdf up`이 경고). 파일이 있으면 기본이 거부입니다.

```yaml
# iam.yaml
layers:
  account: {kind: ordered, levels: [viewer, analyst, admin]}    # 순서 있는 계층
  service: {kind: flat, members: [app, source, transform]}

rules:
  - {type: order, account: ">=analyst", service: app}
  - {type: flow, from: source.load,         to: transform.clean,     account: ">=analyst"}
  - {type: flow, from: transform.*,         to: transform.*,         account: ">=analyst"}
  - {type: flow, from: transform.summarize, to: app.on_stats,        account: any}
  - {type: delete, account: ">=admin", service: app, target: "transform.summarize.*"}
```

### 계층

- 어떤 계층을 둘지는 사용자가 정합니다. `account`는 예시입니다(`tenant`, `region` 등 무엇이든).
- `ordered`는 등급처럼 순서가 있어 `">=analyst"`, `"<admin"`, `"==viewer"` 같은 비교를 씁니다. `flat`은 이름 목록이며 `*` 패턴을 씁니다.
- 계층 값은 서비스가 [`@context`](writing-services.md#context)로 알려 줍니다.
- `service` 계층은 따로 정의하지 않아도 있고, 값은 엔진이 자동으로 채웁니다(요청한 서비스).

### 규칙 종류

| 종류 | 검사하는 것 | 필요한 키 |
| --- | --- | --- |
| `order` | 이 계정·서비스가 order를 낼 수 있는가 | 계층 조건 |
| `flow` | 데이터가 이 Action에서 저 Action으로 흐를 수 있는가 | `from`, `to` (`서비스.액션`, `*` 가능), **`service`를 뺀 모든 계층의 조건** (모든 값 허용은 `any`) |
| `delete` | 이 계정·서비스가 이 데이터를 지울 수 있는가 | `target` (`서비스.액션.슬롯` 패턴), 계층 조건 |

조건 값으로 `any`(또는 `*`)를 쓰면 값이 없어도 통과합니다. 조건에 목록을 주면 하나라도 맞으면 통과합니다.

### 검사 방식

- order를 받는 순간 **DAG의 result까지의 모든 연결**과 `on_success` 배달 연결을 검사합니다. 캐시로 건너뛸 단계도 포함합니다.
- 하나라도 막히면 order 전체를 거부하고, 막힌 것을 `PermissionDenied.blocked`와 UI로 알려 줍니다.
- `on_fail`은 데이터를 넘기지 않으므로 검사 대상이 아닙니다.
- "원본을 볼 수 있으면 파생 데이터도 볼 수 있다" 같은 상속은 하지 않습니다. 그런 정책이 필요하면 규칙마다 같은 계정 조건을 적습니다.

## resolvers.yaml

데이터가 어디에 저장될지를 `서비스.액션.슬롯` 단위로 정합니다. 서비스 코드는 이 파일을 모르므로, 저장소를 바꿔도 코드는 그대로입니다.
**파일이 없으면** 모든 데이터를 `<프로젝트>/.msdf/store`에 파일로 저장합니다.

```yaml
source.load.rows:        {backend: sqlite, path: ./data/raw.db, table: raw_rows}
transform.summarize.stats: {backend: file, path: ./data/stats}
default:                 {backend: file, path: ./data/store}    # 매핑이 없으면 이것
```

| 백엔드 | 옵션 |
| --- | --- |
| `file` | `path`, `allow_pickle` |
| `sqlite` | `path`, `table`, `allow_pickle` |

- `path`는 설정 파일이 있는 폴더 기준입니다.
- 값에 `${ENV_NAME}`을 쓰면 엔진이 환경 변수로 바꿔 줍니다. 비밀번호를 파일에 적지 않아도 됩니다. 설정되지 않은 변수는 로딩 오류입니다.
- 엔진은 각 단계를 보낼 때 그 단계가 읽고 쓰는 슬롯의 설정만 함께 보냅니다. 다른 서비스의 저장소 설정은 받지 않습니다.
- 데이터 자체는 서비스와 저장소 사이에서만 오가고 엔진을 거치지 않습니다.

### 직접 만든 백엔드 쓰기

다른 패키지가 백엔드를 제공할 수 있습니다. 패키지의 `pyproject.toml`에 entry point를 등록하면 `backend:` 이름으로 쓸 수 있습니다.

```toml
[project.entry-points."msdf.resolvers"]
duckdb = "msdf_duckdb:DuckDBResolver"
```

백엔드 클래스는 설정 키를 키워드 인자로 받고, `save`, `load`, `locate`, `delete`, `exists`, `close`를 구현합니다
(`ms_dataflow.resolvers.base.Resolver` 참고). `save`는 같은 `(lineage_key, generation)`이 이미 있으면 다시 쓰지 않고 같은 ID를 돌려줘야 하며,
ID는 `ms_dataflow.ids.artifact_id`로 만들어야 엔진이 미리 계산한 ID와 맞습니다. 내장 백엔드도 같은 방식으로 등록되어 있습니다.

## 로딩할 때 검사하는 것

`msdf check`와 `msdf up`이 파일을 읽을 때 다음을 검사하고, 문제가 있으면 모두 모아서 보여 줍니다.

| 항목 | 결과 |
| --- | --- |
| DAG에 순환이 있다 | 오류 |
| 연결되지 않은 입력 슬롯이 있다 | 오류 |
| 코드에 없는 Action이나 슬롯을 DAG가 참조한다 | 오류 |
| 같은 `order` 이름이 여러 DAG에 있다 | 오류 |
| `result`, `on_success`, `on_fail`이 없는 Action·슬롯을 가리킨다 | 오류 |
| delivery에 `on_fail`이 없다 | 오류 |
| DAG 노드가 `version`을 덮어쓴다 | 오류 |
| 첫 단계가 아닌 Action이 `params`를 선언했다 | 오류 |
| IAM `flow` 규칙에 계층 조건이 빠졌다, 없는 계층·레벨을 쓴다 | 오류 |
| 두 서비스에서 동시에 닿는 Action이 있다 | 오류 |
| DAG가 참조하는 서비스가 이 프로젝트에 없다 | 오류 (`--allow-external`이면 경고, 등록할 때 검사) |
| 어디에도 연결되지 않은 출력 슬롯이 있다 | 경고 |
| 어느 서비스에도 속하지 않는 Action이 있다 | 경고 |

서비스가 `start()`로 등록할 때도 검사합니다. 같은 이름의 서비스가 다른 코드로 등록되면 거부하고, `@context`의 반환 키가 IAM 규칙이 쓰는 계층과 맞지 않아도 거부합니다.

## `msdf` 명령

```bash
msdf check [--root .] [--config DIR] [--allow-external]
msdf up    [--root .] [--config DIR] [--allow-external]
           [--host 127.0.0.1] [--port 8787] [--db PATH]
           [--lease-ttl 60] [--keep-generations 3] [--keep-versions 3] [--no-ui] [--ui-dist DIR]
```

| 옵션 | 기본 | 뜻 |
| --- | --- | --- |
| `--root` | `.` | 서비스 코드를 찾을 폴더 |
| `--config` | `--root` | `dags/`, `iam.yaml`, `resolvers.yaml`이 있는 폴더 |
| `--allow-external` | 꺼짐 | DAG가 다른 저장소의 서비스를 참조해도 허용 |
| `--db` | `<config>/.msdf/msdf.db` | 엔진의 메타데이터 DB |
| `--lease-ttl` | 60 | 단계 lease 시간(초). 심박은 그 1/3마다 |
| `--keep-generations` | 3 | 같은 요청의 최신 몇 세대를 캐시(hot)에 둘지 |
| `--keep-versions` | 3 | 같은 자리에서 버전만 다른 결과를 몇 개 hot에 둘지 |
| `--no-ui` | 꺼짐 | 웹 UI를 띄우지 않음 |
| `--ui-dist` | 패키지 안 `ui/dist` | 빌드한 웹 UI 폴더. 환경 변수 `MSDF_UI_DIST`로도 지정 |

서비스 쪽 환경 변수: `MSDF_SCHEDULER`(엔진 주소, 기본 `http://127.0.0.1:8787`).

> 엔진 API와 웹 UI에는 인증이 없습니다. `--host`를 `127.0.0.1`이 아닌 곳으로 열면 경고를 냅니다. 믿을 수 있는 네트워크에서만 여세요.
