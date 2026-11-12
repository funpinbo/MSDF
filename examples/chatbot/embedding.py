from ms_dataflow import action, service, start


@service("embedding")
def embedding(): ...


@action(inputs=["docs"], outputs=["out"], retries=3)
def embed(docs): ...


if __name__ == "__main__":
    start()
