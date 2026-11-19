import random

ARITY = {"_": 0, "0": 0, ",": 0, "x": 0, "y": 0, "z": 0, "$": 0, ":": 0,
         "^": 1, "v": 1, "A": 1, "D": 1, "'": 1,
         "+": 2, "-": 2, ".": 2, "!": 2, "=": 2, "?": 3}
NIL = None                      # false / empty; a pair is a 2-tuple; a byte is an int


class Limit(Exception):
    pass


def parse(src):
    """Program text -> list of statements. An argument-free symbol is its byte; a symbol with
    arguments is the list (byte, argument, ...) built from pairs. Missing arguments are `_`."""
    src = src.split("F")[0]

    def expr(i):
        if i >= len(src):
            return ord("_"), i
        c = src[i]
        i += 1
        args = []
        for _ in range(ARITY[c]):
            a, i = expr(i)
            args.append(a)
        if not args:
            return ord(c), i
        tail = NIL
        for a in reversed(args):
            tail = (a, tail)
        return (ord(c), tail), i

    out, i = [], 0
    while i < len(src):
        e, i = expr(i)
        out.append(e)
    return out


class Machine:
    def __init__(self, seed=0, limit=4095, steps=10 ** 6):
        self.rng, self.limit, self.steps = random.Random(seed), limit, steps
        self.h = [NIL, NIL, NIL]            # x, y, z
        self.row = []

    def tick(self):
        self.steps -= 1
        if self.steps < 0 or len(self.row) >= self.limit:
            raise Limit

    @staticmethod
    def arg(args, i):
        for _ in range(i):
            args = args[1] if isinstance(args, tuple) else NIL
        return args[0] if isinstance(args, tuple) else NIL

    def ev(self, t, a):
        """Value of expression t (data) with argument a."""
        self.tick()
        if not isinstance(t, tuple):
            c = chr(t) if isinstance(t, int) else ""
            if c == "0": return 0
            if c == ",": return self.rng.randrange(256)
            if c and c in "xyz": return self.h["xyz".index(c)]
            if c == "$": return a
            return NIL
        head, args = t
        c = chr(head) if isinstance(head, int) else ""
        if ARITY.get(c, 0) == 0:
            return NIL
        if c == "'":
            return self.arg(args, 0)
        if c == "?":
            return self.ev(self.arg(args, 1 if self.ev(self.arg(args, 0), a) is not NIL else 2), a)
        p = self.ev(self.arg(args, 0), a)
        if c in "^vAD":
            n = p if isinstance(p, int) else 0
            if c == "^": return (n + 1) % 256
            if c == "v": return (n - 1) % 256
            if c == "A": return p[0] if isinstance(p, tuple) else NIL
            return p[1] if isinstance(p, tuple) else NIL
        q = self.ev(self.arg(args, 1), a)
        if c == ".": return (p, q)
        if c == "!": return self.ev(p, q)
        if c == "=":
            return 1 if not isinstance(p, tuple) and not isinstance(q, tuple) and p == q else NIL
        m, n = (p if isinstance(p, int) else 0), (q if isinstance(q, int) else 0)
        return (m + n) % 256 if c == "+" else (m - n) % 256

    def emit(self, v):
        stack = [v]
        while stack:
            self.tick()                     # emitting costs steps: a value may hold no bytes at all
            x = stack.pop()
            if isinstance(x, int):
                self.row.append(x)
            elif isinstance(x, tuple):
                stack += [x[1], x[0]]

    def run(self, src):
        prog, i, start, last = parse(src), 0, None, NIL
        try:
            while True:
                self.tick()
                if i >= len(prog):
                    if start is None or start >= len(prog) or last is NIL:
                        break
                    i = start
                    continue
                t = prog[i]
                i += 1
                if t == ord(":"):
                    if start is None:
                        start = i
                    continue
                last = self.ev(t, NIL)
                if last is not NIL:
                    self.h = [last] + self.h[:2]
                    self.emit(last)
        except Limit:
            pass
        return self.row[:self.limit]


if __name__ == "__main__":
    import sys
    sys.setrecursionlimit(100000)
    print(Machine(seed=1, limit=16).run(sys.argv[1]))
