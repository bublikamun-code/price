"""Одноразовый 2FA-ticket, счётчик TOTP-шага и режим cookie «Запомнить меня».

Аудит 2026-11-10, находки M9 и L9.

**M9 — ticket второго шага логина не гасился.** Ticket (JWT с type="2fa",
TTL 5 минут) жил только в JWT: за окно его можно было предъявить несколько
раз и получить несколько сессий. Теперь каждый ticket при выдаче
регистрируется в ``two_factor_challenges``, а при verify гасится атомарно
(``UPDATE ... WHERE used_at IS NULL`` + проверка rowcount).

Там же — защита от повторного TOTP: ``users.totp_last_step`` хранит номер
time-step'а последнего принятого кода; шаг, равный или меньший уже
использованного, отклоняется (окно ±30 секунд перестаёт быть «многоразовым»).

**L9 — режим cookie «Запомнить меня».** ``sessions.remember`` запоминает
выбор клиента: true → постоянные cookie (Max-Age), false → сессионные.
Значение переносится в новую сессию при ротации refresh-токена.

Существующие сессии получают remember=true — это прежнее поведение API
(постоянные cookie), поэтому миграция ничего не ломает.

ORM-декларация — ``app/models/user.py`` (metadata → create_all в тестах).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_two_factor_challenge"
down_revision: str | Sequence[str] | None = "0030_photo_key_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Реестр вызовов 2FA: одноразовый ticket.
    op.create_table(
        "two_factor_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        # Идентификатор вызова (claim "jti" в JWT-ticket) — UNIQUE.
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=False
        ),
        # NULL → ticket ещё не использован; выставляется при успешном verify.
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_two_factor_challenges_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_two_factor_challenges"),
        sa.UniqueConstraint("jti", name="uq_two_factor_challenges_jti"),
    )
    op.create_index(
        "ix_two_factor_challenges_user_id",
        "two_factor_challenges",
        ["user_id"],
        unique=False,
    )

    # 2) Счётчик принятого TOTP-шага (аудит M9).
    op.add_column(
        "users",
        sa.Column("totp_last_step", sa.Integer(), nullable=True),
    )

    # 3) Режим cookie «Запомнить меня» (аудит L9).
    op.add_column(
        "sessions",
        sa.Column(
            "remember",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "remember")
    op.drop_column("users", "totp_last_step")
    op.drop_index(
        "ix_two_factor_challenges_user_id", table_name="two_factor_challenges"
    )
    op.drop_table("two_factor_challenges")
