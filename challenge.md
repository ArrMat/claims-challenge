# Challenge Técnico

## Contexto

En VISRED trabajamos con **Django + PostgreSQL**. El rol combina **soporte** (diagnosticar y resolver problemas en código que ya está en producción) con **desarrollo** de nuevas funcionalidades.

Por eso este challenge no es construir algo desde cero: te damos una **app que ya funciona**, con tickets reales de usuarios para resolver y una funcionalidad nueva para agregar.

No buscamos que hagas más, sino que lo que hagas lo entiendas a fondo.

> **Sobre el uso de IA:** podés usarla, nosotros también la usamos. Pero el challenge termina con una **defensa** donde vamos a recorrer tu solución y te vamos a pedir que expliques cada decisión, cómo llegaste a cada diagnóstico y qué alternativas descartaste.

## La app

Una gestión interna de **siniestros**: aseguradoras, clientes, pólizas, siniestros denunciados y los pagos de cada siniestro. Viene con Docker + PostgreSQL y datos de prueba que se cargan solos. Seguí el `README.md` del proyecto para levantar.

> Si algo del setup no te arranca, avisanos asi no perdes tiempo.

**Convención:** todo el código va en **inglés** (menos rutas expuestas al usuario y comentarios decada dev).

## Parte 1 — Tickets de soporte

Recibimos estos reportes de usuarios. Para cada uno: **analizalo, encontrá la causa raíz y resolvelo.**

**Ticket #1**
> "Cuando entro a ver un siniestro que se denunció hace poco, me sale una pantalla de error con codigo que no se entiende nada. Con otros siniestros anda bien."

**Ticket #2**
> "El tablero dice que este mes se denunciaron muchos más siniestros de los que realmente cargamos. Los números no nos cierran."

**Ticket #3**
> "Por ahora el listado de siniestros anda bien, pero sabemos que la base va a crecer mucho. Nos preocupa que se ponga lento, sobre todo al filtrar y buscar."

Una aclaración sobre el #3: el dataset de prueba es chico, así que es probable que **no lo notes lento**. Pero el código tiene problemas que con un volumen real de producción (cientos de miles de siniestros) dejarían la pantalla inutilizable. Queremos que los identifiques, expliques **por qué escalan mal** y los corrijas.

## Parte 2 — Funcionalidad nueva

> **Pedido del área de siniestros:** "A veces cargamos un pago por error (monto equivocado, siniestro equivocado, pago duplicado). Necesitamos poder **anular un pago**. No queremos que se borre: tiene que quedar registrado que existió, cuándo se anuló y por qué. Un pago anulado no debe contar en lo pagado del siniestro, y el estado del siniestro tiene que quedar coherente después de la anulación."

Cómo lo implementás (modelo, dónde va la lógica, cómo se ve en pantalla) queda a tu criterio. Contanos qué decidiste y por qué.

## Parte 3 — Tests

La app no tiene tests. Escribí **al menos un test por cada ticket que resuelvas**, que falle con el código original y pase con tu arreglo. Si querés sumar tests de la funcionalidad nueva, mejor.


## Parte 4 — Pregunta para investigar

Esta app está escrita con **vistas basadas en funciones (FBV)**. En VISRED trabajamos casi siempre con **vistas basadas en clases (CBV)**: `View`, `ListView`, `CreateView`, `UpdateView`, `TemplateView`.

No te pedimos que conviertas la app. pero si que investigues y respondas por escrito en tu `ENTREGA.md`:

1. Si tuvieras que pasar estas vistas a CBV, **¿qué clase base usarías para cada una y por qué?** En particular `claim_list` y `register_payment`.
2. **¿Cuándo conviene una CBV genérica** (`ListView`, `CreateView`) y cuándo una `View` simple? ¿Hay casos en los que una genérica estorba más de lo que ayuda?
3. ¿Qué ganás y qué perdés con CBV frente a FBV a la hora de **leer y depurar** código ajeno?

Si en algún ticket te resulta natural resolverlo con una CBV (por ejemplo, el listado), podés hacerlo, contanos por qué.

## Entrega

- Subí tu solución a un repositorio en **GitHub o GitLab** (público, o privado dándonos acceso) y pasanos el link.
- **Commiteá a medida que avanzás**, idealmente un commit (o varios) por ticket y por la funcionalidad. Nos interesa ver cómo trabajás.
- Agregá un archivo **`ENTREGA.md`** con:
  - **Por cada ticket:** qué lo causaba, **cómo lo encontraste** (qué miraste, qué probaste) y cómo lo arreglaste.
  - **Para la funcionalidad:** qué decisiones tomaste y qué alternativas descartaste.
  - Tus respuestas a la **pregunta para investigar** (Parte 4).
  - Qué harías con más tiempo.
- Si algo no llegaste a resolver, escribilo igual: contanos hasta dónde llegaste y qué sospechás. Valoramos más un diagnóstico honesto a medias que una solución que no sabés explicar.

## La defensa

Después de la entrega coordinamos una **llamada** para recorrer tu solución juntos. Tené el proyecto levantado: puede que te pidamos navegar el código, explicar algo en vivo o razonar sobre escenarios que no están en el challenge.