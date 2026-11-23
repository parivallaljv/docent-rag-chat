"""Safe arithmetic evaluator for the agent's `calculate` tool (no eval())."""

from __future__ import annotations

import ast
import math
import operator

_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"abs": abs, "round": round, "min": min, "max": max, "sqrt": math.sqrt}
MAX_LEN = 200
MAX_EXPONENT = 100


def safe_calculate(expression: str) -> float | int:
    if len(expression) > MAX_LEN:
        raise ValueError("Expression too long.")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError("Not a valid arithmetic expression.") from exc

    def ev(node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
                raise ValueError("Exponent too large.")
            return _BIN[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](ev(node.operand))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS
            and not node.keywords
        ):
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError("Only numbers, + - * / // % ** and abs/round/min/max/sqrt are allowed.")

    try:
        return ev(tree)
    except ZeroDivisionError as exc:
        raise ValueError("Division by zero.") from exc
    except OverflowError as exc:
        raise ValueError("Result too large.") from exc
