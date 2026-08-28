import math

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.schemas import FilterPage


async def paginate(session: AsyncSession, base_query, filter_page: FilterPage):
    """Return (items, total, page, size, pages) for a SELECT query.

    base_query should be a select(...) without limit/offset.
    """
    # Count query
    count_q = select(func.count()).select_from(base_query.subquery())
    total = await session.scalar(count_q) or 0

    page = filter_page.page
    size = filter_page.size
    pages = math.ceil(total / size) if total else 0

    paged = base_query.limit(filter_page.limit).offset(filter_page.offset)
    items = (await session.scalars(paged)).all()

    return items, total, page, size, pages


def paginated_response(items, total: int, page: int, size: int):
    pages = math.ceil(total / size) if total else 0
    return {
        'items': items,
        'total': total,
        'page': page,
        'size': size,
        'pages': pages,
    }
