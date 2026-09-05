import os

from prometheus_client import Gauge, start_http_server

from serviceflow.agent.worker_tasks import celery_app

WORKER_UP = Gauge("serviceflow_worker_up", "Whether the Celery worker process is running.")


def main() -> None:
    start_http_server(int(os.getenv("SERVICEFLOW_WORKER_METRICS_PORT", "9101")))
    WORKER_UP.set(1)
    celery_app.worker_main(
        [
            "worker",
            "--loglevel=INFO",
            "--pool=solo",
        ]
    )


if __name__ == "__main__":
    main()
