from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import ClassVar

from sqlalchemy import CheckConstraint, ForeignKey, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    registry,
    relationship,
)

table_registry = registry()


class BooksStates(str, Enum):
    AVAILABLE = 'available'  # Disponível na estante/acervo
    BORROWED = 'borrowed'  # Emprestado
    RESERVED = 'reserved'  # Reservado
    LOST = 'lost'  # Perdido
    ARCHIVED = 'archived'  # Arquivado / Doado


@table_registry.mapped_as_dataclass()
class User:
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    username: Mapped[str] = mapped_column(unique=True, nullable=False)
    email: Mapped[str] = mapped_column(unique=True, nullable=True)
    password: Mapped[str] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now(), onupdate=func.now()
    )

    books: Mapped[list[Book]] = relationship(
        init=False,
        back_populates='user',
        cascade='all, delete-orphan',
        lazy='selectin',
    )


@table_registry.mapped_as_dataclass()
class Book:
    __tablename__ = 'books'
    __table_args__: ClassVar = (
        CheckConstraint(
            'isbn IS NOT NULL OR internal_code IS NOT NULL',
            name='check_isbn_or_internal_code_present',
        ),
    )

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    title: Mapped[str]
    description: Mapped[str]

    state: Mapped[BooksStates] = mapped_column(
        SQLEnum(BooksStates, values_callable=lambda x: [e.value for e in x])
    )
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))

    isbn: Mapped[str | None] = mapped_column(default=None, nullable=True)
    internal_code: Mapped[str | None] = mapped_column(
        default=None, unique=True, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(init=False, back_populates='books')
