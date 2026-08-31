"""Segundo seed — bem populado com empréstimos para testar algoritmo de recomendação.

Pipeline validado:
 - Afinidade 50%: histórico + usuários similares
 - Contexto 30%: mesmo autor/gênero do livro alvo
 - Tendências 20%: top emprestados 30d inter-escolas
 - Fallback lazy: mesmo gênero/autor, senão []
 - Reranking max 2 mesmo autor

Idempotente: get_or_create por isbn/code/slug. Re-rodável.
Uso:
  poetry run python -m src.seeds.recommendations
  poetry run python -m src.seeds.recommendations --reset
  docker compose exec backend python -m src.seeds.recommendations
"""
import argparse
import asyncio
import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.models import (
    Author,
    Book,
    BookCopy,
    BooksStates,
    Genre,
    Loan,
    LoanStatus,
    Reservation,
    ReservationStatus,
    School,
    User,
    UserRole,
)
from src.security import get_password_hash
from src.settings import Settings
from src.utils.authors import display_name_author, slugify_author
from src.utils.genres import display_name_genre, slugify_genre

settings = Settings()

DEV_PASSWORD = "dev123"
DEV_SUPER_ADMIN = {"username": "dev", "email": "dev@email.com", "password": "dev123"}
REC_PASSWORD = "rec123"

# Clusters determinísticos para validar contexto/fallback
CLUSTERS = [
    {
        "genre": "Fantasia",
        "author": "Machado de Assis",
        "prefix": "REC-A",
        "count": 8,
        "books": [
            {"title": "REC-A 01 - Fantasia Machado - Fundamentos", "isbn": "978-1-REC-A01-1"},
            {"title": "REC-A 02 - Fantasia Machado - Aventuras", "isbn": "978-1-REC-A02-2"},
            {"title": "REC-A 03 - Fantasia Machado - Mistérios", "isbn": "978-1-REC-A03-3"},
            {"title": "REC-A 04 - Fantasia Machado - O Retorno", "isbn": "978-1-REC-A04-4"},
            {"title": "REC-A 05 - Fantasia Machado - Legados", "isbn": "978-1-REC-A05-5"},
            {"title": "REC-A 06 - Fantasia Machado - Cronicas", "isbn": "978-1-REC-A06-6"},
            {"title": "REC-A 07 - Fantasia Machado - Ecos", "isbn": "978-1-REC-A07-7"},
            {"title": "REC-A 08 - Fantasia Machado - Órfão (sem cópia)", "isbn": "978-1-REC-A08-8", "orphan": True},
        ],
    },
    {
        "genre": "Mistério",
        "author": "Clarice Lispector",
        "prefix": "REC-B",
        "count": 8,
        "books": [
            {"title": "REC-B 01 - Mistério Clarice - Sombras", "isbn": "978-1-REC-B01-1"},
            {"title": "REC-B 02 - Mistério Clarice - Enigmas", "isbn": "978-1-REC-B02-2"},
            {"title": "REC-B 03 - Mistério Clarice - Vestígios", "isbn": "978-1-REC-B03-3"},
            {"title": "REC-B 04 - Mistério Clarice - Silêncio", "isbn": "978-1-REC-B04-4"},
            {"title": "REC-B 05 - Mistério Clarice - Névoa", "isbn": "978-1-REC-B05-5"},
            {"title": "REC-B 06 - Mistério Clarice - Chaves", "isbn": "978-1-REC-B06-6"},
            {"title": "REC-B 07 - Mistério Clarice - Espelho", "isbn": "978-1-REC-B07-7"},
            {"title": "REC-B 08 - Mistério Clarice - Órfão", "isbn": "978-1-REC-B08-8", "orphan": True},
        ],
    },
    {
        "genre": "Ciência",
        "author": "Cecília Meireles",
        "prefix": "REC-C",
        "count": 8,
        "books": [
            {"title": "REC-C 01 - Ciência Cecília - Experimentos", "isbn": "978-1-REC-C01-1"},
            {"title": "REC-C 02 - Ciência Cecília - Horizontes", "isbn": "978-1-REC-C02-2"},
            {"title": "REC-C 03 - Ciência Cecília - Partículas", "isbn": "978-1-REC-C03-3"},
            {"title": "REC-C 04 - Ciência Cecília - Orbitas", "isbn": "978-1-REC-C04-4"},
            {"title": "REC-C 05 - Ciência Cecília - Códigos", "isbn": "978-1-REC-C05-5"},
            {"title": "REC-C 06 - Ciência Cecília - Sinais", "isbn": "978-1-REC-C06-6"},
            {"title": "REC-C 07 - Ciência Cecília - Núcleos", "isbn": "978-1-REC-C07-7"},
            {"title": "REC-C 08 - Ciência Cecília - Órfão", "isbn": "978-1-REC-C08-8", "orphan": True},
        ],
    },
]

