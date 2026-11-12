# 설치

**한국어** | [English](en/installation.md)

MSDF는 **아직 PyPI에 올리지 않았습니다.** `pip install msdf`로는 설치되지 않으며, 아래 세 방법 중 하나를 씁니다.

| 방법 | 어디에 | 웹 UI |
| --- | --- | --- |
| [1. 저장소를 받아 설치](#1-저장소를-받아-설치-권장) | 엔진(`msdf up`)을 띄우는 곳, 처음 써 보는 곳 | 저장소 안에서 빌드 |
| [2. git 주소로 설치](#2-git-주소로-설치) | 각 서비스 프로젝트 (다른 저장소) | 필요 없음 (엔진에서 쓸 때는 `--ui-dist`) |
| [3. 휠 파일로 나눠 주기](#3-휠-파일로-나눠-주기) | 인터넷이나 git 접근이 없는 곳 | 휠에 포함 |

필요한 것: 파이썬 3.11 이상. 웹 UI를 빌드하려면 Node.js 20.19 이상(22 권장).

## 설치 묶음

어느 방법이든 `[...]`로 필요한 부분만 고릅니다.

| 묶음 | 들어 있는 것 | 언제 |
| --- | --- | --- |
| (없음) | 데코레이터, 모델, 정적 분석, `msdf check` | 코드 작성, 검증 |
| `runtime` | 위 + `start()`가 띄우는 수신 서버 | 서비스를 실제로 돌릴 때 |
| `server` | 위 + Scheduler와 웹 UI 서버 | `msdf up`을 실행할 때 |
| `dataframe` | pandas, pyarrow | DataFrame을 주고받을 때 (Parquet 저장) |

패키지 이름은 `msdf`, 코드에서 import하는 이름은 항상 `ms_dataflow`입니다.

## 1. 저장소를 받아 설치 (권장)

엔진을 띄우는 곳과 처음 써 보는 곳은 이 방법이 가장 간단합니다. 웹 UI도 저장소 안에서 바로 빌드됩니다.

[uv](https://docs.astral.sh/uv/)를 쓰는 경우:

```bash
git clone https://github.com/funpinbo/MSDF.git
cd MSDF
uv sync --all-extras
```

`uv sync`가 저장소 안에 가상 환경(`.venv`)을 만들고, 의존성과 MSDF 자체를 **편집 가능 모드**로 설치합니다.
MSDF 코드를 복사하지 않고 `.venv`에 "저장소 경로"를 적은 `.pth` 파일 하나만 두므로, 저장소의 코드를 고치면 다시 설치하지 않아도 바로 반영됩니다.
이후 저장소 안 어디서든 `uv run ...`으로 실행하면 이 `.venv`를 씁니다(uv가 위쪽 폴더의 `pyproject.toml`을 찾아갑니다).

> `uv sync` 없이 바로 `uv run`을 해도 uv가 `.venv`를 자동으로 만들고 MSDF를 설치하지만, **추가 묶음(`server`, `runtime`)은 빠집니다.**
> 그러면 `msdf check`는 되지만 `msdf up`과 `start()`는 묶음이 없다고 알려 줍니다. 처음 한 번은 `uv sync --all-extras`를 하세요.

pip를 쓰는 경우:

```bash
git clone https://github.com/funpinbo/MSDF.git
cd MSDF
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[server,dataframe]"
```

웹 UI 빌드 (한 번만, 그리고 UI 소스가 바뀔 때마다):

```bash
cd frontend
npm install
npm run build                      # 결과: ms_dataflow/ui/dist
```

확인:

```bash
msdf --version                     # uv라면 uv run msdf --version
```

업데이트는 `git pull` 뒤 `uv sync --all-extras`(또는 `pip install -e ".[server]"`)와 `npm run build`를 다시 합니다.

## 2. git 주소로 설치

서비스가 각자 다른 저장소에 있다면, 서비스 쪽에서는 git 주소로 `runtime` 묶음만 설치하면 됩니다.

```bash
pip install "msdf[runtime] @ git+https://github.com/funpinbo/MSDF.git"
```

특정 버전에 고정하려면 태그나 커밋을 붙입니다.

```bash
pip install "msdf[runtime] @ git+https://github.com/funpinbo/MSDF.git@v0.1.0"
```

의존성 파일에 적을 때:

```text
# requirements.txt
msdf[runtime] @ git+https://github.com/funpinbo/MSDF.git@v0.1.0
```

```toml
# pyproject.toml
[project]
dependencies = ["msdf[runtime] @ git+https://github.com/funpinbo/MSDF.git@v0.1.0"]
```

uv라면 `uv add "msdf[runtime] @ git+https://github.com/funpinbo/MSDF.git" --tag v0.1.0`.

**git 주소로 설치하면 웹 UI 빌드 결과는 들어 있지 않습니다**(저장소에 빌드 결과를 넣지 않기 때문입니다). 이렇게 설치한 곳에서 엔진을 띄우고 UI도 쓰려면,
저장소를 받아 UI를 한 번 빌드한 뒤 그 폴더를 알려 줍니다.

```bash
msdf up --ui-dist /경로/MSDF/ms_dataflow/ui/dist
# 또는 환경 변수: MSDF_UI_DIST=/경로/MSDF/ms_dataflow/ui/dist msdf up
```

UI 없이 엔진만 띄워도 실행에는 문제가 없습니다. `/ui`에 빌드 방법이 안내되고 JSON API는 그대로 동작합니다.

## 3. 휠 파일로 나눠 주기

인터넷이나 git 접근이 없는 서버에는 휠 파일을 만들어 옮깁니다. UI를 먼저 빌드하면 휠 안에 함께 들어갑니다.

```bash
cd MSDF
(cd frontend && npm install && npm run build)
uv build --wheel                   # 또는: pip install build && python -m build --wheel
ls dist/                           # msdf-0.1.0-py3-none-any.whl
```

옮긴 곳에서:

```bash
pip install "msdf-0.1.0-py3-none-any.whl[server]"
```

> 휠에는 UI가 쓰는 라이브러리의 빌드된 코드가 들어갑니다: Vue, vue-router, Vue Flow(안에 VueUse 포함), dagre는 MIT,
> Vue Flow 안에 포함된 d3 모듈(d3-zoom, d3-drag 등)은 ISC입니다. 둘 다 허용형 라이선스라 사용에는 제약이 없지만,
> 휠을 외부에 배포할 때는 각 라이브러리의 저작권 고지와 라이선스 전문을 함께 넣어야 합니다.

## 무엇을 어디에 설치하나

```text
엔진 머신        방법 1 (server, UI 빌드)          msdf up
서비스 A 저장소   방법 2 (runtime)                  python service_a.py  ← start()
서비스 B 저장소   방법 2 (runtime)                  python service_b.py  ← start()
```

엔진과 모든 서비스는 **같은 버전**을 쓰는 것이 안전합니다. git 주소에 같은 태그를 붙이세요.

## 문제가 생기면

| 증상 | 확인할 것 |
| --- | --- |
| `pip install msdf`가 실패한다 | 아직 PyPI에 없습니다. 위의 방법을 쓰세요 |
| Windows에서 `msdf`나 `python`이 `UnicodeDecodeError: 'cp949' codec can't decode`를 내며 시작하지 않는다 | 프로젝트 경로에 한글이 있고 파이썬이 3.12 이하라서, 편집 가능 설치가 만든 `.pth` 파일을 cp949로 읽다 실패한 것입니다. ① `PYTHONUTF8=1`로 UTF-8 모드를 켜거나(PowerShell: `$env:PYTHONUTF8 = "1"`, 계속 쓰려면 `setx PYTHONUTF8 1` 후 새 터미널), ② 영문 경로(예: `C:\dev\MSDF`)로 옮겨 `.venv`를 다시 만들거나, ③ 파이썬 3.13 이상을 쓰세요 |
| `msdf up`이 "server 묶음이 필요합니다", `start()`가 "runtime 묶음이 필요합니다"라고 한다 | 묶음 없이 설치되었습니다. 저장소에서는 `uv sync --all-extras`, pip라면 `pip install -e ".[server]"` |
| `msdf: command not found` | 가상 환경을 켰는지(`source .venv/bin/activate`), uv라면 `uv run msdf` |
| `/ui`에 "빌드되지 않았습니다"가 나온다 | `cd frontend && npm run build`, 또는 `msdf up --ui-dist 경로` |
| `npm run build`가 Node 버전 오류를 낸다 | Node.js 20.19 이상 또는 22.12 이상 |
| 브라우저에서 `http://127.0.0.1:8787/ui`가 열리지 않는다 | ① `msdf up`이 떠 있는지(`run_local.py`에는 웹 UI가 없습니다), ② 엔진이 원격 서버·VM에서 돈다면 `127.0.0.1`은 그 컴퓨터 자신만 가리킵니다. 내 컴퓨터에서 `ssh -L 8787:127.0.0.1:8787 사용자@서버`로 터널을 연 뒤 `http://127.0.0.1:8787/ui`를 엽니다. 믿을 수 있는 네트워크라면 `msdf up --host 0.0.0.0`으로 열고 `http://서버주소:8787/ui`로 접속해도 됩니다(방화벽에서 8787 허용). ③ 화면이 비어 있으면 `frontend`에서 `npm run build`를 했는지 확인하세요 |
| `start()`가 "엔진을 기다리는 중"에서 멈춘다 | `msdf up`이 떠 있는지, 주소가 맞는지(`MSDF_SCHEDULER`) |
| 엔진이 "스키마 v1로 만들어졌고" 오류를 낸다 | 0.x 동안은 DB를 자동 변환하지 않습니다. `.msdf/msdf.db`를 지우고 다시 시작 (캐시와 실행 기록만 사라짐) |
