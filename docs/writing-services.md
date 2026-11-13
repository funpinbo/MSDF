# 서비스 작성하기

**한국어** | [English](en/writing-services.md)

사용자가 쓰는 것은 여섯 개뿐입니다.

```python
from ms_dataflow import service, action, order, start, context, delete
```

| 이름 | 하는 일 |
| --- | --- |
| `service(name)` / `@service(name)` | 서비스를 선언합니다 |
| `@action(...)` | 데이터를 읽거나 쓰는 함수를 표시하고 슬롯을 선언합니다 |
| `order(name, params, meta=...)` | 결과물을 이름으로 요청하고 request_id를 받습니다 |
| `start()` | 이 프로세스를 엔진에 붙입니다 |
| `@context` | 권한 검사에 쓸 값(계정 등)을 알려 주는 함수를 표시합니다 |
| `delete(request_id)` | `order()`로 만든 데이터를 지웁니다 |

서비스 코드에는 다른 서비스의 이름, DB 종류, 저장 위치, 데이터 ID가 나오지 않습니다. 나오게 된다면 무언가 잘못 쓰고 있다는 신호입니다.

## `service()` / `@service`

서비스를 선언하는 방법은 두 가지이고, 결과는 같습니다.

```python
service("transform")       # 파일 최상위에 한 줄. 진입 함수가 없는 서비스(Action만 제공)
```

```python
@service("app")            # 서비스를 실행하는 함수가 있으면 그 함수에 붙인다
def app(day: str):
    order("daily_stats", params={"day": day})
```

