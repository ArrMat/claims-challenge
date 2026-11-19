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

# Parte 2 - 
## Decision 1 - Como modelar la anulacion
- Decision tomada: Agregar campos voided_at y void_reason a ClaimPayment: Migracion chica, facil de filtrar, tiene todo lo solicitado, pero mezcla en el mismo modelo los datos del pago y de la anulacion. Opcionalmente: CheckConstraint como base que garantice que voided_at y void_reason se cargan juntos (o están los dos vacíos, o el motivo no está vacío. Así no puede existir un pago anulado sin motivo). 
- Opciones descartadas: 
  - Modelo aparte: separaria bien responsabilidades, pero cada consulta agregaria un JOIN y selec_related
  - Campo `status` (`active`/`voided`), ademas de campos `voided_at` y `void_reason`: se puede extender a mas status (por ej `pending`), pero estaria de mas para lo que se pide.
  - Pago negativo: Queda la historia completa y no se modifican filas, pero choca con las validaciones actuales y es confuso para la UI y el status

## Decision 2 - Que el pago anulado no se sume al total pagado
- Decision tomada: Un QuerySet con `.active()` (`ClaimPayment.objects.active()`, `claim.payments.active()`). Hoy lo pagado se calcula en dos lugares (`Claim.total_paid()` y la subquery `paid` de `claim_list`), y ambos pasan a usar `.active()`. Es explicito y el filtro queda definido en un solo lugar.
- Opciones descartadas:
  - Filtrar a mano (`voided_at__isnull=True`) en cada lugar: es lo mas simple, pero el dia que alguien agregue un tercer calculo se lo puede olvidar.
  - Manager por defecto que oculte los anulados: es peligroso, porque tambien los esconde del admin y del detalle, y se pide justamente que queden registrados y visibles.

## Decision 3 - Que el estado del siniestro quede coherente
- Decision tomada: Recalcular el estado a partir de los pagos activos con un unico metodo (`Claim.refresh_status()`), usado tanto al registrar un pago como al anularlo. Hoy `register_payment` sube el estado (OPEN → IN_REVIEW → SETTLED) pero nunca lo baja, asi que al anular un pago un siniestro podria quedar SETTLED con saldo pendiente. Reglas:
  - Si lo pagado cubre lo reclamado → SETTLED.
  - Si estaba SETTLED y ya no lo cubre → IN_REVIEW.
  - REJECTED no se toca.
  - No se vuelve a OPEN: que haya existido un pago ya indica que el siniestro fue revisado.
- Opciones descartadas:
  - Volver a OPEN si no queda ningun pago activo: defendible, pero se pierde un IN_REVIEW que pudo haberse puesto a mano.
  - Historial de estados: lo mas correcto, pero excede lo que se pide.

## Decision 4 - Donde va la logica
- Decision tomada: Un metodo en el modelo (`payment.void(reason)`). Corre dentro de `transaction.atomic()`, bloquea el siniestro con `select_for_update()` para que una anulacion y un pago simultaneos no dejen el estado mal calculado, rechaza un pago ya anulado y llama a `claim.refresh_status()`. Se puede reutilizar y testear sin pasar por la vista.
- Opciones descartadas:
  - En la vista (como `register_payment` hoy): no se puede reutilizar ni testear aislado.
  - Capa de servicios (`services.py`): una capa mas que no se justifica para una sola operacion.

## Decision 5 - Como se ve en pantalla
- Decision tomada: En el detalle del siniestro, un boton "Anular" por pago que lleva a un form chico con el motivo obligatorio y se envia por POST con CSRF. Los pagos anulados se siguen mostrando (tachados, con fecha y motivo de anulacion).
- Opciones descartadas:
  - Form inline o modal con `confirm()`: mas rapido de usar, pero con menos validacion visible del motivo.

# Parte 4 - FBV vs CBV

## 1. Qué clase base usaría para cada vista
| Vista | Clase base | Por qué |
|---|---|---|
| `dashboard` | `TemplateView` | Solo GET, no gira alrededor de un objeto ni un form. Todo va en `get_context_data()`. |
| `claim_list` | `ListView` | Es un listado paginado de un modelo: justo lo que resuelve. |
| `claim_detail` | `DetailView` | Un objeto por `pk` con 404 incluido; pagos y totales en `get_context_data()`. |
| `claim_create` | `CreateView` (+ `SuccessMessageMixin`) | `ModelForm` que crea un objeto y redirige. Es el caso de manual. |
| `register_payment` | `CreateView` | Crea un `ClaimPayment` desde un `ModelForm`, pero con varios overrides (ver abajo). |
| `void_payment` | `View` (o `FormView`) | No crea ni edita con `form.save()`: llama a `payment.void(reason)`. |

