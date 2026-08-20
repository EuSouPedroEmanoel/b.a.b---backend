import factory.fuzzy

from scr.models import Book, BooksStates


class BookFactory(factory.Factory):
    class Meta:
        model = Book

    title = factory.Faker('text')
    description = factory.Faker('text')
    isbn = factory.Faker('isbn13')
    state = factory.fuzzy.FuzzyChoice(BooksStates)
    user_id = 1
