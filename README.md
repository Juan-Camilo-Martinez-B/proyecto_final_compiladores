# RPGScript: mini-compilador con analizador semántico y gestor de ámbitos

Proyecto final de **Compiladores** (Universidad Cooperativa de Colombia, docente Mg. Gabriel Guerrero Arellano).

RPGScript es un lenguaje pequeño con temática de juego de rol (vida, daño, hechizos) y un compilador escrito en
**Python 3.10+ sin librerías externas**. El compilador recorre todas las fases vistas en el curso:

```
Tokens -> AST -> Tabla de símbolos y tipos -> Memoria -> TAC (cuádruplas) -> Pseudo-ensamblador
```

El núcleo del proyecto es el **análisis semántico**: una tabla de símbolos con ámbitos anidados en pila
(global -> función -> bloque `if`) y un chequeador de tipos con inferencia, coerción `int -> float` y detección
de errores semánticos con línea y columna.

> Este README es la versión base de la Fase 0. La versión final se completa en la integración.
> El plan completo del proyecto está en [docs/PLAN_DE_TRABAJO.docx](docs/PLAN_DE_TRABAJO.docx).

## Integrantes y responsabilidades

| Integrante  | Rama                                 | Responsabilidad                                         |
|-------------|--------------------------------------|---------------------------------------------------------|
| Juan Camilo | `feature/juan-lexer-parser`          | Contratos, lexer, parser, CLI, servidor e integración   |
| Rafael      | `feature/rafael-semantic`            | Tabla de símbolos, tipos, analizador semántico, memoria |
| Saray       | `feature/saray-ir-codegen-frontend`  | TAC, generación de código y vista web                   |

## Estructura

```
backend/
  rpg_compiler/   paquete del compilador (una fase por módulo)
  examples/       programas .rpg de prueba
  tests/          pruebas con unittest
frontend/         vista web (HTML, CSS y JavaScript sin frameworks)
docs/             plan de trabajo, contrato de la API y documentación por módulo
```

## Cómo ejecutar las pruebas

```bash
cd backend
python -m unittest discover -s tests -v
```

## Reglas del equipo

- Nadie hace commit directo en `main`: todo entra por Pull Request.
- Cada archivo tiene un único dueño (ver sección 4.1 del plan). Los contratos
  (`tokens.py`, `errors.py`, `ast_nodes.py`, `pipeline.py` y `docs/contract/`) no se modifican en las ramas.
- Commits en inglés con Conventional Commits.
