# Vista web

Responsable: Saray. Carpeta: `frontend/`.

La vista web muestra la evolución del programa en cada fase del compilador y señala los errores en
la línea exacta. Está hecha con HTML, CSS y JavaScript con módulos ES, **sin frameworks ni
dependencias**: no hay nada que instalar ni que compilar.

## Cómo ejecutarla

```bash
cd backend
python server.py              # abre http://127.0.0.1:8000
```

El mismo `server.py` sirve la API y los archivos de `frontend/`, así que no hay problemas de CORS.

**Sin backend** (para trabajar solo en la interfaz):

```bash
cd frontend
python -m http.server 5500
# http://127.0.0.1:5500/?mock=ok       respuesta real de batalla_ok.rpg
# http://127.0.0.1:5500/?mock=errors   respuesta real de estres_semantico.rpg (13 errores, 1 warning)
```

No se debe abrir `index.html` con doble clic: los módulos ES no cargan desde `file://`.

Se puede abrir una pestaña directamente desde la URL: `#tokens`, `#ast`, `#symbols`, `#memory`,
`#ir` o `#assembly` (por ejemplo `http://127.0.0.1:8000/#assembly`).

## Estructura

| Archivo | Responsabilidad |
|---------|-----------------|
| `index.html` | Esqueleto: encabezado con la barra de pipeline, editor, pestañas y diagnósticos |
| `css/styles.css` | Tema oscuro (paleta de la sección 5.4 del plan) y diseño adaptable |
| `js/api.js` | `compileSource(source, registerCount)` y `fetchExamples()`. Con `?mock=ok\|errors` lee `mock/*.json` |
| `js/renderers.js` | Una función por vista con la firma `(container, data)` |
| `js/app.js` | Estado, eventos, pestañas y conexión entre la API y los renderers |
| `mock/response_ok.json`, `mock/response_errors.json` | Respuestas reales del compilador, generadas con `python main.py ... --json` |

Para regenerar los mocks después de un cambio en el backend:

```bash
cd backend
python main.py examples/batalla_ok.rpg --json > ../frontend/mock/response_ok.json
python main.py examples/estres_semantico.rpg --json > ../frontend/mock/response_errors.json
```

## Qué muestra cada parte

| Parte | Contenido |
|-------|-----------|
| **Editor** | `<textarea>` con números de línea sincronizados al hacer scroll. Las líneas con error se marcan en rojo y las que tienen warning en ámbar. Selector de ejemplos (`GET /api/examples`), selector de registros (2 a 8) y botón **Compilar** (también Ctrl + Enter). Tab inserta 4 espacios |
| **Barra de pipeline** | 6 etapas con flechas: verde = ok, rojo = error, gris = omitida, ámbar = no implementada. Un clic abre la pestaña de esa fase |
| **Tokens** | Tabla `#`, tipo, lexema, línea y columna, con un filtro de texto |
| **AST** | Árbol con `<details>` anidados: nodo, atributos clave, rol en el padre (`left`, `condition`...), insignia con el `inferred_type` y posición. Botones para expandir y colapsar todo |
| **Símbolos** | Tarjetas de ámbitos anidadas como en el código (global ⊃ función ⊃ if/else) con su tabla de símbolos. Debajo, la traza de la pila con un color por acción. **Reproducir** recorre la traza paso a paso y resalta el ámbito activo |
| **Memoria** | Segmento global como tabla, un bloque por cada frame de la pila (los slots de control en cursiva) y el heap de cadenas con direcciones. Una barra muestra el tamaño de cada slot |
| **TAC** | Tabla de cuádruplas `(op, arg1, arg2, result)` y, al lado, el listado TAC |
| **ASM** | Listado del ensamblador. Al pasar el cursor o hacer clic sobre una instrucción se ve el estado de R0..Rn en ese punto (`register_trace`), con los registros que cambiaron resaltados. Los spills van en rojo y las recargas en ámbar. Muestra contadores de registros, spills e instrucciones, y la tabla de spills |
| **Diagnósticos** | Icono por severidad, fase, `línea:columna` y mensaje. Un clic selecciona esa línea en el editor (`setSelectionRange`) |

Si una fase no se ejecutó (por errores anteriores), su pestaña dice "Esta fase no se ejecutó." y,
después de compilar, la vista salta a la última fase que sí produjo datos.

## Decisiones

- **Seguridad (XSS)**: todo dato de la API se inserta con `textContent` o `document.createElement`
  a través del helper `h(tag, props, ...children)` de `renderers.js`. No se usa `innerHTML` en
  ningún archivo. Un programa con `print("<script>...")` se muestra como texto.
- **Desacople**: los renderers solo conocen el contrato JSON (sección 4.4 del plan), no el backend.
  Por eso se pudieron desarrollar con los mocks antes de integrar.
- **Diseño adaptable**: por encima de 900 px, editor (40 %) y fases (60 %) en dos columnas. Por
  debajo, una sola columna.
