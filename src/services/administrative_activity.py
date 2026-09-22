from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.models import AdministrativeActivity, User


def record_activity(  # noqa: PLR0913
    session: AsyncSession,
    actor: User,
    *,
    operation: str,
    entity_type: str,
    summary: str,
    entity_id: int | str | None = None,
    school_id: int | None = None,
    changed_fields: dict | None = None,
    justification: str | None = None,
) -> AdministrativeActivity:
    """Stage an activity in the caller's transaction; never commits itself."""
    activity = AdministrativeActivity(
        id=str(uuid4()),
        actor_id=actor.id,
        actor_display_name=(actor.name or actor.username)[:120],
        actor_role=actor.role.value,
        school_id=school_id,
        operation=operation,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        summary=summary[:240],
        changed_fields=changed_fields,
        justification=justification,
    )
    session.add(activity)
    return activity
