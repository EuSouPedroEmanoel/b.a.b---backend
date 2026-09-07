from src.models import UserRole
from src.permissions import has_personal_reader_capability


def test_personal_reader_capability_preserves_reader_roles():
    assert has_personal_reader_capability(UserRole.STUDENT)
    assert has_personal_reader_capability(UserRole.TEACHER)


def test_personal_reader_capability_excludes_guest_and_staff():
    assert not has_personal_reader_capability('guest')
    assert not has_personal_reader_capability(UserRole.LIBRARIAN)
    assert not has_personal_reader_capability(None)
