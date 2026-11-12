from ms_dataflow import action, service, start


@service("search")
def search(): ...


@action(params=["q"], outputs=["out"], fresh_for="1d", retries=3)
def fetch(q: str): ...


if __name__ == "__main__":
    start()
