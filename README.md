# Gestión de Siniestros

App interna para administrar siniestros (claims) de pólizas de seguro: aseguradoras,
clientes, pólizas, siniestros y los pagos de cada siniestro.

Stack: **Django + PostgreSQL + Docker**.

## Cómo levantarlo

Requisitos: Docker y Docker Compose. No necesitás Python ni Postgres locales.

```bash
cp .env.example .env
docker compose up --build
```

Al arrancar, el contenedor espera a Postgres, aplica migraciones y carga datos de
prueba (solo la primera vez). Abrí <http://localhost:8000>.

Para el admin de Django, creá un usuario:

```bash
docker compose exec web python manage.py createsuperuser
```

## Comandos útiles

```bash
docker compose exec web python manage.py makemigrations
docker compose exec web python manage.py migrate
docker compose exec web python manage.py test
docker compose exec web python manage.py shell
docker compose logs -f web
```

Para reiniciar con la base limpia: `docker compose down -v && docker compose up --build`.

## Estructura

```
app/
├── config/                 # settings, urls
├── claims/                 # la app
│   ├── models.py
│   ├── forms.py
│   ├── views.py
│   ├── urls.py
│   ├── admin.py
│   ├── tests.py
│   ├── templates/claims/
│   └── management/commands/
│       ├── wait_for_db.py
│       └── seed_demo.py    # datos de prueba
├── templates/base.html
└── static/css/app.css
```

## Modelo de datos (resumen)

- `Insurer` — aseguradora.
- `Client` — asegurado.
- `Policy` — póliza de un cliente con una aseguradora.
- `Claim` — siniestro denunciado sobre una póliza.
- `ClaimPayment` — pagos realizados sobre un siniestro.
