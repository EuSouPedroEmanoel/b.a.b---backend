from datetime import datetime, timedelta, timezone

import factory.fuzzy

from src.models import (
    Book,
    BookCondition,
    BookCopy,
    BooksStates,
    Loan,
    LoanStatus,
    Reservation,
    ReservationStatus,
    School,
)


class SchoolFactory(factory.Factory):
    class Meta:
        model = School

    name = factory.Faker('company')
    code = factory.Sequence(lambda n: f'SCH-{n}')
    is_active = True


class BookFactory(factory.Factory):
    class Meta:
        model = Book

    class Params:
        user_id = None  # legacy alias for added_by

    title = factory.Faker('text')
    description = factory.Faker('text')
    isbn = factory.Faker('isbn13')
    published_date = factory.Faker('date_object')
    added_by = factory.LazyAttribute(
        lambda o: o.user_id if o.user_id is not None else 1
    )
    edited_by = None
    is_active = True


class BookCopyFactory(factory.Factory):
    class Meta:
        model = BookCopy

    class Params:
        user_id = None  # legacy alias for added_by

    code = factory.Sequence(lambda n: f'EX-{n}')
    state = BooksStates.AVAILABLE
    condition = BookCondition.GOOD
    book_id = 1
    added_by = factory.LazyAttribute(
        lambda o: o.user_id if o.user_id is not None else 1
    )
    edited_by = None
    school_id = 1


class LoanFactory(factory.Factory):
    class Meta:
        model = Loan

    copy_id = 1
    user_id = 1
    school_id = 1
    due_date = factory.LazyFunction(
        lambda: datetime.now(timezone.utc) + timedelta(days=14)
    )
    status = LoanStatus.ACTIVE
    late_days = 0


class ReservationFactory(factory.Factory):
    class Meta:
        model = Reservation

    book_id = 1
    user_id = 1
    school_id = 1
    status = ReservationStatus.ACTIVE
