from datetime import date

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from scr.models import BookCondition, BooksStates, UserRole


class Message(BaseModel):
    message: str


# region - User
class UserSchema(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserPublic(BaseModel):
    username: str
    email: EmailStr
    id: int
    role: UserRole
    school_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class UserDB(UserSchema):
    id: int


class UserList(BaseModel):
    users: list[UserPublic]


class StaffCreateSchema(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: UserRole = UserRole.LIBRARIAN
    school_id: int | None = None  # only honored for SUPER_ADMIN

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


class SchoolAdminCreateSchema(BaseModel):
    username: str
    email: EmailStr
    password: str


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


# endregion
# region - Filters
class FilterPage(BaseModel):
    limit: int = Field(ge=1, default=10)
    offset: int = Field(ge=0, default=0)


class FilterBook(FilterPage):
    title: str | None = Field(None, min_length=3)
    description: str | None = None
    state: BooksStates | None = None


class FilterCopy(FilterPage):
    state: BooksStates | None = None
    condition: BookCondition | None = None
    school_id: int | None = None  # SUPER_ADMIN can filter by school


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
    user_id: int
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
    title: str
    description: str | None = None
    state: BooksStates | None = BooksStates.AVAILABLE
    isbn: str | None = None

    @model_validator(mode='after')
    def validate_identifiers(self):
        if not self.title:
            raise ValueError("O 'title' é obrigatório.")
        return self


class BooksPublic(BooksSchema):
    id: int

    model_config = ConfigDict(from_attributes=True)


class BookList(BaseModel):
    books: list[BooksPublic]


class BookUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    state: BooksStates | None = None


# endregion
