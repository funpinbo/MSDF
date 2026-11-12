from ms_dataflow import action, service, start


@service("processing")
def processing(): ...


@action(inputs=["vectors"], outputs=["summary", "keywords"])
def refine(vectors): ...  # 반환 순서 = outputs 순서


if __name__ == "__main__":
    start()
