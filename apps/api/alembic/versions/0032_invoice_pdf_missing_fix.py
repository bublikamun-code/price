"""Починка состояния PDF счетов и КП: «READY без файла» → FAILED.

UI-аудит 2026-11-15, находка H1 (docs/UI_AUDIT_REPORT_2026-11-15.md).

**Суть.** FK ``invoices.pdf_file_asset_id`` и ``quotes.pdf_file_asset_id``
объявлены с ``ON DELETE SET NULL``. Удаление PDF счёта из файлового архива
(``DELETE /api/v1/manager/files/{id}``) удаляло строку ``file_assets`` → ссылка
обнулялась, а ``pdf_status`` оставался ``READY``. В UI это выглядело как
зелёный бейдж «PDF: Готов» и активная кнопка «Скачать счёт», а сервер отдавал
``409 INVOICE_PDF_NOT_READY``; перерендерить было нельзя (кнопка рендера
существует только для ``FAILED``).

Исправление — в двух частях:

* **Данные (эта миграция).** Документы в состоянии «READY без файла» переводятся
  в ``FAILED`` — UI показывает «Перерендерить PDF», и документ можно восстановить.
* **Код** (``services/file_assets.py``): при удалении ассета сам счёт/КП
  переводится в ``FAILED`` в той же транзакции, поэтому новые «битые» записи
  не появляются.

Канон: §16 п.40, решение (10); §16 п.18; §6 «Счета на оплату».
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0032_invoice_pdf_missing_fix"
down_revision: str | None = "0031_two_factor_challenge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Счёт: PDF помечен готовым, но файла нет — счёт нерабочий.
    op.execute(
        """
        UPDATE invoices
           SET pdf_status = 'FAILED'
         WHERE pdf_status = 'READY'
           AND pdf_file_asset_id IS NULL
        """
    )
    # КП — тот же механизм (FK на file_assets тоже SET NULL).
    op.execute(
        """
        UPDATE quotes
           SET pdf_status = 'FAILED'
         WHERE pdf_status = 'READY'
           AND pdf_file_asset_id IS NULL
        """
    )


def downgrade() -> None:
    """Откат данных не выполняется осознанно.

    Вернуть ``FAILED`` → ``READY`` означало бы снова показать кнопку «Скачать
    счёт» у документа без файла — ровно тот дефект, который чинится. Откат
    возможен точечно вручную по списку затронутых id.
    """
    return None
