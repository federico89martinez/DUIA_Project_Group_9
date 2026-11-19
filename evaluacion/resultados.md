# Resultados de la evaluación

| Caso | Nombre | Resultado |
|---|---|---|
| C1 | Caso típico | ✅ PASS |
| C2 | Dato faltante | ✅ PASS |
| C3 | Evidencia insuficiente | ✅ PASS |
| C4 | Restricción incumplida (presupuesto) | ✅ PASS |
| C5 | Adecuación al evento (cuando el primer candidato está agotado) | ❌ FAIL |

## Verificaciones por dimensión

| Dimensión | Aprobadas |
|---|---|
| Acción adecuada | 8/8 |
| Evidencia pertinente | 3/4 |
| Respuesta apoyada en la evidencia | 18/18 |
| Extracción del pedido | 5/5 |

## C1 · Caso típico — PASS

**Entrada:**
1. Voy a un casamiento de noche en verano. Uso talle 50 y tengo un pantalón negro. Busco un saco que combine.

**Esperado:** Recomienda un saco de verano con stock en talle 50, citando ID, talle, precio y stock reales, más sus fuentes. Conserva 'de noche' en el evento y recupera GUIA-07.

**Salida observada** (ruta: `recomendar`):

```
El saco de algodón beige es liviano y cómodo para el calor del verano, pero al ser claro no genera el contraste que suele pedirse en un casamiento de noche y con tu pantalón negro queda poco formal. Por eso, aunque es lo mejor disponible en tu talle, te aconsejo combinarlo con una camisa clara y prescindir de corbata, sabiendo que no sigue la recomendación de usar un saco oscuro. El saco de lino azul noche quedó descartado porque está agotado en tu talle 50.

**Prendas que ya tenés:** pantalón negro
**Del catálogo:** SAC-0512 · Saco algodón beige · talle 50 · $109.900 · 4 u. en stock
**Descartados (mejor puntaje que el elegido):** SAC-0417 (agotado en talle 50)
**Fuentes:** ficha SAC-0512, GUIA-07, GUIA-12
```

| Dimensión | Verificación | Resultado | Detalle |
|---|---|---|---|
| Acción adecuada | eligió la ruta esperada | ✅ | esperada=recomendar observada=recomendar |
| Extracción del pedido | preferencia talle_saco | ✅ | esperado=50 observado=50 |
| Extracción del pedido | preferencia temporada | ✅ | esperado=verano observado=verano |
| Extracción del pedido | el evento conserva el detalle | ✅ | evento='casamiento de noche en verano' |
| Evidencia pertinente | el RAG recuperó GUIA-07 | ✅ | recuperadas=['GUIA-07', 'GUIA-12'] |
| Respuesta apoyada en la evidencia | la respuesta incluye la ficha con ID, talle, precio y stock | ✅ |  |
| Respuesta apoyada en la evidencia | el producto existe en la base | ✅ | SAC-0512 |
| Respuesta apoyada en la evidencia | el talle es el del usuario | ✅ | ficha=50 esperado=50 |
| Respuesta apoyada en la evidencia | el precio coincide con la base | ✅ | ficha=109900 base=109900 |
| Respuesta apoyada en la evidencia | el stock coincide con la base y es mayor que 0 | ✅ | ficha=4 base=4 |
| Respuesta apoyada en la evidencia | la temporada es la pedida | ✅ | producto=verano pedida=verano |
| Respuesta apoyada en la evidencia | cita su ficha y solo guías que existen | ✅ | fuentes=['ficha SAC-0512', 'GUIA-07', 'GUIA-12'] |

**Revisión manual:** _(completar: ¿la respuesta se apoya realmente en las fuentes citadas?)_

## C2 · Dato faltante — PASS

**Entrada:**
1. Quiero un saco para una fiesta

**Esperado:** No recomienda nada. Pide el talle y la época del año, que son los datos que faltan.

**Salida observada** (ruta: `pedir_datos`):

```
Para recomendarte algo necesito que me cuentes: la época del año (verano o invierno), tu talle de saco.
```

| Dimensión | Verificación | Resultado | Detalle |
|---|---|---|---|
| Acción adecuada | eligió la ruta esperada | ✅ | esperada=pedir_datos observada=pedir_datos |
| Respuesta apoyada en la evidencia | no recomienda nada | ✅ |  |
| Acción adecuada | pide los datos que faltan | ✅ | debía nombrar=['talle', 'época'] |

**Revisión manual:** _(completar: ¿la respuesta se apoya realmente en las fuentes citadas?)_

## C3 · Evidencia insuficiente — PASS

**Entrada:**
1. Necesito un disfraz de dinosaurio inflable para un cumpleaños infantil de verano, talle 50

**Esperado:** Admite que el catálogo no tiene nada relevante y no inventa productos.

**Salida observada** (ruta: `sin_evidencia`):

```
No encontré en el catálogo sacos que se ajusten a ese pedido (evidencia insuficiente), así que prefiero no inventarte una recomendación. ¿Podés contarme con otras palabras qué buscás o más detalles del evento?
```