- 파일 하나에 하나, 모듈 최상위에서만 씁니다. 이름은 문자열 리터럴이어야 합니다(코드를 실행하지 않고 읽기 때문).
- 선언한 파일에서 시작해 **프로젝트 안의 import를 따라가며** 찾은 `@action`은 모두 이 서비스 것이 됩니다. Action에 소속을 따로 적지 않습니다.
- 함수 안의 import도 따라갑니다. `if TYPE_CHECKING:` 블록은 건너뛰고, `importlib.import_module` 같은 동적 import는 따라가지 않고 경고합니다.
- 설치한 외부 패키지는 따라가지 않습니다.
- 두 서비스에서 동시에 닿는 Action이 있으면 로딩 오류입니다. 아래 [공통 로직](#여러-서비스가-같은-로직을-쓸-때)을 참고하세요.

## `@action`

```python
@action(
    inputs=["rows"],        # 입력 슬롯 이름 (함수 인자 이름과 같아야 함)
    outputs=["clean"],      # 출력 슬롯 이름. 기본 ["out"]
    params=[],              # order의 params에서 받을 이름 (첫 단계 Action만)
    version=None,           # 없으면 함수 소스로 자동 계산
    retries=0,              # 예외가 나면 다시 시도할 횟수
    retry_delay=0.0,        # 재시도 간격(초). 시도마다 두 배로 늘어남
    fresh_for=None,         # "30m", "1h", "1d" 등. 없으면 영구 캐시
)
def clean(rows):
    return [r for r in rows if r["value"] is not None]
```

선언할 것이 없으면 괄호 없이 써도 됩니다.

```python
@action
def on_stats_failed(status: str):
    print("실패:", status)
```

- 모듈 최상위 함수에만 붙입니다.
- 옵션 값은 리터럴로 적습니다(`inputs=NAMES`처럼 변수는 안 됨). 코드를 실행하지 않고 읽기 때문입니다.

### 입력과 출력

- `inputs`와 `params`의 이름은 **함수 인자 이름과 같아야** 합니다. 다르면 로딩할 때 오류로 알려 줍니다.
- 엔진이 입력 데이터를 읽어 인자로 넣어 주고, 반환값을 출력 슬롯에 저장합니다. 함수 안에서 DB를 직접 다루지 않습니다.
- 출력이 여러 개면 `outputs` 순서대로 튜플을 반환합니다.

```python
@action(inputs=["rows"], outputs=["stats", "outliers"])
def summarize(rows) -> tuple[dict, list]:
    return stats, outliers
```

- `async def`로 써도 됩니다.

### 저장할 수 있는 데이터

| 타입 | 저장 형식 |
| --- | --- |
| `dict`, `list`, `tuple`, `str`, 숫자, `bool`, `None` | JSON |
| `bytes` | 그대로 |
| pandas `DataFrame` | Parquet (`msdf[dataframe]` 필요) |
| 그 밖 | 거절 (`UnsupportedType`). 백엔드 설정에서 `allow_pickle: true`를 켜면 pickle |

### 버전

- `version`을 적지 않으면 함수 소스로 버전이 정해집니다. 로직을 고치면 새 버전이 되고, 그 단계부터 다시 계산합니다.
- Action이 부르는 **프로젝트 안의 함수, 클래스, 모듈 상수**도 버전에 들어갑니다. 같은 파일에 있든 `from util import normalize`나
  `import util`로 가져왔든, 그 함수가 다시 부르는 것까지 따라갑니다. 도우미 하나를 고쳐도 그 도우미를 쓰는 Action만 새 버전이 됩니다.
- 주석, 공백, 줄바꿈, docstring, 데코레이터 옵션만 바뀐 것은 같은 버전입니다.
- 설치한 외부 패키지(pandas 등)의 버전 변화는 보지 않습니다. 동적으로 고른 함수(`getattr`, 딕셔너리에서 꺼낸 함수)도 따라가지 못합니다.
  그럴 때는 `version="2"`처럼 직접 올려 주세요. `version`을 적으면 그 값만 씁니다.
- DAG 파일은 `version`을 덮어쓸 수 없습니다.

### 신선도

- `fresh_for`는 주로 외부에서 데이터를 가져오는 첫 단계에 씁니다. 기간이 지나면 새로 가져옵니다.
- DAG 노드에 `fresh_for`, `retries`, `retry_delay`를 적으면 데코레이터보다 우선합니다.

## `order()`

```python
request_id = order("daily_stats", params={"day": day})
request_id = order("daily_stats", params={"day": day}, meta={"session_id": sid}, idempotency_key=msg_id)
```

- **즉시 반환**합니다. 결과를 기다리지 않고 다른 일을 계속합니다.
- 결과는 DAG의 `deliveries`에 적힌 Action(`on_success` / `on_fail`)으로 도착합니다.
- 반환값은 **request_id**입니다. 요청마다 다릅니다(같은 데이터를 요청해도). `delete()`에도 쓸 수 있습니다.

| 인자 | 뜻 | cache key에 들어가나 |
| --- | --- | --- |
| `params` | **무엇을** 계산할지. DAG 첫 단계 Action의 `params`와 맞아야 함 | 들어감 |
| `meta` | 결과를 **누구에게** 돌려줄지 찾는 작은 값(예: `session_id`). 엔진이 보관했다가 delivery Action에 그대로 돌려줌. JSON, 4 KB까지 | 안 들어감. IAM에도 쓰지 않음 |
| `idempotency_key` | 같은 서비스가 같은 키로 다시 요청하면 새로 실행하지 않고 처음 request_id를 돌려줌. 네트워크 오류로 다시 보낼 때 | – |

`meta`가 cache key가 아니므로, 두 사용자가 같은 질문을 하면 **계산은 한 번, 결과는 각자의 `meta`와 함께 따로** 배달됩니다.

### delivery Action이 받는 것

```python
@action(inputs=["stats"])
def on_stats(stats: dict, meta: dict, request_id: str):     # meta, request_id는 선언할 때만 받음
    send_to_user(meta["session_id"], stats)

@action
def on_stats_failed(status: str, meta: dict, error: str | None):
    send_to_user(meta["session_id"], f"실패했습니다 ({status})")
```

| 인자 | on_success | on_fail | 값 |
| --- | --- | --- | --- |
| 결과 슬롯 (`inputs`의 첫 이름) | ○ | – | DAG의 `result` |
| `status` (첫 인자) | – | ○ | `"failed"` 또는 `"cancelled"` |
| `request_id` | ○ | ○ | `order()`가 돌려준 값 |
| `meta` | ○ | ○ | `order()`에 준 `meta` (없으면 `{}`) |
| `error` | – | ○ | 실패 원인의 마지막 줄 (없으면 `None`) |

선언하지 않은 인자는 넣지 않으므로 기존 delivery Action은 그대로 동작합니다. 계산하는 Action(produce)은 `meta`를 받지 않습니다. cache key에 없는 값이 결과를 바꾸면 cache가 틀어지기 때문입니다.
- 요청한 서비스의 이름은 `order()`를 부른 파일로 자동으로 정해집니다. 인자로 적지 않으며, 다른 서비스인 척할 수 없습니다.
- `params`의 이름은 DAG 첫 단계 Action이 `params=[...]`로 선언한 이름과 정확히 맞아야 합니다. 값은 JSON으로 바꿀 수 있어야 합니다.

`order()`가 던질 수 있는 예외는 `OrderError` 계열뿐입니다.

| 예외 | 언제 |
| --- | --- |
| `PermissionDenied` | IAM 규칙에 막힘. `.blocked`에 막힌 연결 목록 |
| `UnknownOrder` | 그런 이름의 DAG가 없거나, DAG의 deliveries에 이 서비스가 없음 |
| `ServiceUnavailable` | DAG가 거치는 서비스가 떠 있지 않음. `.missing`에 목록 |
| `ParamError` | params 이름이 빠졌거나 남음 |
| `OrderError` | 그 밖 (엔진에 연결할 수 없음 등) |

```python
from ms_dataflow.errors import OrderError, PermissionDenied

try:
    order("daily_stats", params={"day": day})
except PermissionDenied as e:
    print("권한 없음:", e.blocked)
except OrderError as e:
    print("요청 실패:", e)
```

## `start()`

```python
if __name__ == "__main__":
    start()      # 엔진에 붙는다 (바로 반환)
    app.run()    # 내 서비스는 평소대로 (웹 서버 등)
```

자기 메인 루프가 없는 서비스(Action만 제공)는 프로세스가 끝나지 않게 `block=True`를 줍니다.

```python
if __name__ == "__main__":
    start(block=True)   # Ctrl+C나 SIGTERM을 받으면 등록을 해제하고 끝난다
```

- 부른 파일에서 import로 닿는 서비스와 Action을 엔진에 등록하고, 단계 실행 요청을 받을 작은 서버를 백그라운드로 띄운 뒤 **바로 반환**합니다.
- 포트는 자동으로 잡습니다. 같은 서비스를 여러 개 띄우면 엔진이 쉬는 쪽에 일을 나눠 줍니다.
- 엔진 주소는 인자 → 환경 변수 `MSDF_SCHEDULER` → `http://127.0.0.1:8787` 순으로 정합니다.
- 엔진을 토큰과 함께 띄웠다면(`msdf up --token`) 같은 값을 `token=`이나 환경 변수 `MSDF_TOKEN`으로 줍니다. 틀리면 `RegistrationError`.
- 엔진이 아직 없으면 기다리며 다시 시도합니다. `start(required=False)`면 경고만 내고, 연결은 백그라운드에서 계속 시도합니다. `timeout=`초를 주면 그만큼만 기다립니다.
- 같은 이름의 서비스가 **다른 코드**로 이미 등록되어 있으면 `RegistrationError`를 냅니다. 옛 프로세스를 끄고 다시 띄우세요.
- 프로세스가 끝나면 등록을 해제합니다.

| 인자 | 기본 | 뜻 |
| --- | --- | --- |
| `scheduler` | `MSDF_SCHEDULER` 또는 `http://127.0.0.1:8787` | 엔진 주소 |
| `port` | `0` (자동) | 수신 서버 포트 |
| `required` | `True` | 엔진이 없을 때 기다릴지 |
| `host` | `127.0.0.1` | 수신 서버 주소 |
| `root` | 부른 파일의 폴더 | 코드 분석을 시작할 프로젝트 폴더 |
| `timeout` | 없음 | 엔진을 기다릴 최대 시간(초) |
| `block` | `False` | `True`면 반환하지 않고 Ctrl+C나 SIGTERM까지 기다린다. Action만 제공하는 서비스용 |
| `token` | `MSDF_TOKEN` | 엔진 토큰 (`msdf up --token`과 같은 값) |

## `@context`

IAM 규칙에 계정 등급 같은 계층을 쓴다면, 그 값을 알려 주는 함수를 하나 둡니다.

```python
@context
def who() -> dict:
    return {"account": current_user.role}
```

- `order()`를 낼 때마다 호출됩니다. 요청마다 로그인한 사용자가 다를 수 있기 때문입니다.
- 반환 키는 `iam.yaml`의 계층 이름과 맞아야 합니다. 규칙이 쓰는 계층이 빠져 있으면 `start()` 때 등록이 거부됩니다.
- 엔진은 이 값을 **그대로 믿습니다.** 값을 어떻게 얻고 검증할지는 서비스(인증 시스템)의 몫입니다.
- 계층이 서비스뿐이라면 필요 없습니다.

## `delete()`

```python
request_id = order("daily_stats", params={"day": day})
# ... 결과를 다 쓴 뒤
delete(request_id)                 # 그 결과 데이터를 지운다
delete(request_id, cascade=True)   # 그 데이터로 만든 하위 데이터까지
```

- IAM의 `delete` 규칙으로 검사합니다. 막히면 `PermissionDenied`.
- 엔진이 먼저 삭제 표시를 남기므로, 그 순간부터 캐시로 쓰이지 않습니다. 저장소의 본체 삭제가 실패하면 표시를 둔 채 나중에 다시 시도합니다.
- 지운 Artifact 수를 돌려줍니다.

## 여러 서비스가 같은 로직을 쓸 때

로직은 `@action`이 없는 일반 모듈에 두고, 서비스마다 자기 Action을 만들어 호출합니다.

```python
# common/cleaning.py   (@action 없음. 어느 서비스가 import해도 됨)
def drop_empty(rows):
    return [r for r in rows if r["value"] is not None]

# transform.py
@action(inputs=["rows"], outputs=["clean"])
def clean(rows):
    return drop_empty(rows)

# report.py
@action(inputs=["rows"], outputs=["clean"])
def tidy(rows):
    return drop_empty(rows)
```

같은 로직이어도 서비스가 다르면 결과는 따로 저장됩니다. 결과 자체를 여러 서비스가 공유해야 한다면 별도 서비스로 만들고 `order`로 요청하세요.

## 로딩 오류는 이렇게 보입니다

```text
MSDF 로딩 오류: transform.py:12
  @action(inputs=["rows"])
  def clean(data):

  선언한 입력 슬롯 'rows'가 함수 인자에 없습니다.
  함수 인자: data
  고칠 방법: clean의 인자 이름을 'rows'로 맞추거나 선언을 고치세요.
```

오류가 여러 개면 첫 번째에서 멈추지 않고 한 번에 모아서 보여 줍니다(`LoadErrors`).
