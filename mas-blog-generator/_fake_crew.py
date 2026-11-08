import os
import time


def slow_crew(topic: str) -> str:
    marker = f"/tmp/fake_crew_{os.getpid()}"
    for step in range(60):
        with open("/tmp/fake_crew_last_pid", "w") as f:
            f.write(str(os.getpid()))
        with open(marker, "w") as f:
            f.write(str(step))
        time.sleep(0.5)
    return "slow done"


def fast_crew(topic: str) -> str:
    return f"Article about {topic}\n" + "x" * 200_000 + "\nImage URL: http://example/img.png"


def failing_crew(topic: str) -> str:
    raise ValueError("boom from fake crew")
