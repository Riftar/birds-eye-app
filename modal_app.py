import modal

app = modal.App("birds-eye")
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "fastapi>=0.115", "pydantic-settings>=2.7", "httpx>=0.27", "uvicorn>=0.34"
    )
    .env({"PROVIDER_MODE": "live", "DEFAULT_SCENARIO_DIR": "/root/mock-data/default"})
    .add_local_python_source("birds_eye")
    .add_local_dir("mock-data", remote_path="/root/mock-data")
)


@app.function(
    image=image,
    secrets=[modal.Secret.from_local_environ(["BASETEN_API_KEY", "MODEL_API_KEY"])],
    cpu=0.5,
    memory=512,
    min_containers=0,
    scaledown_window=60,
    max_containers=1,
    timeout=300,
)
@modal.concurrent(max_inputs=4)
@modal.asgi_app()
def web():
    from birds_eye.app import create_app

    return create_app()
