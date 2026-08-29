import asyncio
import random
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.models import Author, Book, BookCopy, Genre, School, User, UserRole
from src.security import get_password_hash
from src.settings import Settings
from src.utils.authors import display_name_author, slugify_author
from src.utils.genres import display_name_genre, slugify_genre

settings = Settings()

DEV_PASSWORD = 'dev123'
DEV_SUPER_ADMIN = {
    'username': 'dev',
    'email': 'dev@email.com',
    'password': 'dev123',
}


def _cpf_with_check(base: str) -> str:
    """Append two valid check digits to a 9-digit base to form a valid CPF."""
    def _digit(digs: list[int]) -> int:
        total = sum(d * (w) for d, w in zip(digs, range(len(digs) + 1, 1, -1)))
        rest = (total * 10) % 11
        return 0 if rest == 10 else rest

    digs = [int(c) for c in base]
    d1 = _digit(digs)
    d2 = _digit(digs + [d1])
    return base + str(d1) + str(d2)


def _student_fields(username: str) -> dict:
    num = username.replace('student_dev', '').replace('_dev', '') or '0'
    num = num.zfill(2)
    idx = int(num) if num.isdigit() else 0
    letras = ('A', 'B')
    hoje = date.today()
    idade = 10 + (idx % 5)  # 10..14 anos
    return {
        'cpf': _cpf_with_check(f'{num}'.rjust(9, '0')),
        'birthdate': date(hoje.year - idade, hoje.month, hoje.day),
        'turma_numero': 6 + (idx % 4),  # 6, 7, 8, 9 -> ex.: 7A, 8B
        'turma_letra': letras[idx % 2],  # A, B alternando
    }


async def seed_schools(session: AsyncSession) -> list[School]:
    schools_data = [
        {'name': 'Escola Dev 1', 'code': 'SCH-DEV-01'},
        {'name': 'Escola Dev 2', 'code': 'SCH-DEV-02'},
    ]
    schools: list[School] = []
    for data in schools_data:
        existing = await session.scalar(
            select(School).where(School.code == data['code'])
        )
        if existing:
            print(f"School {existing.code} already exists (id={existing.id})")
            schools.append(existing)
            continue
        school = School(name=data['name'], code=data['code'])
        session.add(school)
        await session.flush()
        print(f"School {school.code} created (id={school.id})")
        schools.append(school)
    await session.commit()
    for s in schools:
        await session.refresh(s)
    return schools


async def seed_users(session: AsyncSession, schools: list[School]) -> dict:
    users: dict[str, User] = {}
    # ensure super_admin exists first
    # role, username suffix, school
    specs = []
    for idx, school in enumerate(schools, start=1):
        specs.extend([  # noqa: E501
            (f'school_admin_dev{idx}', f'school_admin_dev{idx}@exemplo.com', UserRole.SCHOOL_ADMIN, school.id),  # noqa: E501
            (f'librarian_dev{idx}', f'librarian_dev{idx}@exemplo.com', UserRole.LIBRARIAN, school.id),  # noqa: E501
            (f'teacher_dev{idx}', f'teacher_dev{idx}@exemplo.com', UserRole.TEACHER, school.id),  # noqa: E501
            (f'student_dev{idx}', f'student_dev{idx}@exemplo.com', UserRole.STUDENT, school.id),  # noqa: E501
        ])
    for username, email, role, school_id in specs:
        existing = await session.scalar(
            select(User).where(User.username == username)
        )
        if existing:
            print(f"User {username} already exists (id={existing.id})")
            users[username] = existing
            continue
        user = User(
            username=username,
            email=email,
            password=get_password_hash(DEV_PASSWORD),
            role=role,
            school_id=school_id,
            **(_student_fields(username) if role == UserRole.STUDENT else {}),
        )
        session.add(user)
        await session.flush()
        print(f"User {username} ({role.value}) created (id={user.id}, school_id={school_id})")  # noqa: E501
        users[username] = user
    await session.commit()
    for u in users.values():
        await session.refresh(u)
    return users