SCHOOLS_REC = [
    {"name": "Escola REC 1", "code": "SCH-REC-01"},
    {"name": "Escola REC 2", "code": "SCH-REC-02"},
    {"name": "Escola REC 3", "code": "SCH-REC-03"},
]


def _cpf_with_check(base: str) -> str:
    def _digit(digs: list[int]) -> int:
        total = sum(d * w for d, w in zip(digs, range(len(digs) + 1, 1, -1)))
        rest = (total * 10) % 11
        return 0 if rest == 10 else rest
    digs = [int(c) for c in base]
    d1 = _digit(digs)
    d2 = _digit(digs + [d1])
    return base + str(d1) + str(d2)


def _student_fields(username: str) -> dict:
    # base numérica estável
    num = "".join(c for c in username if c.isdigit()) or "0"
    num = num.zfill(9)[-9:]
    # evita colisão com dev seed (usa base 900 + idx)
    base = f"9{num[-8:]}"
    hoje = date.today()
    idx = int(num[-2:]) if num[-2:].isdigit() else 0
    idade = 11 + (idx % 4)
    return {
        "cpf": _cpf_with_check(base),
        "birthdate": date(hoje.year - idade, hoje.month, hoje.day),
        "turma_numero": 6 + (idx % 4),
        "turma_letra": ("A", "B")[idx % 2],
    }


async def _get_or_create_genre(session: AsyncSession, name: str) -> Genre:
    canonical = display_name_genre(name)
    slug = slugify_genre(canonical)
    existing = await session.scalar(select(Genre).where(Genre.slug == slug))
    if existing:
        return existing
    g = Genre(name=canonical, slug=slug)
    session.add(g)
    await session.flush()
    return g


async def _get_or_create_author(session: AsyncSession, name: str) -> Author:
    canonical = display_name_author(name)
    slug = slugify_author(canonical)
    existing = await session.scalar(select(Author).where(Author.slug == slug))
    if existing:
        return existing
    a = Author(name=canonical, slug=slug)
    session.add(a)
    await session.flush()
    return a


async def seed_schools_rec(session: AsyncSession) -> list[School]:
    schools: list[School] = []
    # mantém SCH-DEV-01/02 se existirem
    for data in SCHOOLS_REC:
        existing = await session.scalar(select(School).where(School.code == data["code"]))
        if existing:
            print(f"School {existing.code} already exists (id={existing.id})")
            schools.append(existing)
            continue
        s = School(name=data["name"], code=data["code"])
        session.add(s)
        await session.flush()
        print(f"School {s.code} created (id={s.id})")
        schools.append(s)
    await session.commit()
    for s in schools:
        await session.refresh(s)
    return schools


