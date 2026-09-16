"""Resolve the bibliographic view of a book for a school.

The Book row is the shared catalogue record.  This module is the only place
where callers should combine it with a school-specific override.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import (
    Author,
    Book,
    BookSchoolOverride,
    Genre,
)


@dataclass(frozen=True)
class EffectiveBook:
    base: Book
    override: BookSchoolOverride | None
    title: str
    description: str | None
    cover_url: str | None
    published_date: date | None
    genres: list[Genre]
    authors: list[Author]


async def load_book_overrides(
    session: AsyncSession,
    book_ids: list[int],
    school_id: int | None,
) -> dict[int, BookSchoolOverride]:
    if not book_ids or school_id is None:
        return {}
    rows = (
        await session.scalars(
            select(BookSchoolOverride)
            .options(
                selectinload(BookSchoolOverride.genres),
                selectinload(BookSchoolOverride.authors),
            )
            .where(
                BookSchoolOverride.school_id == school_id,
                BookSchoolOverride.book_id.in_(book_ids),
            )
        )
    ).all()
    return {row.book_id: row for row in rows}


def resolve_book(
    book: Book,
    override: BookSchoolOverride | None,
) -> EffectiveBook:
    if override is None:
        return EffectiveBook(
            base=book,
            override=None,
            title=book.title,
            description=book.description,
            cover_url=book.cover_url,
            published_date=book.published_date,
            genres=list(book.genres or []),
            authors=list(book.authors or []),
        )
    return EffectiveBook(
        base=book,
        override=override,
        title=override.title if override.title_overridden else book.title,
        description=(
            override.description
            if override.description_overridden
            else book.description
        ),
        cover_url=(
            override.cover_url
            if override.cover_url_overridden
            else book.cover_url
        ),
        published_date=(
            override.published_date
            if override.published_date_overridden
            else book.published_date
        ),
        genres=(
            list(override.genres)
            if override.genres_overridden
            else list(book.genres or [])
        ),
        authors=(
            list(override.authors)
            if override.authors_overridden
            else list(book.authors or [])
        ),
    )


async def resolve_books(
    session: AsyncSession,
    books: list[Book],
    school_id: int | None,
) -> list[EffectiveBook]:
    overrides = await load_book_overrides(
        session, [book.id for book in books], school_id
    )
    return [resolve_book(book, overrides.get(book.id)) for book in books]


async def resolve_one(
    session: AsyncSession,
    book: Book,
    school_id: int | None,
) -> EffectiveBook:
    resolved = await resolve_books(session, [book], school_id)
    return resolved[0]


def public_book(book: EffectiveBook, guest: bool = False) -> dict:
    base = book.base
    genres = [
        {'id': item.id, 'name': item.name, 'slug': item.slug}
        for item in book.genres
    ]
    authors = [
        {'id': item.id, 'name': item.name, 'slug': item.slug}
        for item in book.authors
    ]
    payload = {
        'id': base.id,
        'title': book.title,
        'description': book.description,
        'isbn': base.isbn,
        'cover_url': book.cover_url,
        'published_date': book.published_date,
        'is_active': base.is_active,
        'genres': genres,
        'genre_ids': [item['id'] for item in genres],
        'genre_names': [item['name'] for item in genres],
        'authors': authors,
        'author_ids': [item['id'] for item in authors],
        'author_names': [item['name'] for item in authors],
    }
    if not guest:
        payload.update(
            {
                'added_by': base.added_by,
                'edited_by': base.edited_by,
                'created_at': base.created_at,
                'updated_at': base.updated_at,
            }
        )
    return payload


def customization_fields(override: BookSchoolOverride | None) -> list[str]:
    if override is None:
        return []
    fields: list[str] = []
    for name in (
        'title',
        'description',
        'cover_url',
        'published_date',
        'genres',
        'authors',
    ):
        if getattr(override, f'{name}_overridden'):
            fields.append(name)
    return fields


def effective_column(
    column, override_column, override_flag, school_id: int | None
):
    """Return a SQL expression for a scalar effective field.

    The caller must outer-join ``BookSchoolOverride`` for the requested school
    before using this expression.
    """
    if school_id is None:
        return column
    return case((override_flag.is_(True), override_column), else_=column)


def effective_title_expression(school_id: int | None):
    return effective_column(
        Book.title,
        BookSchoolOverride.title,
        BookSchoolOverride.title_overridden,
        school_id,
    )


def effective_description_expression(school_id: int | None):
    return effective_column(
        Book.description,
        BookSchoolOverride.description,
        BookSchoolOverride.description_overridden,
        school_id,
    )


def effective_published_date_expression(school_id: int | None):
    return effective_column(
        Book.published_date,
        BookSchoolOverride.published_date,
        BookSchoolOverride.published_date_overridden,
        school_id,
    )


def customization_state(
    book_id: int,
    school_id: int,
    override: BookSchoolOverride | None,
) -> dict:
    return {
        'book_id': book_id,
        'school_id': school_id,
        'has_override': override is not None,
        'overridden_fields': customization_fields(override),
    }
