"""Pruebas de la pila de ambitos: visibilidad, redeclaracion, shadowing y traza."""
# ======================================================================
# Pruebas de la tabla de simbolos (symbol_table.py).
# Verifican la pila de ambitos: lookup en el ambito actual, en el padre y en
# el abuelo; que una variable deja de ser visible tras exit_scope; la
# redeclaracion, el shadowing y la traza de operaciones.
#
# Ejecutar (desde backend/): python -m unittest tests.test_symbol_table -v
# ======================================================================
import unittest

from rpg_compiler.symbol_table import Symbol, SymbolTable


def symbol(name, line=1, type_name="int", kind="variable"):
    return Symbol(name=name, type_name=type_name, kind=kind, scope_name="",
                  level=-1, line=line, column=1)


class SymbolTableTest(unittest.TestCase):
    def test_lookup_finds_a_name_in_the_current_scope(self):
        table = SymbolTable()
        table.define(symbol("vida"))
        found = table.lookup("vida", line=2)
        self.assertIsNotNone(found)
        self.assertEqual(found.scope_name, "global")
        self.assertEqual(found.level, 0)

    def test_lookup_walks_to_the_parent_scope(self):
        table = SymbolTable()
        table.define(symbol("vida"))
        table.enter_scope("func:curar", line=3)
        found = table.lookup("vida", line=4)
        self.assertEqual(found.scope_name, "global")
        self.assertEqual(table.trace[-1]["found_in"], "global")
        self.assertEqual(table.trace[-1]["scope"], "func:curar")

    def test_grandparent_is_visible_from_the_innermost_scope(self):
        table = SymbolTable()
        table.define(symbol("vida"))
        table.enter_scope("func:curar", line=2)
        table.enter_scope("if@3", line=3)
        found = table.lookup("vida", line=4)
        self.assertEqual(found.level, 0)
        self.assertEqual(table.current_scope.level, 2)

    def test_name_is_invisible_after_exit_scope(self):
        table = SymbolTable()
        table.enter_scope("if@4", line=4)
        table.define(symbol("temporal", line=5))
        table.exit_scope(line=6)
        self.assertIsNone(table.lookup("temporal", line=7))
        self.assertIsNone(table.trace[-1]["found_in"])
        # El ambito se desapila, pero queda guardado para mostrarlo.
        self.assertEqual(table.all_scopes[-1].name, "if@4")
        self.assertEqual(table.current_scope.name, "global")

    def test_redeclare_in_the_same_scope_returns_the_previous_symbol(self):
        table = SymbolTable()
        first = symbol("vida", line=2)
        self.assertIsNone(table.define(first))
        previous = table.define(symbol("vida", line=5))
        self.assertIs(previous, first)
        self.assertEqual(table.lookup_local("vida").line, 2)
        defines = [event for event in table.trace if event["action"] == "define"]
        self.assertEqual(len(defines), 1)

    def test_shadowing_is_allowed_in_a_child_scope(self):
        table = SymbolTable()
        table.define(symbol("vida", line=1))
        table.enter_scope("func:curar", line=2)
        self.assertIsNone(table.define(symbol("vida", line=3)))
        self.assertEqual(table.lookup("vida", line=4).level, 1)
        table.exit_scope(line=5)
        self.assertEqual(table.lookup("vida", line=6).level, 0)

    def test_trace_records_every_stack_action_in_order(self):
        table = SymbolTable()
        table.define(symbol("vida", line=2))
        table.enter_scope("func:curar", line=7)
        table.lookup("vida", line=8)
        table.exit_scope(line=9)
        actions = [event["action"] for event in table.trace]
        self.assertEqual(actions, ["define", "enter_scope", "lookup", "exit_scope"])
        self.assertEqual([event["step"] for event in table.trace], [1, 2, 3, 4])
        self.assertEqual(table.trace[0]["name"], "vida")
        self.assertEqual(table.trace[1]["scope"], "func:curar")
        self.assertIsNone(table.trace[1]["name"])

    def test_to_dict_uses_the_contract_keys(self):
        table = SymbolTable()
        table.define(Symbol(
            name="curar", type_name="int", kind="function", scope_name="",
            level=0, line=4, column=1, params=["int"], return_type="int",
        ))
        data = table.current_scope.to_dict()
        self.assertEqual(data["parent"], None)
        symbol = data["symbols"][0]
        self.assertEqual(set(symbol), {
            "name", "type", "kind", "scope", "level", "line", "params", "return_type",
        })
        self.assertEqual(symbol["type"], "int")
        self.assertEqual(symbol["params"], ["int"])
        self.assertEqual(symbol["return_type"], "int")


if __name__ == "__main__":
    unittest.main()