async def seed_users_rec(session: AsyncSession, schools: list[School]) -> dict[str, User]:
    users: dict[str, User] = {}
    specs: list[tuple[str, str, UserRole, int]] = []
    for school in schools:
        # admin/librarian para cada escola REC
        specs.extend([
            (f"librarian_rec_{school.code.lower()}", f"librarian_rec_{school.code.lower()}@exemplo.com", UserRole.LIBRARIAN, school.id),
            (f"teacher_rec_{school.code.lower()}", f"teacher_rec_{school.code.lower()}@exemplo.com", UserRole.TEACHER, school.id),
        ])
        # 4 students rec por escola para afinidade
        for i in range(1, 5):
            uname = f"student_rec_{school.code.lower()}_{i}"
            specs.append((uname, f"{uname}@exemplo.com", UserRole.STUDENT, school.id))
    # students extras específicos para cenários de afinidade (na SCH-REC-01)
    # já cobertos acima

    for username, email, role, school_id in specs:
        existing = await session.scalar(select(User).where(User.username == username))
        if existing:
            print(f"User {username} already exists (id={existing.id})")
            users[username] = existing
            continue
        extra = _student_fields(username) if role == UserRole.STUDENT else {}
        u = User(
            username=username,
            email=email,
            password=get_password_hash(REC_PASSWORD),
            role=role,
            school_id=school_id,
            **extra,
        )
        session.add(u)
        await session.flush()
        print(f"User {username} ({role.value}) created (id={u.id}, school_id={school_id})")
        users[username] = u
    await session.commit()
    for u in users.values():
        await session.refresh(u)
    return users


async def seed_books_rec(session: AsyncSession, super_admin: User) -> list[Book]:
    books: list[Book] = []
    for cluster in CLUSTERS:
        genre = await _get_or_create_genre(session, cluster["genre"])
        author = await _get_or_create_author(session, cluster["author"])
        for idx, data in enumerate(cluster["books"]):
            isbn = data["isbn"].replace("-", "").replace(" ", "")
            existing = await session.scalar(select(Book).where(Book.isbn == isbn))
            # também busca por isbn com hífen da definição original
            if not existing:
                existing = await session.scalar(select(Book).where(Book.isbn == data["isbn"]))
            if existing:
                # atualiza para garantir cluster correto
                existing.title = data["title"]
                existing.description = f"Livro de teste recomendações - {cluster['genre']}/{cluster['author']} - {data['title']}"
                existing.cover_url = f"https://dummyimage.com/400x600/0f4c75/ffffff&text={cluster['prefix']}+{idx+1:02d}" if not data.get("orphan") else f"https://dummyimage.com/400x600/0f4c75/ffffff&text={cluster['prefix']}+Orfao"
                existing.is_active = True
                existing.genres = [genre]
                existing.authors = [author]
                existing.edited_by = super_admin.id
                session.add(existing)
                await session.flush()
                print(f"Book {existing.isbn} updated cluster {cluster['prefix']} (id={existing.id}, orphan={bool(data.get('orphan'))})")
                books.append(existing)
                continue
            book = Book(
                title=data["title"],
                description=f"Livro de teste recomendações - {cluster['genre']}/{cluster['author']} - {data['title']}",
                isbn=isbn,
                cover_url=f"https://dummyimage.com/400x600/0f4c75/ffffff&text={cluster['prefix']}+{idx+1:02d}" if not data.get("orphan") else f"https://dummyimage.com/400x600/0f4c75/ffffff&text={cluster['prefix']}+Orfao",
                published_date=date(2015 + idx, (idx % 12) + 1, (idx % 28) + 1),
                added_by=super_admin.id,
            )
            book.genres = [genre]
            book.authors = [author]
            session.add(book)
            await session.flush()
            print(f"Book '{book.title}' created (id={book.id}, isbn={book.isbn}, {cluster['genre']}/{cluster['author']}, orphan={bool(data.get('orphan'))})")
            books.append(book)
    await session.commit()
    for b in books:
        await session.refresh(b, attribute_names=["genres", "authors"])
    return books


