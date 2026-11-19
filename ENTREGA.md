# Tickets de soporte

## Ticket 1
- **Causa**: `Claim.total_paid()` devuelve `None` cuando el siniestro no tiene pagos, porque `SUM` sobre cero filas da `NULL` y `aggregate(...)` lo entrega como `{"total": None}`, no como `0`. Eso rompe `pending_amount()` (`Decimal("None")` lanza `InvalidOperation`) y la comparación en `views.py:87` (`None >= ...` lanza `TypeError`).
  ```python
  def total_paid(self):
      return self.payments.aggregate(total=Sum("amount"))["total"]
  ```
- **Cómo se encontró**: al abrir el detalle de un siniestro sin pagos, el traceback de Django señalaba `claims/models.py, line 82, in pending_amount: return self.amount_claimed - Decimal(str(self.total_paid()))`. Seguí la llamada hasta `total_paid()` y vi que devolvía `None`. Al buscar los usos de `total_paid()`, encontré el mismo problema en `views.py`.
- **Cómo se solucionó**: `total_paid()` devuelve `0` si no hay pagos. Agregué un test sobre un siniestro sin pagos, que falla con el código original.
  ```python
  def total_paid(self):
      return self.payments.aggregate(total=Sum("amount"))["total"] or 0
  ```

## Ticket 2
- **Causa**: en `views.py:dashboard`, el contador "Denunciados por mes" filtraba solo por número de mes (`reported_at__month=today.month`) y no por año. Entonces sumaba los siniestros del mismo mes de cualquier año (marzo de 2026 + marzo de 2025, etc.).
- **Cómo se encontró**: el ticket decía que el contador de "Denunciados por mes" mostraba más siniestros de los esperados. Seguí el dato desde el template hasta la vista (`dashboard.html` → `views.py:dashboard`) y encontré el filtro sin año.
- **Cómo se solucionó**: se agregó el filtro por año.
  ```python
  "reported_this_month": Claim.objects.filter(
      reported_at__year=today.year, reported_at__month=today.month
  ).count(),
  ```

## Ticket 3
- **Causa**: `views.py:claim_list` no escalaba con la cantidad de siniestros:
  - **Sin paginación**: renderizaba todos los siniestros que pasaban los filtros.
  - **N+1 en el template**: por cada fila, `claim.policy.client`, `claim.policy.insurer` y `claim.total_paid` (un `aggregate` por siniestro) hacían queries aparte.
  - **Búsqueda `q` en Python**: recorría `Claim.objects.all()`, la tabla entera sin tener en cuenta los otros filtros, con 2 queries por siniestro (`claim.policy.client`). Después devolvía los ids encontrados en un `WHERE id IN (...)` que podía ser enorme.
  - **Filtro por aseguradora**: hacía una query aparte para traer los ids de las pólizas y los pasaba en un `WHERE policy_id IN (...)`. Además, un `insurer` no numérico (`?insurer=abc`) levantaba `ValueError` y daba un 500.
