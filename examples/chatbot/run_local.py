"""엔진과 서비스 넷을 프로세스 하나에서 돌려 보는 데모. (테스트와 체험용)

자기 프로세스 안에 따로 엔진과 DB(.msdf/local.db)를 만들어 돌고 끝나므로,
msdf up의 웹 UI에는 나타나지 않는다.
웹 UI에서 흐름을 보려면 run_services.py를 쓴다.

    python run_local.py "환불은 언제 되나요"

실제 운영처럼 따로 띄우려면 README의 '여러 프로세스로 실행'을 보세요.
"""

import os
import sys

from ms_dataflow.decorators import resolve_function
from ms_dataflow.execute.local import LocalRunner

HERE = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    questions = sys.argv[1:] or [
        "환불은 언제 되나요",
        "배송 조회는 어디서 하나요",
        "환불은 언제 되나요",
    ]
    with LocalRunner(HERE, db=os.path.join(HERE, ".msdf", "local.db")) as runner:
        chatbot = resolve_function(os.path.join(HERE, "chatbot.py"), "chatbot")
        for q in questions:
            print(f"> {q}")
            chatbot(q)
            runner.run_until_idle()
            plan = runner.last.plan
            cached = f" (캐시: {', '.join(plan.cached)})" if plan.cached else ""
            print(f"  실행한 단계: {', '.join(s.node for s in plan.steps) or '없음'}{cached}")
    print(
        "\n(이 데모는 자기 프로세스 안의 엔진으로 돌았으므로 "
        "msdf up의 웹 UI에는 나타나지 않습니다.\n"
        " UI에서 보려면: 터미널 1에서 uv run msdf up, 터미널 2에서 uv run python run_services.py)"
    )
