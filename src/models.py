from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    String,
    Table,
    UniqueConstraint,
    case,
    func,
    select,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    registry,
    relationship,
)

table_registry = registry()

# association tables for N:N Book <-> Genre / Author (global)
book_genres = Table(
    'book_genres',
    table_registry.metadata,
    Column('book_id', ForeignKey('books.id', ondelete='CASCADE'), primary_key=True),
    Column('genre_id', ForeignKey('genres.id', ondelete='CASCADE'), primary_key=True),
)

book_authors = Table(
    'book_authors',
    table_registry.metadata,
    Column('book_id', ForeignKey('books.id', ondelete='CASCADE'), primary_key=True),
    Column('author_id', ForeignKey('authors.id', ondelete='CASCADE'), primary_key=True),
)


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


class LoanStatus(str, Enum):
    ACTIVE = 'active'
    RETURNED = 'returned'
    OVERDUE = 'overdue'


class ReservationStatus(str, Enum):
    ACTIVE = 'active'
    FULFILLED = 'fulfilled'
    CANCELLED = 'cancelled'


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
    cpf: Mapped[str | None] = mapped_column(
        unique=True, kw_only=True, default=None, nullable=True
    )
    birthdate: Mapped[date | None] = mapped_column(
        kw_only=True, default=None, nullable=True
    )
    turma_numero: Mapped[int | None] = mapped_column(
        kw_only=True, default=None, nullable=True
    )
    turma_letra: Mapped[str | None] = mapped_column(
        kw_only=True, default=None, nullable=True
    )
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
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
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
        foreign_keys='Book.added_by',
    )
    copies: Mapped[list[BookCopy]] = relationship(
        init=False,
        back_populates='user',
        cascade='all, delete-orphan',
        lazy='selectin',
        foreign_keys='BookCopy.added_by',
    )

    @property
    def school_name(self) -> str | None:
        return self.school.name if self.school else None

    @property
    def school_code(self) -> str | None:
        return self.school.code if self.school else None


@table_registry.mapped_as_dataclass()
class Genre:
    __tablename__ = 'genres'

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now(), onupdate=func.now()
    )

    books: Mapped[list[Book]] = relationship(
        init=False,
        secondary=book_genres,
        back_populates='genres',
        lazy='selectin',
    )


@table_registry.mapped_as_dataclass()
class Author:
    __tablename__ = 'authors'

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now(), onupdate=func.now()
    )

    books: Mapped[list[Book]] = relationship(
        init=False,
        secondary=book_authors,
        back_populates='authors',
        lazy='selectin',
    )


@table_registry.mapped_as_dataclass()
class Book:
    __tablename__ = 'books'

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    title: Mapped[str]
    description: Mapped[str | None] = mapped_column(kw_only=True, default=None)

    added_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    edited_by: Mapped[int | None] = mapped_column(
        ForeignKey('users.id'), kw_only=True, default=None, nullable=True
    )

    isbn: Mapped[str | None] = mapped_column(
        kw_only=True, default=None, unique=True
    )
    cover_url: Mapped[str | None] = mapped_column(
        kw_only=True, default=None, nullable=True
    )
    published_date: Mapped[date | None] = mapped_column(
        kw_only=True, default=None, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now(), onupdate=func.now()
    )

    edited_user: Mapped[User | None] = relationship(
        init=False, foreign_keys='Book.edited_by', lazy='selectin'
    )
    user: Mapped[User] = relationship(  # noqa: E501
        init=False,
        foreign_keys='Book.added_by',
        back_populates='books',
        lazy='selectin',
    )
    copies: Mapped[list[BookCopy]] = relationship(
        init=False,
        back_populates='book',
        cascade='all, delete-orphan',
        lazy='selectin',
    )
    genres: Mapped[list[Genre]] = relationship(
        init=False,
        secondary=book_genres,
        back_populates='books',
        lazy='selectin',
    )
    authors: Mapped[list[Author]] = relationship(
        init=False,
        secondary=book_authors,
        back_populates='books',
        lazy='selectin',
    )

    @staticmethod
    def derived_state_expr(school_id: int | None = None):
        """SQL expression for the derived state, scoped to a school.

        Priority borrowed > available: available if any copy is available;
        borrowed if there are copies but none available; archived if no copies.
        """
        cond = [BookCopy.book_id == Book.id]
        if school_id is not None:
            cond.append(BookCopy.school_id == school_id)
        avail = (
            select(func.count(BookCopy.id))
            .where(*cond, BookCopy.state == BooksStates.AVAILABLE)
            .correlate(Book)
            .scalar_subquery()
        )
        other = (
            select(func.count(BookCopy.id))
            .where(*cond, BookCopy.state != BooksStates.AVAILABLE)
            .correlate(Book)
            .scalar_subquery()
        )
        return case(
            (avail > 0, BooksStates.AVAILABLE),
            (other > 0, BooksStates.BORROWED),
            else_=BooksStates.ARCHIVED,
        )

    @hybrid_property
    def derived_state(self) -> BooksStates:
        if not self.copies:
            return BooksStates.ARCHIVED
        if any(c.state == BooksStates.AVAILABLE for c in self.copies):
            return BooksStates.AVAILABLE
        return BooksStates.BORROWED


