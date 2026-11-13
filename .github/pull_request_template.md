<!-- 한국어 또는 영어로 써 주세요. Korean or English is fine. -->

## 무엇을 바꿨나 / What changed

## 왜 / Why

<!-- 관련 이슈 / Related issue: #… -->

## 확인 / Checklist

- [ ] `uv run pytest` 통과 (guards, e2e 포함) / passes, including guards and e2e
- [ ] 문서를 한국어와 영어 둘 다 고쳤다 / docs updated in both Korean and English (`docs/` + `docs/en/`)
- [ ] CHANGELOG(ko/en)에 적었다 / CHANGELOG updated (ko/en)
- [ ] cache key, Action 버전, DB 구조, 엔진↔서비스 메시지에 영향이 있다면 CHANGELOG의 "바뀐 것"에 적었다 /
      if this affects cache keys, Action versions, the DB schema or engine↔service messages, it is listed under "Changed"
- [ ] 서비스 코드에 데이터 ID, 큐, HTTP, 저장소가 새어 나오지 않는다 / no data IDs, queues, HTTP or storage leak into service code
- [ ] guard를 고쳤다면 이유를 아래에 적었다 / if a guard was changed, the reason is written below

## guard를 바꿨다면 그 이유 / If a guard changed, why