- **Cómo se encontró**: el ticket menciona el listado de siniestros, así que seguí el dato desde el template hasta la vista (`claim_list.html` → `views.py:claim_list`).
- **Cómo se solucionó**: ahora cada página se resuelve con 3 queries fijas (el count del paginador, la página y las aseguradoras), sin importar cuántos siniestros o pagos haya.
  - **Relaciones**: `select_related("policy__client", "policy__insurer")` las trae en la misma query.
  - **Total pagado**: se calcula con una subconsulta correlacionada (`paid_total`), solo para las filas de la página. Se descartó `annotate(Sum(...))` porque el `GROUP BY` obliga a agregar todo el conjunto filtrado, encarece el count y hace que Django ignore el `Meta.ordering`. La anotación se llama `paid_total` porque `total_paid` es un método del modelo y lo pisaría.
  - **Búsqueda**: se resuelve en SQL. `Concat` arma el nombre completo, así "juan pér" sigue encontrando a "Juan Pérez", e `icontains` mantiene la búsqueda parcial sin distinguir mayúsculas y minúsculas.
  - **Aseguradora**: se filtra con un join (`policy__insurer_id`). Un valor no numérico se ignora.
  - **Paginación**: usa el `Paginator` de Django. El tamaño de página se elige entre 20, 50, 100, 500 y 1000 (20 por defecto, y cualquier otro valor vuelve a 20). Los números de página inválidos no dan 404, y los links conservan los filtros.
  - **Nuevo filtro opcional por fecha**: `Desde` / `Hasta` sobre `reported_at`, con los dos extremos incluidos. Una fecha inválida se ignora.
  ```python
  paid = (
      ClaimPayment.objects.filter(claim=OuterRef("pk"))
      .order_by()
      .values("claim")
      .annotate(total=Sum("amount"))
      .values("total")
  )
  claims = Claim.objects.select_related("policy__client", "policy__insurer").annotate(
      paid_total=Coalesce(Subquery(paid), Value(Decimal("0")))
  )

  if insurer_id and insurer_id.isdigit():
      claims = claims.filter(policy__insurer_id=insurer_id)
  ...
  if search:
      claims = claims.annotate(
          client_name=Concat("policy__client__first_name", Value(" "), "policy__client__last_name")
      ).filter(Q(client_name__icontains=search) | Q(number__icontains=search))
  ...
  page = Paginator(claims, per_page).get_page(request.GET.get("page"))
  ```
  - **Tests**: los de listado que ya existían pasan sin cambios. Se agregaron:
    - **paginación**: orden, links con filtros y páginas inválidas;
    - **`per_page`**: valor elegido y valores inválidos;
    - **rango de fechas**;
    - **aseguradora**: sin queries extra y con valor inválido;
    - **cantidad de queries**: dos `assertNumQueries(3)`, uno sin búsqueda y otro con `q`.
  - **Límite conocido**: `LIKE '%...%'` no usa índices btree. Si la búsqueda se vuelve lenta, se agrega un índice GIN con `pg_trgm`.

# Problemas encontrados, fuera del scope del challenge
- **Pagos sobre un siniestro rechazado o ya liquidado**: hoy se permiten, y uno rechazado puede pasar a liquidado. No está claro qué debería pasar.
- El `email` de `class Client` no es unico, es posible que sea intencional. En caso de querer corregirlo habria que crear y aplicar una migracion (makemigrations y migrate). Si ya hay clientes con correos repetidos, la migración fallaria hasta corregir esos datos. En caso de hacerlo, tener en cuenta que la restriccion distingue mayusculas de minusculas
- **(SOLUCIONADO) `ClaimPayment.amount` era `FloatField`**, a diferencia del resto de los montos de dinero (`DecimalField`), lo que podía causar errores de redondeo (p. ej. `0.70 + 0.10 = 0.7999999999999999`, y un siniestro pagado completo no quedaba liquidado).
  - Se cambió a `DecimalField(max_digits=14, decimal_places=2)` y se generó la migración.
  - Se eliminaron las conversiones a `float` en `views.py` (comparación para liquidar) y en `seed_demo.py`.
  - Riesgo de la migración: PostgreSQL redondea cada valor a 2 decimales; solo cambiaría un saldo si había montos con más de 2 decimales reales. Se verificó con consultas previas que ningún pago ni total por siniestro cambia.
  - Se agregó un test que reproduce el caso (`0.70 + 0.10` sobre un siniestro de `0.80` debe quedar liquidado).
- **(SOLUCIONADO) El monto de `ClaimPayment` podía ser no positivo**: la única validación estaba en el form.
  - Se agregó `MinValueValidator(Decimal("0.01"))` al campo (valida en forms/`full_clean`).
  - Se agregó `CheckConstraint(condition=Q(amount__gt=0), name="claimpayment_amount_positive")` para garantizarlo a nivel base de datos, aunque se guarde sin pasar por el form.
  - Incluido en la misma migración.