# calc 픽스처

프레임워크 검증용 최소 서비스. 도메인 로직 없이 숫자만 다룬다.
각 Action은 호출될 때 `CALC_LOG` 환경 변수가 가리키는 파일에 한 줄을 남겨,
테스트가 "실행됐는가/캐시로 건너뛰었는가"를 확인할 수 있게 한다.

```text
src.make(n) ─▶ mid.add ─▶ mid.double ─▶ req.on_done / req.on_fail
```

`CALC_FAIL`에 Action 이름을 넣으면 그 Action이 예외를 낸다 (`add:2`면 처음 2번만 실패).
