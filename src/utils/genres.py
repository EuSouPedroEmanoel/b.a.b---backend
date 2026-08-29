import re
import unicodedata


def slugify_genre(name: str) -> str:
    name = name.strip()
    # remove accents
    nfkd = unicodedata.normalize('NFKD', name)
    without_accents = ''.join(c for c in nfkd if not unicodedata.combining(c))
    lower = without_accents.lower().strip()
    # replace non-alphanum with dash
    slug = re.sub(r'[^a-z0-9]+', '-', lower)
    slug = slug.strip('-')
    return slug[:80] or 'genero'


# Mapeamento de gêneros em inglês (Google Books) -> português padrão
GENRE_TRANSLATION: dict[str, str] = {
    'fiction': 'Ficção',
    'nonfiction': 'Não-Ficção',
    'non-fiction': 'Não-Ficção',
    'biography': 'Biografia',
    'autobiography': 'Biografia',
    'history': 'História',
    'science': 'Ciência',
    'science fiction': 'Ficção Científica',
    'sci-fi': 'Ficção Científica',
    'fantasy': 'Fantasia',
    'mystery': 'Mistério',
    'thriller': 'Suspense',
    'horror': 'Terror',
    'romance': 'Romance',
    'adventure': 'Aventura',
    'humor': 'Humor',
    'comedy': 'Humor',
    'drama': 'Drama',
    'poetry': 'Poesia',
    'philosophy': 'Filosofia',
    'religion': 'Religião',
    'self-help': 'Autoajuda',
    'self help': 'Autoajuda',
    'health': 'Saúde',
    'business': 'Negócios',
    'economics': 'Economia',
    'education': 'Educação',
    'art': 'Arte',
    'music': 'Música',
    'cooking': 'Culinária',
    'travel': 'Viagem',
    'sports': 'Esportes',
    'children': 'Infantil',
    'juvenile': 'Infantojuvenil',
    'young adult': 'Jovem Adulto',
    'crime': 'Policial',
    'detective': 'Policial',
    'classic': 'Clássico',
    'literary': 'Literatura',
    'literature': 'Literatura',
    'general': 'Geral',
}


def canonical_genre_name(name: str) -> str:  # pragma: no cover
    raw = name.strip()  # pragma: no cover
    if not raw:  # pragma: no cover
        return raw  # pragma: no cover
    # slug sem acentos para comparar chave
    lower = slugify_genre(raw).replace('-', ' ')
    # também tenta lower direto sem slug
    key = raw.strip().lower()
    # tenta mapear por slug normalizado ou key direta
    for k, v in GENRE_TRANSLATION.items():
        k_slug = slugify_genre(k).replace('-', ' ')
        if lower == k_slug or key == k.lower():
            return v
    return raw


def display_name_genre(name: str) -> str:
    canonical = canonical_genre_name(name)
    return canonical.strip()[:80]