async def seed_copies_rec(session: AsyncSession, books: list[Book], schools: list[School], users: dict[str, User], super_admin: User) -> list[BookCopy]:
    """Cada livro do cluster recebe cópia AVAILABLE em cada escola REC, exceto órfãos (sem cópia)."""
    copies: list[BookCopy] = []
    # mapa escola -> librarian
    lib_by_school: dict[int, User] = {}
    for s in schools:
        # tenta achar librarian_rec para a escola, fallback super_admin
        lib = None
        for u in users.values():
            if u.role == UserRole.LIBRARIAN and u.school_id == s.id:
                lib = u
                break
        lib_by_school[s.id] = lib or super_admin

    # índice rápido isbn -> book
    isbn_to_book = {b.isbn: b for b in books}
    # também tenta por título prefix
    for cluster in CLUSTERS:
        for data in cluster["books"]:
            isbn = data["isbn"].replace("-", "").replace(" ", "")
            book = isbn_to_book.get(isbn)
            if not book:
                # busca por título
                book = await session.scalar(select(Book).where(Book.title == data["title"]))
            if not book:
                continue
            if data.get("orphan"):
                # garante que órfão não tenha cópias (remove se existir)
                existing = (await session.scalars(select(BookCopy).where(BookCopy.book_id == book.id))).all()
                for ec in existing:
                    await session.delete(ec)
                    print(f"Copy orphan cleanup {ec.code} book {book.id} removed")
                await session.flush()
                continue
            for school in schools:
                code = f"EX-{cluster['prefix']}-{data['isbn'][-2:]}-S{school.id:02d}"
                existing = await session.scalar(select(BookCopy).where(BookCopy.school_id == school.id, BookCopy.code == code))
                if existing:
                    if existing.state != BooksStates.AVAILABLE:
                        existing.state = BooksStates.AVAILABLE
                        await session.flush()
                    copies.append(existing)
                    continue
                lib = lib_by_school[school.id]
                cp = BookCopy(code=code, book_id=book.id, added_by=lib.id, school_id=school.id, state=BooksStates.AVAILABLE)
                session.add(cp)
                await session.flush()
                print(f"Copy {code} book {book.id} school {school.code} created (id={cp.id})")
                copies.append(cp)
    await session.commit()
    return copies


GENRE_POOL_DIVERSE = [
    "Ficção", "Romance", "Técnico", "Fantasia", "Mistério", "Suspense",
    "Biografia", "História", "Ciência", "Aventura", "Poesia", "Filosofia",
    "Arte", "Infantil", "Clássico", "Humor",
]
AUTHOR_POOL_DIVERSE = [
    "Machado de Assis", "Clarice Lispector", "Jorge Amado", "Cecília Meireles",
    "Carlos Drummond", "Monteiro Lobato", "Lygia Fagundes", "João Guimarães",
    "Paulo Coelho", "Conceição Evaristo", "Graciliano Ramos", "Rachel de Queiroz",
]