GENRE_POOL = [
    'Ficção', 'Romance', 'Técnico', 'Fantasia', 'Mistério', 'Suspense',
    'Biografia', 'História', 'Ciência', 'Aventura', 'Poesia', 'Filosofia',
    'Arte', 'Infantil', 'Clássico', 'Humor',
]

AUTHOR_POOL = [
    'Machado de Assis', 'Clarice Lispector', 'Jorge Amado', 'Cecília Meireles',
    'Carlos Drummond', 'Monteiro Lobato', 'Lygia Fagundes', 'João Guimarães',
    'Paulo Coelho', 'Conceição Evaristo', 'Graciliano Ramos', 'Rachel de Queiroz',
]

COVER_POOL = [
    'https://picsum.photos/seed/{seed}/400/600',
    'https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg',
    'https://picsum.photos/400/600?random={rand}',
]


async def _get_or_create_genre_seed(session: AsyncSession, name: str) -> Genre:
    canonical = display_name_genre(name)
    slug = slugify_genre(canonical)
    existing = await session.scalar(select(Genre).where(Genre.slug == slug))
    if existing:
        return existing
    g = Genre(name=canonical, slug=slug)
    session.add(g)
    await session.flush()
    return g


async def _get_or_create_author_seed(session: AsyncSession, name: str) -> Author:
    canonical = display_name_author(name)
    slug = slugify_author(canonical)
    existing = await session.scalar(select(Author).where(Author.slug == slug))
    if existing:
        return existing
    a = Author(name=canonical, slug=slug)
    session.add(a)
    await session.flush()
    return a


