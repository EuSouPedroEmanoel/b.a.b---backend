import asyncio
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.models import Book, BookCopy, School, User, UserRole
from src.security import get_password_hash
from src.settings import Settings

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


async def seed_books_and_copies(
    session: AsyncSession,  # noqa: E501
    schools: list[School],  # noqa: E501
    users: dict[str, User],  # noqa: E501
    super_admin: User,  # noqa: E501
) -> list[Book]:
    books_data = [  # noqa: E501
        {'title': 'Livro Dev 1 - 2 copias', 'description': 'Livro com 2 copias (uma por escola)', 'isbn': '978-0-00-000001-1'},  # noqa: E501
        {'title': 'Livro Dev 2 - 1 copia', 'description': 'Livro com 1 copia', 'isbn': '978-0-00-000001-2'},  # noqa: E501
        {'title': 'Livro Dev 3 - 0 copias', 'description': 'Livro sem copias', 'isbn': '978-0-00-000001-3'},  # noqa: E501
    ]
    books: list[Book] = []
    for data in books_data:
        existing = await session.scalar(select(Book).where(Book.isbn == data['isbn']))  # noqa: E501
        if existing:
            print(f"Book {existing.isbn} already exists (id={existing.id})")
            books.append(existing)
            continue
        book = Book(
            title=data['title'],
            description=data['description'],
            isbn=data['isbn'],
            added_by=super_admin.id,
        )
        session.add(book)
        await session.flush()
        print(f"Book '{book.title}' created (id={book.id}, isbn={book.isbn})")
        books.append(book)
    await session.commit()
    for b in books:
        await session.refresh(b)

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
