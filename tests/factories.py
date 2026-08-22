import factory.fuzzy

from scr.models import Book, BookCondition, BookCopy, BooksStates


class BookFactory(factory.Factory):
    class Meta:
        model = Book

    title = factory.Faker('text')
    description = factory.Faker('text')
    isbn = factory.Faker('isbn13')
    state = factory.fuzzy.FuzzyChoice(BooksStates)
    user_id = 1


class BookCopyFactory(factory.Factory):
    class Meta:
        model = BookCopy

    internal_code = factory.Sequence(lambda n: f'EX-{n}')
    state = BooksStates.AVAILABLE
    condition = BookCondition.GOOD
    book_id = 1
    user_id = 1
