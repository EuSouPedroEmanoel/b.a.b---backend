from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from src.models import (
    BookCondition,
    BooksStates,
    LoanStatus,
    ReservationStatus,
    UserRole,
)
from src.utils.cpf import normalize_cpf, validate_cpf

T = TypeVar('T')


# region - Pagination
class PaginatedMeta(BaseModel):
    total: int
    page: int
    size: int
    pages: int


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int


# endregion
# region - Message
class Message(BaseModel):
    message: str


# region - User
class UserSchema(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserPublic(BaseModel):
    username: str
    email: EmailStr | None = None
    cpf: str | None = None
    birthdate: date | None = None
    turma_numero: int | None = None
    turma_letra: str | None = None
    id: int
    role: UserRole
    school_id: int | None = None
    school_name: str | None = None
    school_code: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class UserDB(UserSchema):
    id: int


class UserList(BaseModel):
    users: list[UserPublic]


class StaffCreateSchema(BaseModel):
    username: str
    email: EmailStr | None = None
    cpf: str
    password: str
    role: UserRole = UserRole.LIBRARIAN
    school_id: int | None = None  # only honored for SUPER_ADMIN

    @model_validator(mode='after')
    def validate_cpf_field(self):
        if not validate_cpf(self.cpf):
            raise ValueError('CPF inválido')
        self.cpf = normalize_cpf(self.cpf)
        return self

    @model_validator(mode='after')
    def validate_staff_role(self):
        allowed = {
            UserRole.LIBRARIAN,
            UserRole.TEACHER,
            UserRole.STUDENT,
        }
        # SCHOOL_ADMIN/SUPER_ADMIN creation via schools/{id}/admins
        if self.role not in allowed:
            raise ValueError(
                f'Role deve ser um de: {", ".join(r.value for r in allowed)}'
            )
        return self


MIN_STUDENT_AGE_YEARS = 4
MAX_STUDENT_AGE_YEARS = 20


def validate_birthdate(dt: date) -> date:
    today = date.today()
    if dt >= today:
        raise ValueError('birthdate deve ser uma data no passado')
    age = today.year - dt.year - (
        (today.month, today.day) < (dt.month, dt.day)
    )
    if not (MIN_STUDENT_AGE_YEARS <= age <= MAX_STUDENT_AGE_YEARS):
        raise ValueError(
            f'birthdate indica idade fora do intervalo permitido '
            f'({MIN_STUDENT_AGE_YEARS}-{MAX_STUDENT_AGE_YEARS} anos)'
        )
    return dt


def initial_student_password(birthdate: date) -> str:
    return birthdate.strftime('%d%m%Y')


class StudentCreateSchema(BaseModel):
    name: str = Field(min_length=1)
    cpf: str
    birthdate: date
    turma_numero: int = Field(ge=1, le=12)
    turma_letra: str = Field(min_length=1, max_length=1)
    password: str | None = Field(default=None, min_length=1)

    @model_validator(mode='after')
    def validate_cpf_field(self):
        if not validate_cpf(self.cpf):
            raise ValueError('CPF inválido')
        self.cpf = normalize_cpf(self.cpf)
        return self

    @model_validator(mode='after')
    def validate_student_fields(self):
        validate_birthdate(self.birthdate)
        return self

    @model_validator(mode='after')
    def default_password_from_birthdate(self):
        if self.password is None:
            self.password = initial_student_password(self.birthdate)
        return self


class SchoolAdminCreateSchema(BaseModel):
    username: str
    email: EmailStr
    cpf: str
    password: str

    @model_validator(mode='after')
    def validate_cpf_field(self):
        if not validate_cpf(self.cpf):
            raise ValueError('CPF inválido')
        self.cpf = normalize_cpf(self.cpf)
        return self


class UserUpdateSelf(BaseModel):
    username: str | None = Field(default=None, min_length=1)
    email: EmailStr | None = None
    cpf: str | None = None
    birthdate: date | None = None
    turma_numero: int | None = Field(default=None, ge=1, le=12)
    turma_letra: str | None = Field(default=None, min_length=1, max_length=1)
    password: str | None = Field(default=None, min_length=1)

    @model_validator(mode='after')
    def validate_student_fields(self):
        if self.birthdate is not None:
            validate_birthdate(self.birthdate)
        if (self.turma_numero is not None) != (self.turma_letra is not None):
            raise ValueError(
                'turma_numero e turma_letra devem ser informados juntos'
            )
        return self


# endregion
# region - Genre
class GenrePublic(BaseModel):
    id: int
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class GenreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


# endregion
# region - Author
class AuthorPublic(BaseModel):
    id: int
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


class AuthorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


# endregion
# region - School
class SchoolSchema(BaseModel):
    name: str = Field(min_length=2)
    code: str = Field(min_length=2)


class SchoolPublic(SchoolSchema):
    id: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class SchoolList(BaseModel):
    schools: list[SchoolPublic]


# endregion
# region - Token
class Token(BaseModel):
    token_type: str
    access_token: str


class TokenPair(BaseModel):
    token_type: str = 'Bearer'
    access_token: str
    refresh_token: str


class RefreshRequest(BaseModel):
    refresh_token: str


# endregion
# region - Filters
class FilterPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page: int = Field(ge=1, default=1)
    size: int = Field(ge=1, le=100, default=10)
    # backward compat aliases (deprecated): limit/offset
    limit_alias: int | None = Field(default=None, alias='limit')
    offset_alias: int | None = Field(default=None, alias='offset')

    @model_validator(mode='after')
    def _compat_limit_offset(self):
        if self.limit_alias is not None:
            self.size = self.limit_alias
        if self.offset_alias is not None:
            # keep raw offset; also set page for meta response
            # page is ceil((offset+1)/size)
            self.page = (
                (self.offset_alias // self.size) + 1 if self.size else 1
            )
        return self

    @property
    def offset(self) -> int:
        if self.offset_alias is not None:
            return self.offset_alias
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        if self.limit_alias is not None:
            return self.limit_alias
        return self.size


class FilterBook(FilterPage):
    title: str | None = Field(None, min_length=3)
    description: str | None = None
    state: BooksStates | None = None
    is_active: bool | None = None
    q: str | None = Field(
        None,
        min_length=1,
        description='Título, ISBN, código interno, gênero ou autor',
    )
    isbn: str | None = None
    internal_code: str | None = None
    genre_id: int | None = None
    genre: str | None = Field(
        default=None, description='Nome ou slug do gênero'
    )
    author_id: int | None = None
    author: str | None = Field(
        default=None, description='Nome ou slug do autor'
    )
    sort_by: Literal['title', 'created_at', 'updated_at', 'published_date', 'author', 'id'] | None = Field(
        default=None, description='Campo de ordenação'
    )
    sort_order: Literal['asc', 'desc'] | None = Field(
        default=None, description='Direção da ordenação'
    )


class FilterCopy(FilterPage):
    state: BooksStates | None = None
    condition: BookCondition | None = None
    school_id: int | None = None  # SUPER_ADMIN can filter by school
    book_id: int | None = None


class FilterLoan(FilterPage):
    status: LoanStatus | None = None
    user_id: int | None = None
    copy_id: int | None = None


class FilterReservation(FilterPage):
    status: ReservationStatus | None = None
    book_id: int | None = None


# endregion
# region - Copies
class BookCopySchema(BaseModel):
    code: str
    state: BooksStates = BooksStates.AVAILABLE
    condition: BookCondition = BookCondition.GOOD
    acquisition_date: date | None = None
    notes: str | None = None


class BookCopyPublic(BookCopySchema):
    id: int
    book_id: int
    added_by: int
    edited_by: int | None = None
    school_id: int

    model_config = ConfigDict(from_attributes=True)


class BookCopyList(BaseModel):
    copies: list[BookCopyPublic]


class BookCopyUpdate(BaseModel):
    code: str | None = None
    state: BooksStates | None = None
    condition: BookCondition | None = None
    acquisition_date: date | None = None
    notes: str | None = None


# endregion
# region - Books
class BooksSchema(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    isbn: str | None = None
    cover_url: str | None = None
    published_date: date | None = None
    genre_ids: list[int] | None = None
    genre_names: list[str] | None = None
    author_ids: list[int] | None = None
    author_names: list[str] | None = None

    @model_validator(mode='after')
    def validate_identifiers(self):
        has_title = bool(self.title and self.title.strip())
        has_isbn = bool(self.isbn and self.isbn.strip())
        if not has_title and not has_isbn:
            raise ValueError("Either 'title' or 'isbn' must be provided.")
        return self


class BooksPublic(BooksSchema):
    id: int
    is_active: bool = True
    added_by: int
    edited_by: int | None = None
    derived_state: BooksStates = BooksStates.ARCHIVED
    created_at: datetime | None = None
    updated_at: datetime | None = None
    genres: list[GenrePublic] = Field(default_factory=list)
    genre_ids: list[int] = Field(default_factory=list)  # type: ignore[assignment]
    genre_names: list[str] = Field(default_factory=list)  # type: ignore[assignment]
    authors: list[AuthorPublic] = Field(default_factory=list)
    author_ids: list[int] = Field(default_factory=list)  # type: ignore[assignment]
    author_names: list[str] = Field(default_factory=list)  # type: ignore[assignment]

    model_config = ConfigDict(from_attributes=True)


class BookList(BaseModel):
    books: list[BooksPublic]


class BookUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    cover_url: str | None = None
    published_date: date | None = None
    genre_ids: list[int] | None = None
    genre_names: list[str] | None = None
    author_ids: list[int] | None = None
    author_names: list[str] | None = None


class BookLookupResponse(BaseModel):
    isbn: str
    title: str | None = None
    description: str | None = None
    cover_url: str | None = None
    published_date: date | None = None
    genres: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    found: bool = False
    already_exists: bool = False
    existing_book_id: int | None = None


class BookResolveResponse(BaseModel):
    kind: Literal['isbn', 'internal_code', 'title', 'none']
    book_id: int | None = None


class BookSuggestion(BaseModel):
    id: int
    title: str
    isbn: str | None = None

    model_config = ConfigDict(from_attributes=True)


class BookSuggestResponse(BaseModel):
    items: list[BookSuggestion]


# endregion
# region - Loans
class LoanCreate(BaseModel):
    copy_id: int
    user_id: int


class LoanPublic(BaseModel):
    id: int
    copy_id: int
    user_id: int
    school_id: int
    borrowed_at: datetime
    due_date: datetime
    returned_at: datetime | None = None
    late_days: int = 0
    status: LoanStatus

    model_config = ConfigDict(from_attributes=True)


class LoanList(BaseModel):
    loans: list[LoanPublic]


# endregion
# region - Reservations
class ReservationCreate(BaseModel):
    book_id: int


class ReservationPublic(BaseModel):
    id: int
    book_id: int
    user_id: int
    school_id: int
    status: ReservationStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReservationList(BaseModel):
    reservations: list[ReservationPublic]


# endregion
