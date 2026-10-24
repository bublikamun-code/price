"""Границы слоёв: зависимости должны идти сверху вниз.

§4 требует, чтобы нижние слои не знали о верхних. Нарушения не падают при
импорте — они накапливаются незаметно, пока сервис не начнёт тянуть роутер.

Про api-слой сделано исключение намеренно: роутеры в этом проекте ходят в
реpositories и models напрямую, и это устоявшийся шаблон. Запрещать его —
значит требовать рефакторинга, которого никто не просил.

Тест разбирает AST, а не текст: импорт внутри комментария или строки его не обманет.
"""

import ast
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

# Слой → какие слои ему запрещено импортировать.
ЗАПРЕТЫ: dict[str, tuple[str, ...]] = {
    "api": (),
    "services": ("api",),
    "repositories": ("api", "services"),
    "models": ("api", "services", "repositories"),
}

СЛОИ = tuple(ЗАПРЕТЫ)


def _файлы_слоя(слой: str) -> list[Path]:
    return sorted((APP / слой).rglob("*.py"))


def _импортированные_слои(файл: Path) -> set[str]:
    """Слои, из которых этот файл импортирует что-либо из пакета app."""
    дерево = ast.parse(файл.read_text(encoding="utf-8"), filename=str(файл))
    найдено: set[str] = set()
    for узел in ast.walk(дерево):
        if isinstance(узел, ast.Import):
            for имя in узел.names:
                найдено.update(часть for часть in имя.name.split(".") if часть in СЛОИ)
        elif isinstance(узел, ast.ImportFrom) and узел.module and узел.level == 0:
            найдено.update(часть for часть in узел.module.split(".") if часть in СЛОИ)
    return найдено


@pytest.mark.parametrize("слой", СЛОИ)
def test_слой_не_тянет_себя_из_чужих_слоёв(слой: str) -> None:
    нарушения: list[str] = []
    for файл in _файлы_слоя(слой):
        for запрещённый in ЗАПРЕТЫ[слой]:
            if запрещённый in _импортированные_слои(файл):
                нарушения.append(f"{файл.relative_to(APP.parent)} импортирует app.{запрещённый}")
    assert not нарушения, (
        "Зависимость снизу вверх (§4):\n  " + "\n  ".join(нарушения) +
        "\nСервисы и репозитории не должны знать о роутерах."
    )


def test_доменная_ошибка_не_лежит_в_слое_api() -> None:
    """V2ProblemError бросается сервисами — значит, и лежать должна не в api/.

    Регрессия: класс жил в app/api/v2/errors.py, и app/services/auth_v2.py
    импортировал его оттуда — нижний слой зависел от верхнего, при том что
    сам api/v2/errors.py тянет хендлеры FastAPI (связь на уровне пакетов).
    """
    сервисы = "".join(ф.read_text(encoding="utf-8") for ф in _файлы_слоя("services"))
    assert "from app.api" not in сервисы, (
        "Сервис импортирует что-то из app.api — перенеси это в app/core "
        "или app/schemas и переэкспортируй обратно для совместимости."
    )


def test_роутеры_не_содержат_сырого_sql() -> None:
    """Сырой SQL в роутере означает, что слой доступа обойдён.

    Ищем ключевое слово в начале строкового литерала, а не подстроку: иначе
    зацепим русское «выделите» и английское «update» в разметке.

    Исключение — health-роутеры: `SELECT 1` там не обход слоя, а прямая
    проверка живости соединения, которой нет ни в одной репозитории.
    """
    подозрительные: list[str] = []
    шаблон = r"""["'`]\s*(select\s+(?!1\b)|insert\s+into|update\s+\w+\s+set|delete\s+from)"""
    for файл in _файлы_слоя("api"):
        if файл.stem.startswith("health"):
            continue
        if re.search(шаблон, файл.read_text(encoding="utf-8"), re.IGNORECASE):
            подозрительные.append(str(файл.relative_to(APP.parent)))
    assert not подозрительные, (
        "Сырой SQL в слое api — доступ к данным нужно вести через репозитории:\n  "
        + "\n  ".join(подозрительные)
    )