async def seed_diversified_books(session: AsyncSession, schools: list[School], users: dict[str, User], super_admin: User):
    """Cria livros extras para diversificar acervos:
    - SCH-REC-01: alta diversificação (12 livros com 2-3 gêneros/1-2 autores aleatórios)
    - SCH-REC-02/03: baixa diversificação (3 livros cada, 1 gênero/1 autor)
    Esses livros têm cópia APENAS na escola de origem, criando acervos heterogêneos.
    """
    random.seed(42)
    # mapa escola -> librarian
    lib_by_school = {}
    for s in schools:
        lib = next((u for u in users.values() if u.role == UserRole.LIBRARIAN and u.school_id == s.id), None)
        lib_by_school[s.id] = lib or super_admin

    # config por escola: quantos livros extras e quantos gêneros/autores
    config = {
        "SCH-REC-01": {"count": 12, "genres": (2, 3), "authors": (1, 2)},  # alta
        "SCH-REC-02": {"count": 3, "genres": (1, 1), "authors": (1, 1)},   # baixa
        "SCH-REC-03": {"count": 3, "genres": (1, 1), "authors": (1, 1)},   # baixa
    }
    for school in schools:
        cfg = config.get(school.code)
        if not cfg:
            continue
        for i in range(1, cfg["count"] + 1):
            isbn = f"978-1-REC-DIV-{school.code[-2:]}-{i:02d}-{random.randint(0,9)}"
            clean_isbn = isbn.replace("-", "").replace(" ", "")
            existing = await session.scalar(select(Book).where(Book.isbn == clean_isbn))
            if existing:
                # garante cópia só na escola
                code = f"EX-DIV-{school.code[-2:]}-{i:02d}"
                existing_copy = await session.scalar(select(BookCopy).where(BookCopy.school_id == school.id, BookCopy.code == code))
                if not existing_copy:
                    lib = lib_by_school[school.id]
                    cp = BookCopy(code=code, book_id=existing.id, added_by=lib.id, school_id=school.id, state=BooksStates.AVAILABLE)
                    session.add(cp)
                    await session.flush()
                    print(f"Copy diversificada {code} escola {school.code} (livro {existing.id})")
                continue
            # gêneros/autores aleatórios conforme config
            k = random.randint(*cfg["genres"])
            chosen_g = random.sample(GENRE_POOL_DIVERSE, k=k)
            genres = [await _get_or_create_genre(session, g) for g in chosen_g]
            ak = random.randint(*cfg["authors"])
            chosen_a = random.sample(AUTHOR_POOL_DIVERSE, k=ak)
            authors = [await _get_or_create_author(session, a) for a in chosen_a]
            title = f"REC-DIV {school.code[-2:]}-{i:02d} - {'/'.join(chosen_g[:2])} - {chosen_a[0].split()[-1]}"
            book = Book(
                title=title,
                description=f"Livro diversificado {school.code} - gêneros {', '.join(chosen_g)} - autores {', '.join(chosen_a)}",
                isbn=clean_isbn,
                cover_url=f"https://dummyimage.com/400x600/1e3a5f/ffffff&text=DIV+{school.code[-2:]}-{i:02d}",
                published_date=date(2018 + (i % 8), (i % 12) + 1, (i % 28) + 1),
                added_by=super_admin.id,
            )
            book.genres = genres
            book.authors = authors
            session.add(book)
            await session.flush()
            code = f"EX-DIV-{school.code[-2:]}-{i:02d}"
            lib = lib_by_school[school.id]
            cp = BookCopy(code=code, book_id=book.id, added_by=lib.id, school_id=school.id, state=BooksStates.AVAILABLE)
            session.add(cp)
            await session.flush()
            print(f"Livro diversificado '{title}' (id={book.id}, {len(genres)} gêneros, {len(authors)} autores) + cópia {code} escola {school.code}")
    await session.commit()


async def _create_loan(session: AsyncSession, copy: BookCopy, borrower: User, days_ago: int, duration_days: int = 14, status: LoanStatus = LoanStatus.ACTIVE):
    now = datetime.now(timezone.utc)
    borrowed_at = now - timedelta(days=days_ago)
    due_date = borrowed_at + timedelta(days=duration_days)
    # evita duplicar loan ativo para mesma cópia
    existing = await session.scalar(select(Loan).where(Loan.copy_id == copy.id, Loan.status == LoanStatus.ACTIVE))
    if existing:
        # atualiza borrowed_at para teste de tendências
        existing.borrowed_at = borrowed_at
        existing.due_date = due_date
        await session.flush()
        return existing
    loan = Loan(copy_id=copy.id, user_id=borrower.id, school_id=copy.school_id, due_date=due_date, status=status)
    # força borrowed_at (default server_default, mas sobrescrevemos)
    loan.borrowed_at = borrowed_at
    if status == LoanStatus.RETURNED:
        loan.returned_at = borrowed_at + timedelta(days=duration_days - 2)
        loan.late_days = 0
    session.add(loan)
    # marca cópia como emprestada se ativo
    if status == LoanStatus.ACTIVE:
        copy.state = BooksStates.BORROWED
        session.add(copy)
    await session.flush()
    return loan


