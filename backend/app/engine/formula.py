"""Small, safe vector formula evaluator for analyst-created calculated columns.

Supported: column identifiers, numeric constants, + - * / // % **, parentheses,
comparisons, and abs/round/log/sqrt. No attribute access, imports, indexing or eval.
"""
from __future__ import annotations

import ast
import operator

import numpy as np
import pandas as pd

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod, ast.Pow: operator.pow}
_CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Gt: operator.gt,
        ast.GtE: operator.ge, ast.Lt: operator.lt, ast.LtE: operator.le}
def _round(value, digits=0):
    return value.round(int(digits)) if hasattr(value, "round") else round(value, int(digits))

_FUN = {"abs": abs, "round": _round, "sqrt": np.sqrt, "log": np.log}

def evaluate_formula(frame: pd.DataFrame, formula: str):
    if not isinstance(formula, str) or not formula.strip() or len(formula) > 300:
        raise ValueError("Enter a formula (maximum 300 characters).")
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise ValueError("Formula syntax is invalid. Use column names and arithmetic operators.") from exc

    def visit(node):
        if isinstance(node, ast.Expression): return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)): return node.value
        if isinstance(node, ast.Name):
            if node.id not in frame.columns: raise ValueError(f"Unknown column '{node.id}'. Use exact column names without spaces.")
            return pd.to_numeric(frame[node.id], errors="coerce")
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and (not isinstance(right, (int, float)) or abs(right) > 8):
                raise ValueError("Power exponent must be a numeric constant between -8 and 8.")
            return _BIN[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand); return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _CMP:
            return _CMP[type(node.ops[0])](visit(node.left), visit(node.comparators[0]))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUN and not node.keywords:
            args = [visit(arg) for arg in node.args]
            if node.func.id == "round" and len(args) in (1, 2): return round(*args)
            if len(args) == 1: return _FUN[node.func.id](args[0])
        raise ValueError("Unsupported formula. Use arithmetic, comparisons, and abs(), round(), sqrt() or log().")
    result = visit(tree)
    if not hasattr(result, "__len__") or isinstance(result, (str, bytes)):
        result = pd.Series([result] * len(frame), index=frame.index)
    return result
