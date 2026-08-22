from datetime import date

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from scr.models import BookCondition, BooksStates


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

    model_config = ConfigDict(from_attributes=True)


class UserDB(UserSchema):
    id: int


class UserList(BaseModel):
    users: list[UserPublic]


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


# endregion
# region - Copies
class BookCopySchema(BaseModel):
    internal_code: str
    state: BooksStates = BooksStates.AVAILABLE
    condition: BookCondition = BookCondition.GOOD
    acquisition_date: date | None = None
    notes: str | None = None


class BookCopyPublic(BookCopySchema):
    id: int
    book_id: int
    user_id: int

    model_config = ConfigDict(from_attributes=True)


class BookCopyList(BaseModel):
    copies: list[BookCopyPublic]


class BookCopyUpdate(BaseModel):
    state: BooksStates | None = None
    condition: BookCondition | None = None
    acquisition_date: date | None = None
    notes: str | None = None


# endregion
# region - Books
class BooksSchema(BaseModel):
    title: str | None = None
    description: str | None = None
    state: BooksStates | None = BooksStates.AVAILABLE
    isbn: str | None = None
    internal_code: str | None = None

    @model_validator(mode='after')
    def validate_identifiers(self):
        if not self.isbn and not self.internal_code:
            raise ValueError(
                "É necessário informar o 'isbn' ou o 'internal_code'."
            )
        if not self.isbn and not self.title:
            raise ValueError(
                "O 'title' é obrigatório quando o livro não possui 'isbn'."
            )
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