**`claim_list` → `ListView`**
- `get_queryset()`: el `select_related`, la subconsulta `paid_total` y los filtros (aseguradora, estado, `q`, fechas).
- `get_paginate_by()`: devuelve el `per_page` validado contra `PER_PAGE_OPTIONS`.
- `get_context_data()`: aseguradoras, estados, `filters` y `filters_qs`.
- Me da `paginator`, `page_obj` e `is_paginated` en el contexto sin escribirlos.
- Ojo, diferencias de comportamiento con lo que hice:
  - `ListView.paginate_queryset()` tira **404** con una página inválida o fuera de rango (salvo `page=last`). Hoy uso `Paginator.get_page()`, que muestra la primera/última. Para mantenerlo habría que sobreescribir `paginate_queryset()`.
  - El contexto cambia: `object_list`/`claims` pasa a ser la lista de la página y la página es `page_obj`. Habría que ajustar el template.

**`register_payment` → `CreateView`**
- `form_class = PaymentForm`, `template_name = "claims/payment_form.html"`.
- `setup()` o `dispatch()`: busca el `Claim` del `pk` de la URL (`get_object_or_404`), porque el objeto de la vista es el pago, no el siniestro.
- `get_context_data()`: agrega `claim`.
- `form_valid()`: se reemplaza entero (sin `super()`), porque el `super()` hace `form.save()` fuera de la transacción. Adentro va el `atomic()` + `select_for_update()` + `refresh_status()` y el mensaje.
- `get_success_url()`: al detalle del siniestro.
- La gano por el manejo de GET/POST/form inválido. Si sumara más lógica (ej. validar contra el saldo pendiente o el estado), pasaría a `FormView` o `View`.

**`void_payment` → `View`**
- Tiene un chequeo previo que redirige (pago ya anulado), un `Form` que no es `ModelForm` y la acción real es `payment.void()`, que puede fallar con `ValidationError`.
- Un `UpdateView` asume que el form guarda el objeto: tendría que pisar `get_form_kwargs()` (no le paso `instance`) y `form_valid()`. Casi nada del genérico se usaría.
- `FormView` + `get_object` en `setup()` también sirve; `View` con `get()`/`post()` queda más explícito.

## 2. Cuándo genérica y cuándo `View`

- **Genérica** cuando la vista es el patrón: listar un modelo, mostrar uno, crear/editar con un `ModelForm` y redirigir. Se escribe solo lo distinto (queryset, form, URL de éxito) y el resto es comportamiento conocido y testeado.
- **View simple** cuando la vista es una acción o no se parece al patrón:
  - acciones por POST (anular, aprobar, cambiar estado),
  - varios forms o varios modelos en la misma pantalla,
  - respuestas que no son HTML (JSON, CSV, redirects condicionales).
- **Cuando estorba**:
  - Si termino sobreescribiendo casi todos los hooks, o reemplazando `form_valid()`/`get()` sin llamar a `super()`, ya no uso el genérico: solo lo heredo.
  - Comportamientos por defecto que no se ven: el 404 de `ListView` con páginas inválidas, `form.save()` dentro de `form_valid()`, `self.object` que se setea en distintos momentos según la clase, nombres de template y de contexto inferidos.
  - `void_payment` es el ejemplo de este proyecto.

## 3. Leer y depurar código ajeno

**Ventajas de CBV**
- Menos código repetido y estructura uniforme: si el equipo conoce `ListView`, sabe dónde buscar (`get_queryset`, `get_context_data`, `form_valid`).
- GET y POST separados en métodos.
- Reutilización con mixins (`LoginRequiredMixin`, permisos, mensajes) en vez de copiar código.

**Desventajas con CBV**
- El flujo no está escrito en la vista: está repartido en la cadena de herencia (MRO). Para saber qué corre hay que conocer la jerarquía (ccbv.co.uk ayuda mucho).
- Hay cosas implícitas: variables del contexto (`object`, `page_obj`, `form`), nombres de template, `success_url`. Un `grep` en el proyecto no las encuentra.
- Los tracebacks y los breakpoints pasan por varias capas de Django antes de llegar a tu código.

**FBV**
- Se lee de arriba a abajo y lo que ves es lo que corre: depurar es poner un breakpoint y seguir.
- A cambio, cada vista resuelve lo mismo a su manera (paginación, 404, form inválido), y eso hay que leerlo cada vez.

En resumen: CBV es más rápido de leer **si conocés las clases base** y más lento si no. FBV siempre se lee igual.


# Extra: Problemas encontrados fuera del scope del challenge, cosas a solucionar con mas tiempo
- **Pagos sobre un siniestro rechazado o ya liquidado**: hoy se permiten, y uno rechazado puede pasar a liquidado. No está claro qué debería pasar.
  - **(SOLUCIONADO) un siniestro REJECTED que recibía pagos por el total pasaba a SETTLED**: Ahora sigue en REJECTED
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
- **Se puede pagar de más**. PaymentForm no compara el monto con el saldo pendiente. El pendiente puede quedar negativo, y anular un pago no lo corrige. Es un problema que ya venía de antes, pero con la anulación se nota más.
- La DB no rechaza un motivo de anulacion hecho solo de espacios
- Historial de estados del siniestro
- Busqueda LIKE '%q%': indice GIN con pg_trgm
- Autenticacion
  - No queda registrado quién anuló un pago