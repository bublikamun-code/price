"""Тесты JWT RS256 (§16 п.15): PEM-ключи из файлов + валидация конфига.

Dev-режим HS256+SECRET_KEY покрывается test_auth.py (без правок); здесь:
  - RS256 roundtrip (access/refresh) через settings.jwt_signing_key/jwt_verify_key
  - проверка подписи чужим публичным ключом → JWTError
  - кэш PEM по пути (файл читается один раз)
  - валидация Settings: RS256 без путей / с нечитаемыми файлами → ошибка старта
  - HS256 с заданными путями → warning, файлы не используются
"""
import logging
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import JWTError, jwt
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.security import create_access_token, create_refresh_token, decode_token


# ---------- helpers ----------
def _write_rsa_pair(directory: Path) -> tuple[Path, Path]:
    """Генерирует эфемерную RSA-пару (2048) и пишет PEM-файлы (private, public)."""
    directory.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = directory / "jwt_rsa.key"
    private.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public = directory / "jwt_rsa.pub"
    public.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private, public


@pytest.fixture
def rs256_keys(tmp_path, monkeypatch):
    """Переключает глобальный settings на RS256 с эфемерной парой ключей.

    security.py импортирует тот же singleton → encode/decode идут через PEM.
    """
    private, public = _write_rsa_pair(tmp_path / "keys")
    monkeypatch.setattr(settings, "jwt_algorithm", "RS256")
    monkeypatch.setattr(settings, "jwt_private_key_path", str(private))
    monkeypatch.setattr(settings, "jwt_public_key_path", str(public))
    return private, public


# =========================================================
# RS256 roundtrip
# =========================================================
def test_rs256_access_token_roundtrip(rs256_keys):
    token = create_access_token("user-1")
    assert jwt.get_unverified_header(token)["alg"] == "RS256"
    payload = decode_token(token)
    assert payload["sub"] == "user-1"
    assert payload["type"] == "access"


def test_rs256_refresh_token_roundtrip(rs256_keys):
    payload = decode_token(create_refresh_token("user-2"))
    assert payload["sub"] == "user-2"
    assert payload["type"] == "refresh"


def test_rs256_foreign_public_key_rejected(tmp_path, monkeypatch):
    """Подпись одной парой, проверка публичным ключом другой → JWTError."""
    private, _ = _write_rsa_pair(tmp_path / "mine")
    _, foreign_pub = _write_rsa_pair(tmp_path / "foreign")
    monkeypatch.setattr(settings, "jwt_algorithm", "RS256")
    monkeypatch.setattr(settings, "jwt_private_key_path", str(private))
    monkeypatch.setattr(settings, "jwt_public_key_path", str(foreign_pub))
    token = create_access_token("user-1")
    with pytest.raises(JWTError):
        decode_token(token)


def test_rs256_key_properties_return_pem(rs256_keys):
    private, public = rs256_keys
    assert settings.jwt_signing_key == private.read_text()
    assert settings.jwt_verify_key == public.read_text()
    assert "PRIVATE KEY" in settings.jwt_signing_key
    assert settings.jwt_verify_key.startswith("-----BEGIN PUBLIC KEY-----")


def test_rs256_pem_cached_by_path(rs256_keys):
    """Ключ читается с диска один раз: после удаления файлов работает кэш."""
    private, public = rs256_keys
    assert settings.jwt_signing_key and settings.jwt_verify_key  # прогрев кэша
    private.unlink()
    public.unlink()
    assert settings.jwt_signing_key.startswith("-----BEGIN")
    assert settings.jwt_verify_key.startswith("-----BEGIN")


# =========================================================
# Валидация конфига
# =========================================================
def test_rs256_without_paths_rejected():
    with pytest.raises(ValidationError, match="JWT_PRIVATE_KEY_PATH"):
        Settings(jwt_algorithm="RS256")


def test_rs256_missing_files_rejected(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(ValidationError, match="не найден или не читается"):
        Settings(
            jwt_algorithm="RS256",
            jwt_private_key_path=str(missing / "jwt_rsa.key"),
            jwt_public_key_path=str(missing / "jwt_rsa.pub"),
        )


def test_hs256_with_paths_warns_and_ignores_files(tmp_path, caplog):
    private, public = _write_rsa_pair(tmp_path)
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        hs = Settings(
            jwt_algorithm="HS256",
            jwt_private_key_path=str(private),
            jwt_public_key_path=str(public),
        )
    assert "PEM-ключи не используются" in caplog.text
    assert hs.jwt_signing_key == hs.secret_key
    assert hs.jwt_verify_key == hs.secret_key


def test_hs256_default_roundtrip():
    """Без переключения настроек (dev-режим) encode/decode работают как раньше."""
    token = create_access_token("user-3")
    assert jwt.get_unverified_header(token)["alg"] == settings.jwt_algorithm
    assert decode_token(token)["sub"] == "user-3"
