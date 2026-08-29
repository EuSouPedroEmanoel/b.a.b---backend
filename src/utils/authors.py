import re
import unicodedata


def slugify_author(name: str) -> str:
    name = name.strip()
    nfkd = unicodedata.normalize('NFKD', name)
    without_accents = ''.join(c for c in nfkd if not unicodedata.combining(c))
    lower = without_accents.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '-', lower)
    slug = slug.strip('-')
    return slug[:120] or 'autor'


def display_name_author(name: str) -> str:
    # preserva capitalização original mas trim
    return name.strip()[:120]
