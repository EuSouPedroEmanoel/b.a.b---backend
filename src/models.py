from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Table,
    UniqueConstraint,
    case,
    func,
    select,
    text,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    registry,
    relationship,
)

from src.utils.cpf import mask_cpf_last2

table_registry = registry()

# association tables for N:N Book <-> Genre / Author (global)
book_genres = Table(
    'book_genres',
    table_registry.metadata,
    Column(
        'book_id', ForeignKey('books.id', ondelete='CASCADE'), primary_key=True
    ),
    Column(
        'genre_id',
        ForeignKey('genres.id', ondelete='CASCADE'),
        primary_key=True,
    ),
)

book_authors = Table(
    'book_authors',
    table_registry.metadata,
    Column(
        'book_id', ForeignKey('books.id', ondelete='CASCADE'), primary_key=True
    ),
    Column(
        'author_id',
        ForeignKey('authors.id', ondelete='CASCADE'),
        primary_key=True,
    ),
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


class AdministrativeCapability(str, Enum):
    MANAGE_LIBRARY_CALENDAR = 'manage_library_calendar'
    MANAGE_CIRCULATION_RULES = 'manage_circulation_rules'


class LoanStatus(str, Enum):
    ACTIVE = 'active'
    RETURNED = 'returned'
    OVERDUE = 'overdue'


class ReservationStatus(str, Enum):
    ACTIVE = 'active'
    READY = 'ready'
    FULFILLED = 'fulfilled'
    CANCELLED = 'cancelled'
    EXPIRED = 'expired'


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
        CheckConstraint(
            '(cpf_lookup_hash IS NULL) = (cpf_collision_guard IS NULL) '
            'AND (cpf_lookup_hash IS NULL) = (cpf_last2 IS NULL)',
            name='ck_user_cpf_fields_consistent',
        ),
        UniqueConstraint(
            'cpf_lookup_hash',
            'cpf_collision_guard',
            name='uq_users_cpf_lookup_collision_guard',
        ),
    )

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    username: Mapped[str] = mapped_column(unique=True, nullable=False)
    email: Mapped[str] = mapped_column(unique=True, nullable=True)
    cpf_lookup_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary(32), kw_only=True, default=None,
        nullable=True
    )
    cpf_collision_guard: Mapped[bytes | None] = mapped_column(
        LargeBinary(32), kw_only=True, default=None, nullable=True
    )
    cpf_last2: Mapped[str | None] = mapped_column(
        String(2), kw_only=True, default=None, nullable=True
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
    capability_assignments: Mapped[
        list[UserAdministrativeCapability]
    ] = relationship(
        init=False,
        back_populates='user',
        cascade='all, delete-orphan',
        lazy='selectin',
    )

    @property
    def school_name(self) -> str | None:
        return self.school.name if self.school else None

    @property
    def administrative_capabilities(self) -> list[str]:
        return [item.capability for item in self.capability_assignments]

    @property
    def cpf_masked(self) -> str | None:
        return mask_cpf_last2(self.cpf_last2)


@table_registry.mapped_as_dataclass()
class UserAdministrativeCapability:
    __tablename__ = 'user_administrative_capabilities'
    __table_args__ = (
        UniqueConstraint(
            'user_id', 'capability',
            name='uq_user_administrative_capability',
        ),
        CheckConstraint(
            "capability IN ('manage_library_calendar', "
            "'manage_circulation_rules')",
            name='ck_user_administrative_capability_value',
        ),
    )

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'), nullable=False
    )
    capability: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(
        init=False, back_populates='capability_assignments', lazy='selectin'
    )


@table_registry.mapped_as_dataclass()
class SchoolNonWorkingDay:
    __tablename__ = 'school_non_working_days'
    __table_args__ = (
        UniqueConstraint(
            'school_id', 'date', name='uq_school_non_working_day'
        ),
    )

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    school_id: Mapped[int] = mapped_column(
        ForeignKey('schools.id', ondelete='CASCADE'), nullable=False
    )
    date: Mapped[date] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )

    school: Mapped[School] = relationship(init=False, lazy='selectin')