async def seed_loans_rec(session: AsyncSession, books: list[Book], schools: list[School], users: dict[str, User]):
    """Popula empréstimos para testar cada camada."""
    # resolve schools
    rec1 = next((s for s in schools if s.code == "SCH-REC-01"), schools[0])
    rec2 = next((s for s in schools if s.code == "SCH-REC-02"), schools[1] if len(schools) > 1 else schools[0])
    rec3 = next((s for s in schools if s.code == "SCH-REC-03"), schools[-1])

    # resolve books por título
    by_title = {b.title: b for b in books}
    # também por isbn prefix
    by_isbn = {b.isbn: b for b in books}

    def _book(prefix: str, idx: int) -> Book | None:
        # idx 1-based
        title = next((d["title"] for c in CLUSTERS if c["prefix"] == prefix for d in c["books"] if d["title"].startswith(f"{prefix} {idx:02d}")), None)
        if title:
            return by_title.get(title)
        # fallback por isbn
        isbn = f"9781REC{prefix[4:]}{idx:02d}1".replace("-", "")
        return by_isbn.get(isbn)

    # helper para achar usuários
    def _user(username: str) -> User | None:
        return users.get(username)

    # usuários de afinidade: student_rec_sch-rec-01_1 ..4
    s1 = _user(f"student_rec_{rec1.code.lower()}_1")
    s2 = _user(f"student_rec_{rec1.code.lower()}_2")
    s3 = _user(f"student_rec_{rec1.code.lower()}_3")
    s4 = _user(f"student_rec_{rec1.code.lower()}_4")
    if not (s1 and s2 and s3 and s4):
        # fallback para quaisquer students rec
        students = [u for u in users.values() if u.role == UserRole.STUDENT]
        s1, s2, s3, s4 = (students + [None]*4)[:4]

    # --- Afinidade: cria histórico sobreposto Cluster A ---
    # s1 pega REC-A 01,02,03 ; s2 pega REC-A 02,03,04 -> similaridade
    affinity_plan = [
        (s1, "REC-A", [1, 2, 3], rec1),
        (s2, "REC-A", [2, 3, 4], rec1),
        (s3, "REC-B", [1, 2, 3], rec1),
        (s4, "REC-C", [1, 2, 3], rec1),
    ]
    for borrower, prefix, idxs, school in affinity_plan:
        if not borrower:
            continue
        for idx in idxs:
            b = _book(prefix, idx)
            if not b:
                continue
            # acha cópia na escola
            copy = await session.scalar(select(BookCopy).where(BookCopy.book_id == b.id, BookCopy.school_id == school.id))
            if not copy:
                # cria cópia se não existir
                lib = next((u for u in users.values() if u.role == UserRole.LIBRARIAN and u.school_id == school.id), None)
                copy = BookCopy(code=f"EX-{prefix}-{idx:02d}-S{school.id:02d}-LOAN", book_id=b.id, added_by=(lib.id if lib else borrower.id), school_id=school.id, state=BooksStates.AVAILABLE)
                session.add(copy)
                await session.flush()
            await _create_loan(session, copy, borrower, days_ago=random.randint(2, 10), status=LoanStatus.ACTIVE)
            print(f"Affinity loan {borrower.username} -> {b.title} (school {school.code})")

    # --- Tendências globais: 15 loans nos últimos 30d inter-escolas, Cluster B ---
    trending_books = [ _book("REC-B", i) for i in [1, 2, 3, 4, 5]]
    for b in trending_books:
        if not b:
            continue
        for school in [rec1, rec2, rec3]:
            copy = await session.scalar(select(BookCopy).where(BookCopy.book_id == b.id, BookCopy.school_id == school.id))
            if not copy:
                continue
            # cria 1-2 loans por escola para popular count
            for _ in range(random.randint(1, 2)):
                # borrower aleatório da escola
                borrowers = [u for u in users.values() if u.school_id == school.id and u.role == UserRole.STUDENT]
                if not borrowers:
                    continue
                borrower = random.choice(borrowers)
                days_ago = random.randint(1, 25)  # dentro 30d
                await _create_loan(session, copy, borrower, days_ago=days_ago)
                print(f"Trend loan {b.title} school {school.code} days_ago={days_ago}")

    # loans fora da janela (não devem contar) - REC-C 01 em 35d
    b_old = _book("REC-C", 1)
    if b_old:
        for school in [rec1]:
            copy = await session.scalar(select(BookCopy).where(BookCopy.book_id == b_old.id, BookCopy.school_id == school.id))
            if copy and s1:
                await _create_loan(session, copy, s1, days_ago=35)
                print(f"Old loan (35d) {b_old.title} should NOT count for trends")

    # --- Reserva para validar histórico misto ---
    b_res = _book("REC-A", 5)
    if b_res and s1:
        existing = await session.scalar(select(Reservation).where(Reservation.book_id == b_res.id, Reservation.user_id == s1.id, Reservation.status == ReservationStatus.ACTIVE))
        if not existing:
            res = Reservation(book_id=b_res.id, user_id=s1.id, school_id=s1.school_id, status=ReservationStatus.ACTIVE)
            session.add(res)
            await session.flush()
            print(f"Reservation {s1.username} -> {b_res.title}")

    await session.commit()
    print("Loans/Reservations seeded")


