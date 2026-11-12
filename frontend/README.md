# MSDF 웹 UI

**한국어** | [English](README.en.md)

`msdf up`이 `/ui`에서 보여 주는 화면의 소스입니다. Vue 3 + Vue Flow + Vite.

빌드 결과(`ms_dataflow/ui/dist`)는 저장소에 넣지 않습니다. 저장소를 받은 뒤 한 번 빌드하세요.

```bash
cd frontend
npm install
npm run build        # → ../ms_dataflow/ui/dist
```

Node.js 20.19 이상(22 권장)이 필요합니다. 빌드하지 않고 `msdf up`을 띄우면 `/ui`가 이 빌드 방법을 안내합니다. 엔진과 JSON API는 빌드와 상관없이 동작합니다.

MSDF를 git 주소로 설치한 곳에서는 패키지 안에 빌드 결과가 없으므로, 빌드한 폴더를 알려 줍니다.

```bash
msdf up --ui-dist /경로/MSDF/ms_dataflow/ui/dist   # 또는 MSDF_UI_DIST 환경 변수
```

## 개발

```bash
msdf up              # 터미널 1 — 엔진 (8787)
npm run dev          # 터미널 2 — http://localhost:5173/ui/ (/api는 엔진으로 프록시)
```

## 화면

| 경로 | 페이지 | 내용 |
| --- | --- | --- |
| `#/` | 실시간 맵 | 모든 서비스·Action과 데이터 흐름을 한 장의 그래프로. Action별 완료·실패·캐시·실행 중 수, 엣지별 이동한 데이터 수, 성공률, 처리량 |
| `#/editor/:order` | DAG 편집기 | Action을 끌어다 놓아 노드를 만들고, 출력 점에서 입력 점으로 끌어 연결. 저장하면 `dags/*.yaml`을 쓰고 엔진에 바로 반영 |
| `#/logs/runs` | 실행 로그 | DAG·요청 서비스·상태로 거르기 |
| `#/logs/steps` | 단계 로그 | 서비스·DAG·상태·검색어로 거르기. 오류 원문과 데이터 계보 |
| `#/logs/services` | 서비스 | 인스턴스, 심박, Action별 통계 |
| `#/logs/dags` | DAG | DAG별 통계와 YAML |
| `#/logs/engine` | 엔진 로그 | 엔진 프로세스의 로그를 실시간으로 |
| `#/runs/:id` | 실행 상세 | 실행 하나의 그래프, 단계 타임라인, 실패 위치, 결과 계보 |

## 파일

| 파일 | 내용 |
| --- | --- |
| `src/api.js` | API 호출과 주기적 갱신 (`usePoll`) |
| `src/layout.js` | dagre 자동 배치 (서비스별로 묶기) |
| `src/pages/` | 페이지 |
| `src/components/` | 노드, 표, 차트 같은 부품 |

## 라이선스

이 디렉터리의 코드는 MSDF와 같은 MIT입니다. 저장소에는 소스만 있고, 의존성은 `npm install` 때 각자 내려받습니다.

빌드 결과에 실제로 들어가는 라이브러리:

| 라이브러리 | 라이선스 |
| --- | --- |
| vue (@vue/runtime-dom, runtime-core, reactivity, shared) | MIT |
| vue-router | MIT |
| @vue-flow/core, background, controls, minimap (안에 @vueuse/core 포함) | MIT |
| d3-zoom, d3-drag, d3-selection, d3-interpolate 등 (@vue-flow/core 안에 포함) | ISC |
| @dagrejs/dagre | MIT |

빌드 결과를 따로 배포한다면(예: 휠에 포함) 그 안에 위 코드가 들어가므로 각 저작권 고지와 라이선스 전문을 함께 넣어야 합니다.
Vite 등 빌드 도구는 결과물에 들어가지 않습니다.
