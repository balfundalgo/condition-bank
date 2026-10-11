"""
Strategy expressions.

An expression is a flat list of tokens, for example:

    ["C0", "AND", "(", "C1", "OR", "C2", ")", "AND", "C3"]

The user builds this list by clicking chips in the UI.  This module turns it
into a tree, checks that it makes sense, prints it back as text, translates
it into a plain English sentence, and evaluates it against a dictionary of
condition results.
"""

from . import conditions as C

OPS = ("AND", "OR")
OPEN, CLOSE = "(", ")"


class ExprError(ValueError):
    pass


# --------------------------------------------------------------- parsing
class _Parser:
    def __init__(self, tokens):
        self.t = list(tokens)
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        if not self.t:
            raise ExprError("Expression is empty.")
        node = self.parse_or()
        if self.i < len(self.t):
            raise ExprError(f"Unexpected '{self.peek()}' after a complete expression.")
        return node

    def parse_or(self):
        node = self.parse_and()
        while self.peek() == "OR":
            self.take()
            right = self.parse_and()
            node = ("OR", node, right)
        return node

    def parse_and(self):
        node = self.parse_atom()
        while self.peek() == "AND":
            self.take()
            right = self.parse_atom()
            node = ("AND", node, right)
        return node

    def parse_atom(self):
        tok = self.take()
        if tok is None:
            raise ExprError("Expression ends too early -- a condition is missing.")
        if tok == OPEN:
            node = self.parse_or()
            if self.take() != CLOSE:
                raise ExprError("A bracket was opened but never closed.")
            return node
        if tok == CLOSE:
            raise ExprError("Found ')' where a condition was expected.")
        if tok in OPS:
            raise ExprError(f"Found '{tok}' where a condition was expected.")
        if tok not in C.BY_ID:
            raise ExprError(f"'{tok}' is not a condition in the bank.")
        return ("COND", tok)


def parse(tokens):
    return _Parser(tokens).parse()


def validate(tokens, allowed_group=None):
    """Return (ok, message). message is friendly enough to show on screen."""
    if not tokens:
        return False, "Nothing added yet."
    try:
        tree = parse(tokens)
    except ExprError as e:
        return False, str(e)
    if allowed_group:
        wrong = [t for t in tokens
                 if t in C.BY_ID and C.BY_ID[t].group != allowed_group]
        if wrong:
            label = {"entry": "entry", "exit": "exit",
                     "late": "late entry"}[allowed_group]
            return False, (f"{', '.join(sorted(set(wrong)))} cannot be used "
                           f"here -- this box only takes {label} conditions.")
    used = [t for t in tokens if t in C.BY_ID]
    dupes = sorted({t for t in used if used.count(t) > 1})
    if dupes:
        return True, f"Valid, but {', '.join(dupes)} is used more than once."
    return True, f"Valid. {len(used)} condition{'s' if len(used) != 1 else ''} in use."


# --------------------------------------------------------------- printing
def to_text(tokens):
    out = ""
    for tok in tokens:
        if tok == OPEN:
            out += ("" if (not out or out.endswith("(")) else " ") + "("
        elif tok == CLOSE:
            out += ")"
        else:
            out += ("" if (not out or out.endswith("(")) else " ") + tok
    return out


def _english(node, top=True):
    kind = node[0]
    if kind == "COND":
        return C.get(node[1]).phrase
    joiner = " and " if kind == "AND" else " or "
    left = _english(node[1], False)
    right = _english(node[2], False)
    body = left + joiner + right
    return body if top else ("(" + body + ")" if kind == "OR" else body)


def to_english(tokens, lead="Enter when"):
    """Turn the token list into a readable sentence for the preview panel."""
    try:
        tree = parse(tokens)
    except ExprError:
        return ""
    return f"{lead} {_english(tree)}."


# ------------------------------------------------------------- evaluating
def evaluate(tokens, values: dict) -> bool:
    """values maps condition id -> True/False. Used by the live engine."""
    def walk(node):
        if node[0] == "COND":
            return bool(values.get(node[1], False))
        left, right = walk(node[1]), walk(node[2])
        return (left and right) if node[0] == "AND" else (left or right)
    return walk(parse(tokens))


def conditions_used(tokens):
    seen, out = set(), []
    for t in tokens:
        if t in C.BY_ID and t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ------------------------------------------------------------- templates
TEMPLATES = {
    "Strategy 1 (from the spec)": {
        "entry": ["C0", "AND", "(", "C1", "OR", "C2", ")", "AND", "C3",
                  "AND", "C4", "AND", "C5", "AND", "C6"],
        "exit": ["X0", "AND", "X2"],
    },
    "Strategy 2 (from the spec)": {
        "entry": ["C6", "AND", "C7", "AND", "C8", "AND", "C4", "AND", "C9",
                  "AND", "C13", "AND", "C14"],
        "exit": ["X0", "AND", "X2"],
    },
    "Blank": {"entry": [], "exit": []},
}

DEFAULT_LATE = ["L0", "AND", "L1", "AND", "L2"]