async def seed_recommendations(reset: bool = False):
    engine = create_async_engine(settings.DATABASE_URL)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        if reset:
            print("RESET: truncating loans/reservations/copies for REC")
            await session.execute(delete(Loan).where(Loan.school_id.in_(select(School.id).where(School.code.like("SCH-REC%")))))
            await session.execute(delete(Reservation).where(Reservation.school_id.in_(select(School.id).where(School.code.like("SCH-REC%")))))
            await session.commit()

        # super_admin
        super_admin = await session.scalar(select(User).where(User.username == DEV_SUPER_ADMIN["username"]))
        if not super_admin:
            super_admin = User(username=DEV_SUPER_ADMIN["username"], email=DEV_SUPER_ADMIN["email"], password=get_password_hash(DEV_SUPER_ADMIN["password"]), role=UserRole.SUPER_ADMIN, school_id=None)
            session.add(super_admin)
            await session.flush()
            await session.commit()
            await session.refresh(super_admin)
            print(f"SUPER_ADMIN {super_admin.username} created (id={super_admin.id})")

        schools = await seed_schools_rec(session)
        users = await seed_users_rec(session, schools)
        # garante que SCH-DEV-01/02 também existam para teste tenant
        for code in ["SCH-DEV-01", "SCH-DEV-02"]:
            existing = await session.scalar(select(School).where(School.code == code))
            if existing and existing not in schools:
                schools.append(existing)
        books = await seed_books_rec(session, super_admin)
        await seed_copies_rec(session, books, schools, users, super_admin)
        await seed_diversified_books(session, schools, users, super_admin)
        # recarrega books para incluir diversificados nos loans
        all_books = (await session.scalars(select(Book).where(Book.isbn.like("9781REC%")))).all()
        await seed_loans_rec(session, all_books, schools, users)

    await engine.dispose()
    print("RECOMMENDATIONS seed completed")
    print("Teste: logue como student_rec_sch-rec-01_1 / rec123 e abra REC-A 01 - deve ver REC-A 04 (afinidade), REC-A 02/03 (contexto), REC-B 01 (tendência)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed recomendações")
    parser.add_argument("--reset", action="store_true", help="Limpa loans/reservations REC antes")
    args = parser.parse_args()
    asyncio.run(seed_recommendations(reset=args.reset))
