# 서비스 작성하기

> **현재 상태: 구현 전.** 아래 API는 목표하는 형태이며 구현 중에 바뀔 수 있습니다.

사용자가 쓰는 것은 다섯 개뿐입니다.

```python
from ms_dataflow import service, action, order, start, context
```

| 이름 | 하는 일 |
| --- | --- |
| `@service(name)` | 서비스의 진입점을 표시합니다 |
| `@action(...)` | 데이터를 읽거나 쓰는 함수를 표시하고 슬롯을 선언합니다 |
| `order(name, params)` | 결과물을 이름으로 요청합니다 |
| `start()` | 이 프로세스를 엔진에 붙입니다 |
| `@context` | 권한 검사에 쓸 값(계정 등)을 알려 주는 함수를 표시합니다 |

서비스 코드에는 다른 서비스의 이름, DB 종류, 저장 위치, 데이터 ID가 나오지 않습니다. 나오게 된다면 무언가 잘못 쓰고 있다는 신호입니다.

## `@service`

```python
@service("chatbot")
def chatbot(question: str): ...
```

- 서비스 전체를 실행하는 함수에 하나만 붙입니다.
- 이 함수가 있는 파일에서 시작해 **프로젝트 안의 import를 따라가며** 찾은 `@action`은 모두 이 서비스 것이 됩니다. Action에 소속을 따로 적지 않습니다.
- 외부 패키지(설치한 라이브러리)는 따라가지 않습니다.
- 두 서비스에서 동시에 닿는 Action이 있으면 로딩 오류입니다. 아래 [공통 로직](#여러-서비스가-같은-로직을-쓸-때)을 참고하세요.

## `@action`

```python
@action(
    inputs=["docs"],        # 입력 슬롯 이름 (함수 인자 이름과 같아야 함)
    outputs=["out"],        # 출력 슬롯 이름. 기본 ["out"]
    params=[],              # order의 params에서 받을 이름 (첫 단계 Action만)
    version=None,           # 없으면 함수 소스로 자동 계산
    retries=0,              # 예외가 나면 다시 시도할 횟수
    retry_delay=0.0,        # 재시도 간격(초). attempt마다 두 배로 늘어남
    fresh_for=None,         # "30m", "1d" 등. 없으면 영구 캐시
)
def embed(docs): ...
```

선언할 것이 없으면 괄호 없이 써도 됩니다.

```python
@action
def on_search_failed(status: str): ...
```

### 입력과 출력

- `inputs`와 `params`의 이름은 **함수 인자 이름과 같아야** 합니다. 다르면 로딩할 때 오류로 알려 줍니다.
- 엔진이 입력 데이터를 읽어 인자로 넣어 주고, 반환값을 출력 슬롯에 저장합니다. 함수 안에서 DB를 직접 다루지 않습니다.
- 출력이 여러 개면 `outputs` 순서대로 튜플을 반환합니다.

```python
@action(inputs=["vectors"], outputs=["summary", "keywords"])
def refine(vectors) -> tuple[str, list]:
    return summary, keywords
```

- `async def`로 써도 됩니다. 엔진이 알아서 구분합니다.
- 타입 힌트(`DataFrame`, `bytes`, `dict` 등)를 붙이면 저장소가 그 형태로 데이터를 넘겨줍니다.

### 저장할 수 있는 데이터

| 타입 | 저장 형식 |
| --- | --- |
| pandas `DataFrame` | Parquet |
| `dict`, `list` | JSON |
| `bytes` | 그대로 |
| 그 밖 | 기본으로는 거절 (`UnsupportedType`). pickle은 명시적으로 켜야 함 |

### 버전

- `version`을 적지 않으면 함수 소스 코드로 버전이 정해집니다. 로직을 고치면 새 버전이 되고, 그 단계부터 다시 계산합니다.
- 함수가 부르는 **다른 함수**가 바뀐 것은 감지하지 못할 수 있습니다. 그럴 때는 `version="2"`처럼 직접 올려 주세요.
- DAG 파일은 `version`을 덮어쓸 수 없습니다.

### 신선도

- `fresh_for`는 주로 외부에서 데이터를 가져오는 첫 단계에 씁니다. 기간이 지나면 새로 가져옵니다.
- DAG 노드에 `fresh_for`를 적으면 데코레이터보다 우선합니다. 그래서 같은 Action도 DAG마다 다른 신선도를 쓸 수 있습니다.

## `order()`

```python
order("search_result", params={"q": question})
```

- **즉시 반환**합니다. 결과를 기다리지 않고 다른 일을 계속합니다.
- 결과는 DAG의 `deliveries`에 적힌 Action(`on_success` / `on_fail`)으로 도착합니다.
- 요청한 서비스의 이름은 자동으로 채워집니다. 인자로 적지 않으며, 다른 서비스인 척할 수 없습니다.
- `params`의 이름은 DAG 첫 단계 Action이 `params=[...]`로 선언한 이름과 정확히 맞아야 합니다. 값은 JSON으로 바꿀 수 있어야 합니다.

`order()`가 던질 수 있는 예외는 `OrderError` 계열뿐입니다.

| 예외 | 언제 |
| --- | --- |
| `PermissionDenied` | IAM 규칙에 막힘. 어느 연결이 막혔는지 담겨 있음 |
| `UnknownOrder` | 그런 이름의 DAG가 없음 |
| `ServiceUnavailable` | DAG가 거치는 서비스가 떠 있지 않음 |
| `ParamError` | params 이름이 빠졌거나 남음 |

```python
from ms_dataflow.errors import OrderError, PermissionDenied

try:
    order("search_result", params={"q": question})
except PermissionDenied as e:
    ...   # 권한 없음
except OrderError:
    ...   # 그 밖의 요청 실패
```

## `start()`

```python
if __name__ == "__main__":
    start()      # 엔진에 붙는다
    app.run()    # 내 서비스는 평소대로
```

- 이 프로세스의 서비스와 Action을 엔진에 등록하고, 단계 실행 요청을 받을 작은 서버를 백그라운드로 띄운 뒤 **바로 반환**합니다. 사용자 서비스 실행을 막지 않습니다.
- 포트는 자동으로 잡습니다. 같은 서비스를 여러 개 띄우면 엔진이 쉬는 쪽에 일을 나눠 줍니다.
- 엔진 주소의 기본값은 `http://127.0.0.1:8787`입니다. `start(scheduler="http://...")`로 바꿀 수 있습니다.
- 엔진이 아직 떠 있지 않으면 기다리며 다시 시도합니다. `start(required=False)`면 경고만 내고 서비스는 그대로 돕니다.
- 프로세스가 끝나면 등록을 해제합니다.

## `@context`

IAM 규칙에 계정·테넌트 같은 계층을 쓴다면, 그 값을 알려 주는 함수를 하나 둡니다.

```python
@context
def who() -> dict:
    return {"account": current_user.role, "tenant": current_user.tenant}
```

- `order()`를 낼 때마다 호출됩니다. 요청마다 로그인한 사용자가 다를 수 있기 때문입니다.
- 반환 키는 `iam.yaml`의 계층 이름과 맞아야 합니다. 맞지 않으면 `start()`할 때 알려 줍니다.
- 엔진은 이 값을 **그대로 믿습니다.** 값을 어떻게 얻고 검증할지는 서비스(인증 시스템)의 몫입니다.
- 계층이 서비스뿐이라면 필요 없습니다.

## 여러 서비스가 같은 로직을 쓸 때

로직은 `@action`이 없는 일반 모듈에 두고, 서비스마다 자기 Action을 만들어 호출합니다.

```python
# common/clean.py   (@action 없음. 어느 서비스가 import해도 됨)
def clean_text(df): ...

# search.py
@action(inputs=["docs"], outputs=["out"])
def clean(docs): return clean_text(docs)

# chatbot.py
@action(inputs=["history"], outputs=["out"])
def clean(history): return clean_text(history)
```

같은 로직이어도 서비스가 다르면 결과는 따로 저장됩니다. 결과 자체를 여러 서비스가 공유해야 한다면 별도 서비스로 만들고 `order`로 요청하세요.

## 큰 데이터

대용량이나 스트리밍처럼 한 번에 올릴 수 없는 데이터는 `ctx.load()`, `ctx.save()`로 직접 읽고 쓰는 길을 둘 예정입니다. 이때도 슬롯은 데코레이터에 선언해야 합니다. 세부는 [로드맵](roadmap.md)의 미정 항목입니다.

## 로딩 오류는 이렇게 보입니다

```text
MSDF 로딩 오류: services/search.py:12
  @action(inputs=["docs"])
  def fetch(q: str) -> DataFrame:

  선언한 입력 슬롯 'docs'가 함수 인자에 없습니다.
  함수 인자: q
  고칠 방법: inputs를 ["q"]로 바꾸거나, q를 params로 선언하세요.
```

오류가 여러 개면 첫 번째에서 멈추지 않고 한 번에 모아서 보여 줍니다.
