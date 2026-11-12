# 기여 안내

현재 상태: **설계 완료, 구현 시작 전.** 코드보다 설계 논의가 더 유용한 시기입니다.

## 시작하기

```bash
git clone https://github.com/OWNER/msdf
cd msdf
uv sync --all-extras
uv run pytest
```

## 먼저 읽을 것

1. [docs/concepts.md](docs/concepts.md) — 무엇을 하는가
2. [docs/how-it-works.md](docs/how-it-works.md) — 어떻게 동작하는가
3. [docs/roadmap.md](docs/roadmap.md) — 어디까지 왔고 어디로 가는가

문서에 적힌 동작을 바꾸려면 이슈를 먼저 열어 주세요. 하나를 바꾸면 다른 쪽이 따라 바뀌는 결정이 많습니다.

## 구현 순서

[docs/roadmap.md](docs/roadmap.md)에 10단계가 있습니다. 앞 단계 위에 뒤 단계가 쌓이므로 순서대로 가는 편이 낫습니다.
1~5단계는 프로세스 하나로 돌려볼 수 있어 Worker 서버 없이도 검증됩니다.

## 테스트에서 먼저 지켜야 할 것

다음 다섯 가지는 깨지면 조용히 잘못된 데이터가 나갑니다. 관련 코드를 건드리면 테스트를 함께 확인해 주세요.

1. **해시 결정성** — 같은 입력이면 항상 같은 `lineage_key`와 `artifact_id`
2. **Planner와 Resolver의 ID 일치** — `planned_id`와 Resolver 발급 값이 같아야 한다
3. **version 정규화** — 주석·공백만 다르면 같은 version, 로직이 다르면 다른 version
4. **소속 판정** — 두 서비스가 같은 Action에 닿으면 로딩 오류
5. **재시작 안전성** — Scheduler를 임의 시점에 죽였다 살려도 상태가 복구된다

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