@table_registry.mapped_as_dataclass()
class CirculationPolicy:
    __tablename__ = 'circulation_policies'
    __table_args__ = (
        UniqueConstraint(
            'school_id',
            'reader_role',
            name='uq_circulation_policy_school_role',
        ),
        CheckConstraint(
            "reader_role IN ('student', 'teacher')",
            name='ck_circulation_policy_reader_role',
        ),
        CheckConstraint(
            'max_active_loans >= 0',
            name='ck_circulation_policy_max_active_loans',
        ),
        CheckConstraint(
            'loan_duration_days >= 1',
            name='ck_circulation_policy_loan_duration_days',
        ),
        CheckConstraint(
            'max_renewals >= 0',
            name='ck_circulation_policy_max_renewals',
        ),
        CheckConstraint(
            'max_active_reservations >= 0',
            name='ck_circulation_policy_max_active_reservations',
        ),
        CheckConstraint(
            'post_overdue_suspension_days >= 0',
            name='ck_circulation_policy_post_overdue_suspension_days',
        ),
        CheckConstraint(
            'overdue_due_date_reduction_days >= 0',
            name='ck_circulation_policy_overdue_reduction_days',
        ),
        CheckConstraint(
            'max_overdue_reductions >= 0',
            name='ck_circulation_policy_max_overdue_reductions',
        ),
        CheckConstraint(
            'minimum_loan_days_after_penalties >= 1',
            name='ck_circulation_policy_minimum_penalty_days',
        ),
        CheckConstraint(
            "overdue_recovery_mode IN ('on_time_returns', 'elapsed_days')",
            name='ck_circulation_policy_recovery_mode',
        ),
        CheckConstraint(
            'overdue_recovery_on_time_returns IS NULL OR '
            'overdue_recovery_on_time_returns >= 1',
            name='ck_circulation_policy_recovery_returns',
        ),
        CheckConstraint(
            'overdue_recovery_days IS NULL OR overdue_recovery_days >= 1',
            name='ck_circulation_policy_recovery_days',
        ),
    )

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'))
    reader_role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    max_active_loans: Mapped[int] = mapped_column(nullable=False)
    loan_duration_days: Mapped[int] = mapped_column(nullable=False)
    max_active_reservations: Mapped[int] = mapped_column(nullable=False)
    max_renewals: Mapped[int] = mapped_column(default=0, nullable=False)
    can_reserve: Mapped[bool] = mapped_column(default=True, nullable=False)
    block_new_loans_when_overdue: Mapped[bool] = mapped_column(
        default=True, nullable=False
    )
    post_overdue_suspension_days: Mapped[int] = mapped_column(
        default=0, nullable=False
    )
    count_only_business_days: Mapped[bool] = mapped_column(
        default=False, nullable=False
    )
    move_due_date_to_next_business_day: Mapped[bool] = mapped_column(
        default=False, nullable=False
    )
    apply_overdue_due_date_reduction: Mapped[bool] = mapped_column(
        default=True, nullable=False
    )
    overdue_due_date_reduction_days: Mapped[int] = mapped_column(
        default=1, nullable=False
    )
    max_overdue_reductions: Mapped[int] = mapped_column(
        default=14, nullable=False
    )
    minimum_loan_days_after_penalties: Mapped[int] = mapped_column(
        default=1, nullable=False
    )
    overdue_recovery_mode: Mapped[str] = mapped_column(
        default='on_time_returns', nullable=False
    )
    overdue_recovery_on_time_returns: Mapped[int | None] = mapped_column(
        default=3, nullable=True
    )
    overdue_recovery_days: Mapped[int | None] = mapped_column(
        default=None, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now(), onupdate=func.now()
    )

    school: Mapped[School] = relationship(init=False, lazy='selectin')

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

        Prioridade: AVAILABLE > RESERVED > BORROWED > LOST > ARCHIVED.
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
        reserved = (
            select(func.count(BookCopy.id))
            .where(*cond, BookCopy.state == BooksStates.RESERVED)
            .correlate(Book)
            .scalar_subquery()
        )
        borrowed = (
            select(func.count(BookCopy.id))
            .where(*cond, BookCopy.state == BooksStates.BORROWED)
            .correlate(Book)
            .scalar_subquery()
        )
        lost = (
            select(func.count(BookCopy.id))
            .where(*cond, BookCopy.state == BooksStates.LOST)
            .correlate(Book)
            .scalar_subquery()
        )
        return case(
            (avail > 0, BooksStates.AVAILABLE),
            (reserved > 0, BooksStates.RESERVED),
            (borrowed > 0, BooksStates.BORROWED),
            (lost > 0, BooksStates.LOST),
            else_=BooksStates.ARCHIVED,
        )

    @hybrid_property  # pragma: no cover
    def derived_state(self) -> BooksStates:  # pragma: no cover
        if not self.copies:  # pragma: no cover
            return BooksStates.ARCHIVED  # pragma: no cover
        states = {c.state for c in self.copies}  # pragma: no cover
        if BooksStates.AVAILABLE in states:  # pragma: no cover
            return BooksStates.AVAILABLE  # pragma: no cover
        if BooksStates.RESERVED in states:  # pragma: no cover
            return BooksStates.RESERVED  # pragma: no cover
        if BooksStates.BORROWED in states:  # pragma: no cover
            return BooksStates.BORROWED  # pragma: no cover
        if BooksStates.LOST in states:  # pragma: no cover
            return BooksStates.LOST  # pragma: no cover
        return BooksStates.ARCHIVED  # pragma: no cover


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

    @property
    def internal_code(self) -> str:
        return self.copy.code

    @property
    def book_title(self) -> str:
        return self.copy.book.title

    @property
    def book_id(self) -> int:
        return self.copy.book_id

    @property
    def book_cover_url(self) -> str | None:
        return self.copy.book.cover_url

    @property
    def borrower_username(self) -> str:
        return self.borrower.username

    @property
    def borrower_cpf_masked(self) -> str | None:
        return self.borrower.cpf_masked


@table_registry.mapped_as_dataclass()
class Reservation:
    __tablename__ = 'reservations'
    __table_args__ = (
        Index(
            'uq_reservations_active_user_book_school',
            'user_id',
            'book_id',
            'school_id',
            unique=True,
            postgresql_where=text("status IN ('active', 'ready')"),
        ),
    )

    id: Mapped[int] = mapped_column(
        init=False, primary_key=True, autoincrement=True
    )
    book_id: Mapped[int] = mapped_column(ForeignKey('books.id'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    school_id: Mapped[int] = mapped_column(ForeignKey('schools.id'))
    copy_id: Mapped[int | None] = mapped_column(
        ForeignKey('book_copies.id'), kw_only=True, default=None, nullable=True
    )
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
    ready_at: Mapped[datetime | None] = mapped_column(
        kw_only=True, default=None, nullable=True
    )
    pickup_expires_at: Mapped[datetime | None] = mapped_column(
        kw_only=True, default=None, nullable=True
    )

    book: Mapped[Book] = relationship(init=False, lazy='selectin')
    reserver: Mapped[User] = relationship(
        init=False, foreign_keys='Reservation.user_id', lazy='selectin'
    )
    school: Mapped[School] = relationship(init=False, lazy='selectin')
    copy: Mapped[BookCopy | None] = relationship(
        init=False, foreign_keys='Reservation.copy_id', lazy='selectin'
    )


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
