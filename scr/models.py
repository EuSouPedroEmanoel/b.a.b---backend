from __future__ import annotations

from datetime import date, datetime
from enum import Enum

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


class BookCondition(str, Enum):
    NEW = 'new'  # 1. Novo (Zero uso, lacrado ou de livraria)
    GOOD = 'good'  # 2. Bom (Seminovo, lido mas muito bem conservado)
    FAIR = 'fair'  # 3. Regular (Usado normal, páginas amareladas, grifos)
    POOR = 'poor'  # 4. Ruim (Desgastado, capas/páginas rasgadas ou soltas)
    BAD = 'bad'  # 5. Péssimo / Inutilizável (Faltando páginas, mofo, água)


class UserRole(str, Enum):
    SUPER_ADMIN = 'super_admin'
    SCHOOL_ADMIN = 'school_admin'
    LIBRARIAN = 'librarian'
    TEACHER = 'teacher'
    STUDENT = 'student'


@table_registry.mapped_as_dataclass()
class School:
    __tablename__ = 'schools'

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now(), onupdate=func.now()
    )

    users: Mapped[list[User]] = relationship(
        init=False,
        back_populates='school',
        cascade='all, delete-orphan',
        lazy='selectin',
    )


@table_registry.mapped_as_dataclass()
class User:
    __tablename__ = 'users'
    __table_args__ = (
        CheckConstraint(
            "(role = 'super_admin') OR (school_id IS NOT NULL)",
            name='ck_user_school_required',
        ),
    )

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    username: Mapped[str] = mapped_column(unique=True, nullable=False)
    email: Mapped[str] = mapped_column(unique=True, nullable=True)
    password: Mapped[str] = mapped_column(nullable=True)
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole, values_callable=lambda x: [e.value for e in x]),
        kw_only=True,
        default=UserRole.LIBRARIAN,
        nullable=False,
    )
    school_id: Mapped[int | None] = mapped_column(
        ForeignKey('schools.id'), kw_only=True, default=None, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now(), onupdate=func.now()
    )

    school: Mapped[School | None] = relationship(
        init=False, back_populates='users', lazy='selectin'
    )
    books: Mapped[list[Book]] = relationship(
        init=False,
        back_populates='user',
        cascade='all, delete-orphan',
        lazy='selectin',
    )
    copies: Mapped[list[BookCopy]] = relationship(
        init=False,
        back_populates='user',
        cascade='all, delete-orphan',
        lazy='selectin',
    )


@table_registry.mapped_as_dataclass()
class Book:
    __tablename__ = 'books'
    __table_args__ = (
        CheckConstraint(
            '(isbn IS NOT NULL) OR (internal_code IS NOT NULL)',
            name='check_isbn_or_internal_code_present',
        ),
    )

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    title: Mapped[str]
    description: Mapped[str | None] = mapped_column(kw_only=True, default=None)

    state: Mapped[BooksStates] = mapped_column(
        SQLEnum(BooksStates, values_callable=lambda x: [e.value for e in x]),
        kw_only=True,
        default=BooksStates.AVAILABLE,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))

    isbn: Mapped[str | None] = mapped_column(
        kw_only=True, default=None, unique=True
    )
    internal_code: Mapped[str | None] = mapped_column(
        kw_only=True, default=None, unique=True
    )

    created_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(init=False, back_populates='books')
    copies: Mapped[list[BookCopy]] = relationship(
        init=False,
        back_populates='book',
        cascade='all, delete-orphan',
        lazy='selectin',
    )


@table_registry.mapped_as_dataclass()
class BookCopy:
    __tablename__ = 'book_copies'

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    internal_code: Mapped[str] = mapped_column(unique=True, nullable=False)

    state: Mapped[BooksStates] = mapped_column(
        SQLEnum(BooksStates, values_callable=lambda x: [e.value for e in x]),
        kw_only=True,
        default=BooksStates.AVAILABLE,
    )
    condition: Mapped[BookCondition] = mapped_column(
        SQLEnum(BookCondition, values_callable=lambda x: [e.value for e in x]),
        kw_only=True,
        default=BookCondition.GOOD,
    )

    book_id: Mapped[int] = mapped_column(ForeignKey('books.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'))

    acquisition_date: Mapped[date | None] = mapped_column(
        kw_only=True, default=None
    )
    notes: Mapped[str | None] = mapped_column(kw_only=True, default=None)

    created_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now(), onupdate=func.now()
    )

    book: Mapped[Book] = relationship(init=False, back_populates='copies')
    user: Mapped[User] = relationship(init=False, back_populates='copies')
    school: Mapped[School] = relationship(init=False, lazy='selectin')
