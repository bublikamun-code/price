"""Шаблоны писем (services/email): заказы менеджеру/клиенту, сброс пароля.

Проверяем не вёрстку, а содержимое: ключевые строки (номер заказа, сумма,
статус, способ получения), ссылка на кабинет и отсутствие заглушек/внешних
ресурсов (инлайн-CSS, письма должны читаться в почтовом клиенте офлайн).
"""
import pytest

import app.services.email as email_service


HTML_ORDER_NO = "#000123"


@pytest.fixture
def manager_email():
    return email_service.build_order_created_manager_email(
        order_no=HTML_ORDER_NO,
        client_name="Иван Петров",
        client_company='ООО «Ромашка»',
        total_amount=1234.5,
        currency_code="BYN",
        delivery_method="pickup",
        items_count=7,
    )


# =========================================================
# Письмо менеджеру о новой заявке
# =========================================================
def test_order_created_subject_and_number(manager_email):
    subject, html = manager_email
    assert subject == f"Новый заказ {HTML_ORDER_NO}"
    assert HTML_ORDER_NO in html


def test_order_created_carries_summary_fields(manager_email):
    _, html = email_service.build_order_created_manager_email(
        order_no=HTML_ORDER_NO,
        client_name="Иван Петров",
        client_company='ООО «Ромашка»',
        total_amount=1234.5,
        currency_code="BYN",
        delivery_method="pickup",
        items_count=7,
    )
    assert 'ООО «Ромашка» (Иван Петров)' in html
    assert "1234.50 BYN" in html  # формат суммы как в выгрузках
    assert "Самовывоз" in html  # DELIVERY_METHOD_RU
    assert "Позиций" in html and "7" in html


def test_order_created_link_to_manager_cabinet(manager_email):
    _, html = manager_email
    assert 'href="/manager/orders"' in html
    assert "/manager/orders" in html  # и в дубле-тексте для копирования


def test_order_created_delivery_unknown_value_falls_back():
    _, html = email_service.build_order_created_manager_email(
        order_no=HTML_ORDER_NO,
        client_name=None,
        client_company=None,
        total_amount=0,
        currency_code="BYN",
        delivery_method="courier",
        items_count=1,
    )
    assert "courier" in html  # неизвестный способ не теряем


def test_order_created_no_stub_no_external_resources(manager_email):
    _, html = manager_email
    assert "Заглушка" not in html
    assert "<img" not in html and "src=" not in html  # без внешних ресурсов


# =========================================================
# Письмо клиенту о смене статуса
# =========================================================
def test_status_changed_subject_and_status():
    subject, html = email_service.build_order_status_changed_email(
        HTML_ORDER_NO, "Отгружена"
    )
    assert subject == f"Заказ {HTML_ORDER_NO}: статус обновлён"
    assert HTML_ORDER_NO in html
    assert "Отгружена" in html


def test_status_changed_link_to_client_cabinet():
    _, html = email_service.build_order_status_changed_email(
        HTML_ORDER_NO, "Выполнена"
    )
    assert 'href="/orders"' in html
    assert "Заглушка" not in html


# =========================================================
# Ссылка на кабинет: web_app_url → абсолютная, пусто → относительная
# =========================================================
def test_links_use_web_app_url_when_set(monkeypatch):
    monkeypatch.setattr(email_service.settings, "web_app_url", "https://portal.example.by/")
    _, status_html = email_service.build_order_status_changed_email(
        HTML_ORDER_NO, "Новая"
    )
    _, manager_html = email_service.build_order_created_manager_email(
        order_no=HTML_ORDER_NO,
        client_name=None,
        client_company=None,
        total_amount=10,
        currency_code="BYN",
        delivery_method=None,
        items_count=1,
    )
    assert 'href="https://portal.example.by/orders"' in status_html
    assert 'href="https://portal.example.by/manager/orders"' in manager_html


def test_links_stay_relative_without_web_app_url(monkeypatch):
    monkeypatch.setattr(email_service.settings, "web_app_url", "")
    _, html = email_service.build_order_status_changed_email(HTML_ORDER_NO, "Новая")
    assert 'href="/orders"' in html
    assert "https://" not in html  # dev: абсолютного домена нет — не выдумываем


# =========================================================
# Базовый каркас: инлайн-стили у обоих писем заказа
# =========================================================
def test_order_emails_share_layout_with_inline_css(manager_email):
    _, manager_html = manager_email
    _, status_html = email_service.build_order_status_changed_email(
        HTML_ORDER_NO, "Новая"
    )
    for html in (manager_html, status_html):
        assert "style=" in html  # инлайн-CSS: <style> почтовики вырезают
        # Токены витрины (apps/web/assets/css/main.css) — письма в фирменном стиле.
        assert "#fffdf8" in html and "#1b2a24" in html
