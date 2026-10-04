"""Продовые инварианты безопасности должны проверяться на старте.

Регрессия: в prod-оверлее `docker-compose.prod.yml` не было `ENV: prod`.
Без него `_check_prod_security()` выходит на первой строке (`if self.env != "prod"`)
и весь guard остаётся мёртвым кодом: прод поднимался с дефолтным SECRET_KEY,
HS256 и CORS на localhost, молча минуя все проверки.

Проверяем поведением: в prod плохие настройки обязаны падать.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

def _корень_репозитория() -> Path | None:
    """Ищем каталог с infra/ вверх по дереву.

    Глубина от теста до корня разная: на хосте это apps/api/tests, в контейнере
    тесты лежат ближе к корню, и жёсткий parents[3] там просто не существует.
    """
    for родитель in Path(__file__).resolve().parents:
        if (родитель / "infra" / "docker-compose.prod.yml").is_file():
            return родитель
    return None

# Прод-guard ТРЕБУЕТ RS256 (это и было исходным намерением: только асимметричная
# подпись, §16 п.15). Поэтому «валидный» прод — это RS256 с настоящей парой ключей.
GOOD = {
    "cookie_secure": True,
    "cors_origins": "https://portal.example.com",
}


@pytest.fixture(scope="module")
def пара_ключей(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """RS256 проверяет, что файлы ключей читаются, — поднимаем настоящие."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    каталог = tmp_path_factory.mktemp("jwt")
    ключ = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    приватный = каталог / "jwt_rsa.key"
    публичный = каталог / "jwt_rsa.pub"
    приватный.write_bytes(
        ключ.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    публичный.write_bytes(
        ключ.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return {"jwt_private_key_path": str(приватный), "jwt_public_key_path": str(публичный)}


def _prod(пара_ключей: dict[str, str], **overrides: object) -> Settings:
    """Прод-конфигурация на валидной базе; overrides доводят её до проверяемого состояния.

    Собираем одним словарём, а не цепочкой **: иначе переопределение ключа,
    который уже есть в базе (например secret_key), даёт TypeError вместо
    проверки настроек — тест падал бы на своём баге, а не на проверяемом.
    """
    return Settings(**{
        "env": "prod",
        "secret_key": "k" * 40,
        "jwt_algorithm": "RS256",
        **GOOD,
        **пара_ключей,
        **overrides,
    })


def test_корректные_прод_настройки_принимаются(пара_ключей: dict[str, str]) -> None:
    """Базовая линия: конфигурация из docker-compose.prod.yml валидна и поднимается.

    Без неё проверки ниже ничего не значат — они поймали бы любую поломку.
    """
    assert _prod(пара_ключей).jwt_algorithm == "RS256"


@pytest.mark.parametrize(
    ("настройка", "значение"),
    [
        ("secret_key", "change-me-to-a-long-random-string"),  # дефолт из .env.example
        ("secret_key", "k" * 31),                              # короче 32 символов
        ("jwt_algorithm", "HS256"),
        ("cookie_secure", False),
        ("cors_origins", "https://localhost:3000"),
        ("cors_origins", "http://127.0.0.1:8081"),
    ],
)
def test_плохие_прод_настройки_отвергаются(
    пара_ключей: dict[str, str], настройка: str, значение: object
) -> None:
    """Каждый нарушенный инвариант обязан валить старт, а не писать в лог."""
    with pytest.raises(ValidationError):
        _prod(пара_ключей, **{настройка: значение})


def test_rs256_без_файлов_ключей_отвергается() -> None:
    """Ключи обязательны: без них токены нечем подписывать."""
    with pytest.raises(ValidationError):
        Settings(env="prod", secret_key="k" * 40, jwt_algorithm="RS256",
                 cookie_secure=True, cors_origins="https://portal.example.com")


def test_в_dev_эти_проверки_не_применяются() -> None:
    """Dev и staging работают на дефолтах — guard не должен им мешать."""
    assert Settings(env="dev", secret_key="x" * 32).env == "dev"
    assert Settings(env="staging", secret_key="x" * 32).env == "staging"


def test_в_прод_оверлее_задан_ENV_prod() -> None:
    """Страховка от повторения регрессии: без ENV=prod guard не включается.

    Проверяем сам compose-файл — опечатка в нём тихо обнуляла всю защиту,
    и ни один тест кода этого не заметил бы.
    """
    корень = _корень_репозитория()
    if корень is None:  # тесты запущены вне репозитория (образ без infra/)
        pytest.skip("infra/docker-compose.prod.yml недоступен в этом окружении")
    блок_api = (корень / "infra" / "docker-compose.prod.yml").read_text(
        encoding="utf-8"
    ).split("\n  api:", 1)[1]
    assert "ENV: prod" in блок_api.split("\n  [a-z_]*:", 1)[0], (
        "В prod-оверлее нет `ENV: prod` — _check_prod_security() не выполнится, "
        "прод поднимется с дефолтными секретами."
    )