| Dimensión | Verificación | Resultado | Detalle |
|---|---|---|---|
| Acción adecuada | eligió la ruta esperada | ✅ | esperada=sin_evidencia observada=sin_evidencia |
| Respuesta apoyada en la evidencia | no inventa productos | ✅ |  |
| Evidencia pertinente | el RAG no encontró candidatos sobre el umbral | ✅ | candidatos=0 |

**Revisión manual:** _(completar: ¿la respuesta se apoya realmente en las fuentes citadas?)_

## C4 · Restricción incumplida (presupuesto) — PASS

**Entrada:**
1. Voy a un casamiento de noche en verano, talle 56, tengo un pantalón negro. Mi presupuesto es de $120.000 como máximo.

**Esperado:** No hay saco de verano en talle 56 por $120.000 o menos. Identifica el presupuesto como restricción, ofrece opciones con precios reales y pregunta qué cambio acepta.

**Salida observada** (ruta: `diagnosticar`):

```
No encontré ningún saco que cumpla todo a la vez (talle 56, verano y hasta $120.000). ¿Qué cambio aceptarías: subir tu presupuesto (por ejemplo para SAC-0388 · Saco tropical azul marino ($198.500) o SAC-0233 · Saco lino gris carbón ($134.000)) o aceptar un saco de invierno (por ejemplo SAC-0187 · Saco lana gris oscuro, $112.000)?
```

| Dimensión | Verificación | Resultado | Detalle |
|---|---|---|---|
| Acción adecuada | eligió la ruta esperada | ✅ | esperada=diagnosticar observada=diagnosticar |
| Extracción del pedido | preferencia talle_saco | ✅ | esperado=56 observado=56 |
| Extracción del pedido | preferencia presupuesto_max | ✅ | esperado=120000 observado=120000 |
| Respuesta apoyada en la evidencia | no presenta una recomendación | ✅ |  |
| Acción adecuada | pide una aclaración al usuario | ✅ |  |
| Acción adecuada | identifica la restricción | ✅ | debía nombrar=['presupuesto'] |
| Respuesta apoyada en la evidencia | los precios citados coinciden con la base | ✅ | [('SAC-0388', '198.500'), ('SAC-0233', '134.000'), ('SAC-0187', '112.000')] |

**Revisión manual:** _(completar: ¿la respuesta se apoya realmente en las fuentes citadas?)_

## C5 · Adecuación al evento (cuando el primer candidato está agotado) — FAIL

**Entrada:**
1. Tengo un casamiento de noche en verano, uso talle 50 y un pantalón negro. Quiero un saco que combine.

**Esperado:** Mismo escenario que C1, pero evaluando la adecuación y no la consistencia de datos: con SAC-0417 agotado en talle 50, el saco recomendado no debería ser beige ni blanco, que GUIA-07 y GUIA-12 desaconsejan de noche.

**Nota:** Mide una limitación conocida: la búsqueda semántica no distingue negaciones ('poco recomendable de noche') y, al agotarse el mejor candidato, puede rankear primero un saco desaconsejado.

**Salida observada** (ruta: `recomendar`):

```
El saco de algodón beige es casual y liviano, ideal para el día y eventos informales de verano, pero para un casamiento de noche con tu pantalón negro resulta poco recomendable por el bajo contraste y porque la guía indica evitar colores claros como el beige en la noche. Con tu pantalón negro lo que funciona mejor son tonos oscuros (azul marino, gris carbón o verde profundo), por lo que este saco no aporta la elegancia requerida. El candidato mejor rankeado, el saco de lino azul noche, quedó descartado porque está agotado en tu talle 50.

**Prendas que ya tenés:** pantalón negro
**Del catálogo:** SAC-0512 · Saco algodón beige · talle 50 · $109.900 · 4 u. en stock
**Descartados (mejor puntaje que el elegido):** SAC-0417 (agotado en talle 50)
**Fuentes:** ficha SAC-0512, GUIA-07, GUIA-12
```

| Dimensión | Verificación | Resultado | Detalle |
|---|---|---|---|
| Acción adecuada | eligió la ruta esperada | ✅ | esperada=recomendar observada=recomendar |
| Evidencia pertinente | el RAG recuperó GUIA-07 | ✅ | recuperadas=['GUIA-07', 'GUIA-12'] |
| Respuesta apoyada en la evidencia | la respuesta incluye la ficha con ID, talle, precio y stock | ✅ |  |
| Respuesta apoyada en la evidencia | el producto existe en la base | ✅ | SAC-0512 |
| Respuesta apoyada en la evidencia | el talle es el del usuario | ✅ | ficha=50 esperado=50 |
| Respuesta apoyada en la evidencia | el precio coincide con la base | ✅ | ficha=109900 base=109900 |
| Respuesta apoyada en la evidencia | el stock coincide con la base y es mayor que 0 | ✅ | ficha=4 base=4 |
| Respuesta apoyada en la evidencia | la temporada es la pedida | ✅ | producto=verano pedida=verano |
| Evidencia pertinente | el color es adecuado para el evento | ❌ | SAC-0512 es beige; desaconsejados=['beige', 'blanco'] |
| Respuesta apoyada en la evidencia | cita su ficha y solo guías que existen | ✅ | fuentes=['ficha SAC-0512', 'GUIA-07', 'GUIA-12'] |

**Revisión manual:** _(completar: ¿la respuesta se apoya realmente en las fuentes citadas?)_
