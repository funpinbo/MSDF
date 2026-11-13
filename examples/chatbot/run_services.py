"""실행 중인 엔진(msdf up)에 예제 서비스 넷을 붙이고, 예시 질문을 계속 보낸다.

웹 UI(http://127.0.0.1:8787/ui)에서 데이터 흐름, 수치, 로그가 실시간으로 쌓이는 것을 볼 수 있다.

    uv run msdf up                       # 터미널 1 — 엔진
    uv run python run_services.py        # 터미널 2 — 서비스 넷 + 질문 (Ctrl+C로 모두 종료)

질문 간격은 환경 변수 ASK_EVERY(초, 기본 3)로 바꾼다. 엔진 주소는 MSDF_SCHEDULER.
"""

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# 같은 질문이 반복되므로 두 번째부터는 캐시로 답한다. 마지막 질문은 맞는 문서가 없다.
QUESTIONS = [
    "환불은 언제 되나요",
    "배송 조회는 어디서",
    "회원 등급 혜택",
    "환불은 언제 되나요",
    "비밀번호 재설정 메일",
    "교환 절차",
    "배송 조회는 어디서",
    "우주선 발사 일정",
]


def main() -> None:
    every = float(os.environ.get("ASK_EVERY", "3"))
    services = ["search", "embedding", "processing"]
    procs = [subprocess.Popen([sys.executable, os.path.join(HERE, f"{s}.py")]) for s in services]
    try:
        sys.path.insert(0, HERE)
        import chatbot  # 이 프로세스는 chatbot 서비스가 된다

        from ms_dataflow import start
        from ms_dataflow.errors import OrderError

        start(timeout=30)
        time.sleep(2)  # 다른 서비스가 등록될 시간을 준다
        print("서비스 넷을 엔진에 붙였습니다. 웹 UI에서 흐름을 보세요. (Ctrl+C로 종료)", flush=True)
        i = 0
        while True:
            question = QUESTIONS[i % len(QUESTIONS)]
            try:
                print(f"> {question}", flush=True)
                # 사용자 셋이 번갈아 묻는다
                chatbot.chatbot(question, session_id=f"user{i % 3 + 1}")
                i += 1
            except OrderError as e:  # 다른 서비스가 아직 등록 중이면 잠시 뒤 다시
                print(f"  (잠시 뒤 다시 시도: {e})", flush=True)
            time.sleep(every)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