@table_registry.mapped_as_dataclass()
class BookCopy:
    __tablename__ = 'book_copies'
    __table_args__ = (
        UniqueConstraint('school_id', 'code', name='uq_school_copy_code'),
    )

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    code: Mapped[str] = mapped_column(nullable=False)

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
    added_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    edited_by: Mapped[int | None] = mapped_column(
        ForeignKey('users.id'), kw_only=True, default=None, nullable=True
    )
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
    edited_user: Mapped[User | None] = relationship(
        init=False, foreign_keys='BookCopy.edited_by', lazy='selectin'
    )
    # legacy alias keeps User.copies working
    user: Mapped[User] = relationship(  # noqa: E501
        init=False,
        foreign_keys='BookCopy.added_by',
        back_populates='copies',
        lazy='selectin',
    )
    school: Mapped[School] = relationship(init=False, lazy='selectin')


@table_registry.mapped_as_dataclass()
class Loan:
    __tablename__ = 'loans'

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    copy_id: Mapped[int] = mapped_column(ForeignKey('book_copies.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'))
    borrowed_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    due_date: Mapped[datetime] = mapped_column(nullable=False)
    returned_at: Mapped[datetime | None] = mapped_column(
        kw_only=True, default=None, nullable=True
    )
    late_days: Mapped[int] = mapped_column(default=0, nullable=False)
    status: Mapped[LoanStatus] = mapped_column(
        SQLEnum(LoanStatus, values_callable=lambda x: [e.value for e in x]),
        kw_only=True,
        default=LoanStatus.ACTIVE,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now(), onupdate=func.now()
    )

    copy: Mapped[BookCopy] = relationship(init=False, lazy='selectin')
    borrower: Mapped[User] = relationship(
        init=False, foreign_keys='Loan.user_id', lazy='selectin'
    )
    school: Mapped[School] = relationship(init=False, lazy='selectin')


@table_registry.mapped_as_dataclass()
class Reservation:
    __tablename__ = 'reservations'

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    book_id: Mapped[int] = mapped_column(ForeignKey('books.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'))
    status: Mapped[ReservationStatus] = mapped_column(
        SQLEnum(
            ReservationStatus, values_callable=lambda x: [e.value for e in x]
        ),
        kw_only=True,
        default=ReservationStatus.ACTIVE,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now(), onupdate=func.now()
    )

    book: Mapped[Book] = relationship(init=False, lazy='selectin')
    reserver: Mapped[User] = relationship(
        init=False, foreign_keys='Reservation.user_id', lazy='selectin'
    )
    school: Mapped[School] = relationship(init=False, lazy='selectin')


@table_registry.mapped_as_dataclass()
class RevokedToken:
    __tablename__ = 'revoked_tokens'

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    jti: Mapped[str] = mapped_column(unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
