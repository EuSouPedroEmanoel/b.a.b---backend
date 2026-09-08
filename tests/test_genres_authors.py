from http import HTTPStatus


def test_list_genres_empty(client, token):
    resp = client.get('/genres/', headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == HTTPStatus.OK
    assert resp.json() == {
        'items': [], 'total': 0, 'page': 1, 'size': 10, 'pages': 0
    }


def test_create_genre_success(client, super_admin_token):
    resp = client.post(
        '/genres/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={'name': 'Ficção Científica'},
    )
    assert resp.status_code == HTTPStatus.CREATED
    assert resp.json()['name'] == 'Ficção Científica'
    assert 'slug' in resp.json()


def test_create_genre_conflict(client, super_admin_token):
    client.post(
        '/genres/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={'name': 'Romance'},
    )
    resp = client.post(
        '/genres/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={'name': 'Romance'},
    )
    assert resp.status_code == HTTPStatus.CONFLICT


def test_create_genre_invalid(client, super_admin_token):
    resp = client.post(
        '/genres/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={'name': ''},
    )
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_get_genre_success(client, token, super_admin_token):
    created = client.post(
        '/genres/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={'name': 'Aventura Teste'},
    )
    assert created.status_code == HTTPStatus.CREATED
    genre = client.get(
        f"/genres/{created.json()['id']}",
        headers={'Authorization': f'Bearer {token}'},
    )
    assert genre.status_code == HTTPStatus.OK
    assert genre.json() == created.json()


def test_list_genres_with_q(client, super_admin_token):
    created = client.post('/genres/', headers={'Authorization': f'Bearer {super_admin_token}'}, json={'name': 'Biografia'})
    assert created.status_code == HTTPStatus.CREATED
    resp = client.get('/genres/?q=Biograf', headers={'Authorization': f'Bearer {super_admin_token}'})
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()['total'] == 1
    assert [item['id'] for item in resp.json()['items']] == [created.json()['id']]


def test_delete_genre_forbidden(client, token, super_admin_token):
    created = client.post('/genres/', headers={'Authorization': f'Bearer {super_admin_token}'}, json={'name': 'Protegido'})
    assert created.status_code == HTTPStatus.CREATED
    resp = client.delete(f"/genres/{created.json()['id']}", headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == HTTPStatus.FORBIDDEN


def test_delete_genre_success(client, super_admin_token):
    create = client.post(
        '/genres/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={'name': 'Para Deletar Gen'},
    )
    assert create.status_code == HTTPStatus.CREATED
    gid = create.json()['id']
    delete = client.delete(f'/genres/{gid}', headers={'Authorization': f'Bearer {super_admin_token}'})
    assert delete.status_code == HTTPStatus.OK
    assert client.get(f'/genres/{gid}', headers={'Authorization': f'Bearer {super_admin_token}'}).status_code == HTTPStatus.NOT_FOUND


def test_list_authors_empty(client, token):
    resp = client.get('/authors/', headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()['items'] == []
    assert resp.json()['total'] == 0


def test_create_author_success(client, super_admin_token):
    resp = client.post(
        '/authors/',
        headers={'Authorization': f'Bearer {super_admin_token}'},
        json={'name': 'Clarice Lispector'},
    )
    assert resp.status_code == HTTPStatus.CREATED
    assert 'slug' in resp.json()


def test_create_author_conflict(client, super_admin_token):
    client.post('/authors/', headers={'Authorization': f'Bearer {super_admin_token}'}, json={'name': 'Machado de Assis'})
    resp = client.post('/authors/', headers={'Authorization': f'Bearer {super_admin_token}'}, json={'name': 'Machado de Assis'})
    assert resp.status_code == HTTPStatus.CONFLICT


def test_create_author_invalid(client, super_admin_token):
    resp = client.post('/authors/', headers={'Authorization': f'Bearer {super_admin_token}'}, json={'name': ''})
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_list_authors_with_q(client, super_admin_token):
    created = client.post('/authors/', headers={'Authorization': f'Bearer {super_admin_token}'}, json={'name': 'Jorge Amado'})
    assert created.status_code == HTTPStatus.CREATED
    resp = client.get('/authors/?q=Jorge', headers={'Authorization': f'Bearer {super_admin_token}'})
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()['total'] == 1
    assert [item['id'] for item in resp.json()['items']] == [created.json()['id']]


def test_get_author_not_found(client, token):
    resp = client.get('/authors/99999', headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == HTTPStatus.NOT_FOUND


def test_delete_author_forbidden(client, token, super_admin_token):
    created = client.post('/authors/', headers={'Authorization': f'Bearer {super_admin_token}'}, json={'name': 'Autor Protegido'})
    assert created.status_code == HTTPStatus.CREATED
    resp = client.delete(f"/authors/{created.json()['id']}", headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == HTTPStatus.FORBIDDEN


def test_delete_author_success(client, super_admin_token):
    create = client.post('/authors/', headers={'Authorization': f'Bearer {super_admin_token}'}, json={'name': 'Autor Para Deletar'})
    assert create.status_code == HTTPStatus.CREATED
    aid = create.json()['id']
    delete = client.delete(f'/authors/{aid}', headers={'Authorization': f'Bearer {super_admin_token}'})
    assert delete.status_code == HTTPStatus.OK
    assert client.get(f'/authors/{aid}', headers={'Authorization': f'Bearer {super_admin_token}'}).status_code == HTTPStatus.NOT_FOUND


def test_book_create_with_genre_author_names(client, token):
    resp = client.post(
        '/books/',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'title': 'Livro Com Genero Autor',
            'description': 'desc',
            'genre_names': ['Ficção', 'Romance'],
            'author_names': ['Autor Teste Um', 'Autor Teste Dois'],
        },
    )
    assert resp.status_code == HTTPStatus.CREATED
    data = resp.json()
    assert data['genre_names'] == ['Ficção', 'Romance']
    assert [author['name'] for author in data['authors']] == [
        'Autor Teste Um', 'Autor Teste Dois'
    ]


def test_book_create_with_genre_ids(client, token, super_admin_token):
    # create genres via API to get ids
    g1 = client.post('/genres/', headers={'Authorization': f'Bearer {super_admin_token}'}, json={'name': 'Genero ID 1'}).json()
    g2 = client.post('/genres/', headers={'Authorization': f'Bearer {super_admin_token}'}, json={'name': 'Genero ID 2'}).json()
    # may conflict if already exists, fallback to list
    if 'id' not in g1:
        g1 = client.get('/genres/?q=Genero ID 1', headers={'Authorization': f'Bearer {token}'}).json()['items'][0]
    if 'id' not in g2:
        g2 = client.get('/genres/?q=Genero ID 2', headers={'Authorization': f'Bearer {token}'}).json()['items'][0]
    resp = client.post(
        '/books/',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'title': 'Livro Com Genre IDs',
            'genre_ids': [g1['id'], g2['id']],
        },
    )
    assert resp.status_code == HTTPStatus.CREATED
    assert {genre['id'] for genre in resp.json()['genres']} == {g1['id'], g2['id']}


def test_book_patch_clear_genres_authors(client, token):
    create = client.post('/books/', headers={'Authorization': f'Bearer {token}'}, json={'title': 'Livro Patch Clear', 'genre_names': ['Temp']})
    bid = create.json()['id']
    assert create.status_code == HTTPStatus.CREATED
    patch = client.patch(f'/books/{bid}', headers={'Authorization': f'Bearer {token}'}, json={'genre_ids': [], 'genre_names': [], 'author_ids': [], 'author_names': []})
    assert patch.status_code == HTTPStatus.OK
    assert patch.json()['genres'] == []
    assert patch.json()['authors'] == []


def test_list_books_q_genre_author(client, token):
    # create book with known genre/author then query via q
    created = client.post(
        '/books/',
        headers={'Authorization': f'Bearer {token}'},
        json={'title': 'UniqueTitleXYZ', 'genre_names': ['MisterioQ'], 'author_names': ['AutorQUnico']},
    )
    assert created.status_code == HTTPStatus.CREATED
    resp = client.get('/books/?q=MisterioQ', headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == HTTPStatus.OK
    assert resp.json()['total'] == 1
    assert [i['id'] for i in resp.json()['items']] == [created.json()['id']]
    resp2 = client.get('/books/?q=AutorQUnico', headers={'Authorization': f'Bearer {token}'})
    assert resp2.status_code == HTTPStatus.OK
    assert resp2.json()['total'] == 1
    assert [i['id'] for i in resp2.json()['items']] == [created.json()['id']]


def test_list_books_sort_author(client, token):
    resp = client.get('/books/?sort_by=author&sort_order=asc', headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == HTTPStatus.OK
    resp2 = client.get('/books/?sort_by=author&sort_order=desc', headers={'Authorization': f'Bearer {token}'})
    assert resp2.status_code == HTTPStatus.OK


def test_suggest_books_genre_author(client, token):
    # create book then suggest via genre/author term
    client.post('/books/', headers={'Authorization': f'Bearer {token}'}, json={'title': 'Sugestao Livro', 'genre_names': ['SugestGenero'], 'author_names': ['SugestAutor']})
    resp = client.get('/books/suggest?q=SugestGenero', headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == HTTPStatus.OK
    resp2 = client.get('/books/suggest?q=SugestAutor', headers={'Authorization': f'Bearer {token}'})
    assert resp2.status_code == HTTPStatus.OK


def test_utils_parse_published_date():
    from src.utils.apis import _parse_published_date  # noqa: PLC2701

    assert _parse_published_date('2020') == '2020-01-01'
    assert _parse_published_date('2020-05') == '2020-05-01'
    assert _parse_published_date('2020-05-17') == '2020-05-17'
    assert _parse_published_date('') is None
    assert _parse_published_date(None) is None
    assert _parse_published_date('invalid') is None
    assert _parse_published_date('2020-13-01') is None


def test_utils_genres_authors_display():
    from src.utils.authors import display_name_author, slugify_author
    from src.utils.genres import display_name_genre, slugify_genre

    assert display_name_genre('fiction') == 'Ficção'
    assert display_name_genre('  Ficção  ') == 'Ficção'
    assert slugify_genre('Ficção') == 'ficcao'
    assert display_name_author('  machado de assis ') == 'machado de assis'
    assert slugify_author('Machado de Assis') == 'machado-de-assis'
