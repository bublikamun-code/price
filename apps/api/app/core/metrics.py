"""Prometheus-метрики — заглушка (501 Not Implemented)."""

DEFAULT_QUEUE = "celery"


def record_task_duration(task_name: str, duration: float) -> None:
    """Записать длительность задачи — заглушка."""
    pass


def record_task_failure(task_name: str) -> None:
    """Записать сбой задачи — заглушка."""
    pass


def push_worker_metrics() -> None:
    """Отправить метрики воркера в Pushgateway — заглушка."""
    pass


def push_beat_metrics() -> None:
    """Отправить метрики beat в Pushgateway — заглушка."""
    pass


def set_queue_depth(queue: str, depth: int) -> None:
    """Установить глубину очереди — заглушка."""
    pass