async def seed_books_and_copies(
    session: AsyncSession,  # noqa: E501
    schools: list[School],  # noqa: E501
    users: dict[str, User],  # noqa: E501
    super_admin: User,  # noqa: E501
) -> list[Book]:
    books_data = [  # noqa: E501
        {'title': 'Livro Dev 1 - 2 copias', 'description': 'Livro com 2 copias (uma por escola)', 'isbn': '978-0-00-000001-1', 'published_date': date(2018, 5, 20)},  # noqa: E501
        {'title': 'Livro Dev 2 - 1 copia', 'description': 'Livro com 1 copia', 'isbn': '978-0-00-000001-2', 'published_date': date(2020, 8, 15)},  # noqa: E501
        {'title': 'Livro Dev 3 - 0 copias', 'description': 'Livro sem copias', 'isbn': '978-0-00-000001-3', 'published_date': date(2022, 11, 3)},  # noqa: E501
    ]
    # garante pool de gêneros e autores existe
    for gname in GENRE_POOL:
        await _get_or_create_genre_seed(session, gname)
    for aname in AUTHOR_POOL:
        await _get_or_create_author_seed(session, aname)
    await session.commit()

    books: list[Book] = []
    for idx, data in enumerate(books_data):
        existing = await session.scalar(select(Book).where(Book.isbn == data['isbn']))  # noqa: E501
        if existing:
            # atualiza capa, gêneros, autores e data de lançamento a cada seed (mesmo se já existe)
            tpl = random.choice(COVER_POOL)
            existing.cover_url = tpl.format(seed=f"{existing.isbn}-{random.randint(1,9999)}", isbn=existing.isbn.replace('-', ''), rand=random.randint(1, 1_000_000))
            if data.get('published_date'):
                existing.published_date = data['published_date']
            # gêneros aleatórios 1-3
            k = random.randint(1, 3)
            chosen = random.sample(GENRE_POOL, k=k)
            genres = []
            for c in chosen:
                g = await _get_or_create_genre_seed(session, c)
                genres.append(g)
            existing.genres = genres
            # autores aleatórios 1-2
            ak = random.randint(1, 2)
            chosen_a = random.sample(AUTHOR_POOL, k=ak)
            authors = []
            for c in chosen_a:
                a = await _get_or_create_author_seed(session, c)
                authors.append(a)
            existing.authors = authors
            existing.edited_by = super_admin.id
            session.add(existing)
            await session.flush()
            print(f"Book {existing.isbn} updated cover/genres/authors/published_date (id={existing.id}, genres={[g.name for g in genres]}, authors={[a.name for a in authors]}, published_date={existing.published_date})")
            books.append(existing)
            continue
        tpl = random.choice(COVER_POOL)
        cover_url = tpl.format(seed=f"{data['isbn']}-{random.randint(1,9999)}", isbn=data['isbn'].replace('-', ''), rand=random.randint(1, 1_000_000))
        k = random.randint(1, 3)
        chosen = random.sample(GENRE_POOL, k=k)
        genres = []
        for c in chosen:
            g = await _get_or_create_genre_seed(session, c)
            genres.append(g)
        ak = random.randint(1, 2)
        chosen_a = random.sample(AUTHOR_POOL, k=ak)
        authors = []
        for c in chosen_a:
            a = await _get_or_create_author_seed(session, c)
            authors.append(a)
        book = Book(
            title=data['title'],
            description=data['description'],
            isbn=data['isbn'],
            cover_url=cover_url,
            published_date=data.get('published_date'),
            added_by=super_admin.id,
        )
        book.genres = genres
        book.authors = authors
        session.add(book)
        await session.flush()
        print(f"Book '{book.title}' created (id={book.id}, isbn={book.isbn}, cover={cover_url}, genres={[g.name for g in genres]}, authors={[a.name for a in authors]})")
        books.append(book)
    await session.commit()
    for b in books:
        await session.refresh(b, attribute_names=['genres', 'authors'])

    # copies: B1 2 copies (one per school), B2 1 copy (school 1), B3 0
    # use librarian of each school as added_by
    copies_spec = []
    if len(schools) >= 2 and len(books) >= 3:  # noqa: PLR2004
        lib1 = users.get('librarian_dev1')
        lib2 = users.get('librarian_dev2')
        # B1
        copies_spec.append((books[0].id, 'EX-DEV-001', schools[0].id, lib1.id if lib1 else super_admin.id))  # noqa: E501
        copies_spec.append((books[0].id, 'EX-DEV-001', schools[1].id, lib2.id if lib2 else super_admin.id))  # noqa: E501
        # B2
        copies_spec.append((books[1].id, 'EX-DEV-002', schools[0].id, lib1.id if lib1 else super_admin.id))  # noqa: E501
        # B3 0 copies

    for book_id, code, school_id, added_by in copies_spec:
        existing = await session.scalar(
            select(BookCopy).where(BookCopy.school_id == school_id, BookCopy.code == code)
        )
        if existing:
            print(f"Copy {code} at school {school_id} already exists (id={existing.id})")
            continue
        copy = BookCopy(
            code=code,
            book_id=book_id,
            added_by=added_by,
            school_id=school_id,
        )
        session.add(copy)
        await session.flush()
        print(f"Copy {code} for book {book_id} at school {school_id} created (id={copy.id})")
    await session.commit()
    return books


async def seed_dev():
    engine = create_async_engine(settings.DATABASE_URL)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        super_admin = await session.scalar(
            select(User).where(User.username == DEV_SUPER_ADMIN['username'])
        )
        if not super_admin:
            super_admin = User(
                username=DEV_SUPER_ADMIN['username'],
                email=DEV_SUPER_ADMIN['email'],
                password=get_password_hash(DEV_SUPER_ADMIN['password']),
                role=UserRole.SUPER_ADMIN,
                school_id=None,
            )
            session.add(super_admin)
            await session.flush()
            print(f"DEV SUPER_ADMIN {super_admin.username} created (id={super_admin.id})")
            await session.commit()
            await session.refresh(super_admin)
        else:
            print(f"DEV SUPER_ADMIN {super_admin.username} already exists (id={super_admin.id})")
        schools = await seed_schools(session)
        users = await seed_users(session, schools)
        await seed_books_and_copies(session, schools, users, super_admin)
    await engine.dispose()
    print('DEV seed completed')


if __name__ == '__main__':  # pragma: no cover
    asyncio.run(seed_dev())  # pragma: no cover
