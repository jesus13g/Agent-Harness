"""Herramienta de cálculo determinista.

Evalúa expresiones aritméticas de forma segura mediante el AST de Python: solo
se permiten operadores numéricos y un conjunto cerrado de funciones de `math`.
NO usa `eval` sobre código arbitrario.
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from agente.core.types import ToolResult
from agente.ports.tool import Tool

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCS: dict[str, Any] = {
    name: getattr(math, name)
    for name in (
        "sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
        "log", "log2", "log10", "exp", "floor", "ceil", "fabs", "factorial",
        "degrees", "radians", "hypot", "pow",
    )
}
_FUNCS.update({"abs": abs, "round": round, "min": min, "max": max})
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


class CalculatorTool(Tool):
    name = "calculator"
    description = (
        "Evalúa una expresión matemática y devuelve el resultado numérico. "
        "Soporta + - * / // % ** , paréntesis, constantes (pi, e, tau) y "
        "funciones de math (sqrt, sin, log, exp, factorial, ...). "
        "Úsala para cualquier cálculo en lugar de calcular mentalmente."
    )
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Expresión a evaluar, p. ej. '2 * (3 + 4) ** 2'.",
            }
        },
        "required": ["expression"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        expression = kwargs.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            return ToolResult.failure("Se requiere 'expression' (string no vacío).")
        try:
            tree = ast.parse(expression, mode="eval")
            value = self._eval(tree.body)
        except ZeroDivisionError:
            return ToolResult.failure("División por cero.")
        except (ValueError, OverflowError) as exc:
            return ToolResult.failure(f"Error matemático: {exc}")
        except _UnsafeExpression as exc:
            return ToolResult.failure(str(exc))
        except SyntaxError:
            return ToolResult.failure(f"Expresión inválida: {expression!r}")
        return ToolResult.success(str(value))

    # ------------------------------------------------------------------ #

    def _eval(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise _UnsafeExpression(f"Constante no numérica: {node.value!r}")
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            return _BIN_OPS[type(node.op)](self._eval(node.left), self._eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](self._eval(node.operand))
        if isinstance(node, ast.Name):
            if node.id in _CONSTS:
                return _CONSTS[node.id]
            raise _UnsafeExpression(f"Nombre no permitido: {node.id!r}")
        if isinstance(node, ast.Call):
            return self._eval_call(node)
        raise _UnsafeExpression(f"Construcción no permitida: {type(node).__name__}")

    def _eval_call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise _UnsafeExpression("Solo se permiten funciones matemáticas conocidas.")
        if node.keywords:
            raise _UnsafeExpression("No se permiten argumentos con nombre.")
        args = [self._eval(arg) for arg in node.args]
        return _FUNCS[node.func.id](*args)


class _UnsafeExpression(Exception):
    """La expresión contiene construcciones no permitidas."""
