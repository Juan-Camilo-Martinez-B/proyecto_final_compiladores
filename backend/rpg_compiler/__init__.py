"""Compilador de RPGScript: lexer, parser, analisis semantico, IR y codigo objetivo."""
# ======================================================================
# Paquete rpg_compiler: mapa de modulos, en el orden en que conviene leerlos
# ----------------------------------------------------------------------
# Contratos compartidos (los usan todas las fases):
#   tokens.py            tipos de token, palabras reservadas y simbolos
#   errors.py            diagnosticos y ErrorReporter
#   ast_nodes.py         nodos del arbol de sintaxis y el patron Visitor
#
# Fases del compilador, en orden de ejecucion:
#   1. lexer.py              texto -> tokens
#   2. parser.py             tokens -> AST
#   3. semantic_analyzer.py  AST -> AST con tipos (usa symbol_table.py y type_system.py)
#   4. memory_model.py       simbolos -> segmento global, frames y heap
#   5. ir_generator.py       AST -> cuadruplas (codigo de tres direcciones)
#   6. codegen.py            cuadruplas -> pseudo-ensamblador con registros
#      vm.py                 ejecuta las cuadruplas y muestra la salida
#
# Orquestador:
#   pipeline.py          compile_source(): conecta todas las fases y arma el JSON
# ======================================================================
