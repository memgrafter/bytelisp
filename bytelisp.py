import random

ARITY_V1 = {
    "_": 0, "0": 0, ",": 0, "x": 0, "y": 0, "z": 0, "$": 0, ":": 0,
    "^": 1, "v": 1, "A": 1, "D": 1, "'": 1,
    "+": 2, "-": 2, ".": 2, "!": 2, "=": 2, "?": 3,
}
ARITY_V2_EXT = {
    "<": 2, "*": 2, "U": 2, "H": 1, "N": 2, "@": 2,
}
ARITY_V3_EXT = {
    "X": 2, "%": 2, ">": 2,
}
ARITY = {**ARITY_V1, **ARITY_V2_EXT, **ARITY_V3_EXT}

VERSIONS = {
    "v1": tuple(ARITY_V1),
    "v2": tuple(ARITY_V1) + tuple(ARITY_V2_EXT),
    "v3": tuple(ARITY),
}
END = "F"
NIL = None                      # false / empty; a pair is a 2-tuple; a byte is an int

HALT, OUTPUT, STEPS, MEMORY = 0, 1, 2, 3
STOP_NAMES = ("halt", "output", "steps", "memory")


def version_spec(version="v3"):
    """Return (body_alphabet, alphabet_with_F, arity_dict) for version 'v1', 'v2', or 'v3'."""
    if version not in VERSIONS:
        raise ValueError(f"unknown version {version!r}: choose from {tuple(VERSIONS)}")
    syms = VERSIONS[version]
    body = "".join(syms)
    return body, body + END, {c: ARITY[c] for c in syms}


def splitmix64(state):
    """(new_state, output) of splitmix64."""
    m = (1 << 64) - 1
    state = (state + 0x9E3779B97F4A7C15) & m
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & m
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & m
    return state, z ^ (z >> 31)


class SplitMix64:
    """Deterministic byte stream (top 8 bits of splitmix64); matches the Numba batch interpreter."""

    def __init__(self, seed=0):
        self.state = int(seed) & ((1 << 64) - 1)

    def randrange(self, n):
        if n != 256:
            raise ValueError("bytelisp draws bytes only")
        self.state, z = splitmix64(self.state)
        return z >> 56


class Limit(Exception):
    pass


def parse(src, version="v3"):
    """Program text -> list of statements. An argument-free symbol is its byte; a symbol with
    arguments is the list (byte, argument, ...) built from pairs. Missing arguments are `_`."""
    _, _, arity = version_spec(version)
    src = src.split(END)[0]
    n, under = len(src), ord("_")
    out, i = [], 0
    while i < n:
        stack = []
        while True:
            if i >= n:
                v = under
            else:
                c = src[i]
                i += 1
                k = arity[c]
                if k:
                    stack.append((ord(c), k, []))
                    continue
                v = ord(c)
            while stack:
                head, k, args = stack[-1]
                args.append(v)
                if len(args) < k:
                    break
                stack.pop()
                tail = NIL
                for a in reversed(args):
                    tail = (a, tail)
                v = (head, tail)
            if not stack:
                break
        out.append(v)
    return out


class Machine:
    def __init__(self, seed=0, limit=4095, steps=10 ** 6, max_pairs=None, rng=None, version="v3"):
        self.rng = random.Random(seed) if rng is None else rng
        self.limit, self.steps, self.max_pairs = limit, steps, max_pairs
        self.version = version
        _, _, self._arity = version_spec(version)
        self.h = [NIL] * 256                # x=h[0], y=h[1], z=h[2], H(k)=h[k]
        self.row = []
        self.used = 0
        self.pairs = 0
        self.depth = self.max_depth = 0
        self.stop = HALT

    def tick(self):
        self.steps -= 1
        if len(self.row) >= self.limit:
            self.stop = OUTPUT
            raise Limit
        if self.steps < 0:
            self.stop = STEPS
            raise Limit
        self.used += 1

    def _alloc_pair(self, p, q):
        if self.max_pairs is not None and self.pairs >= self.max_pairs:
            self.stop = MEMORY
            raise Limit
        self.pairs += 1
        return (p, q)

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
        if self._arity.get(c, 0) == 0 or c == "@":
            return NIL
        if c == "'":
            return self.arg(args, 0)
        if c == "?":
            return self.ev(self.arg(args, 1 if self.ev(self.arg(args, 0), a) is not NIL else 2), a)
        if c == "U":
            cnt_v = self.ev(self.arg(args, 0), a)
            cnt = cnt_v if isinstance(cnt_v, int) else 0
            if cnt == 0:
                return NIL
            expr = self.arg(args, 1)
            vals = []
            for _ in range(cnt):
                v = self.ev(expr, a)
                if self.max_pairs is not None and self.pairs >= self.max_pairs:
                    self.stop = MEMORY
                    raise Limit
                self.pairs += 1
                vals.append(v)
            res = NIL
            for v in reversed(vals):
                res = (v, res)
            return res
        p = self.ev(self.arg(args, 0), a)
        if c in "^vADH":
            n = p if isinstance(p, int) else 0
            if c == "^": return (n + 1) % 256
            if c == "v": return (n - 1) % 256
            if c == "A": return p[0] if isinstance(p, tuple) else NIL
            if c == "D": return p[1] if isinstance(p, tuple) else NIL
            return self.h[n]
        q = self.ev(self.arg(args, 1), a)
        if c == ".": return self._alloc_pair(p, q)
        if c == "!":
            self.depth += 1
            self.max_depth = max(self.max_depth, self.depth)
            try:
                return self.ev(p, q)
            finally:
                self.depth -= 1
        if c == "=":
            return 1 if not isinstance(p, tuple) and not isinstance(q, tuple) and p == q else NIL
        if c == "N":
            cnt = p if isinstance(p, int) else 0
            res = NIL
            for _ in range(cnt):
                self.tick()
                res = self._alloc_pair(q, res)
            return res
        m, n = (p if isinstance(p, int) else 0), (q if isinstance(q, int) else 0)
        if c == "<": return 1 if m < n else NIL
        if c == "*": return (m * n) % 256
        if c == "X": return (m ^ n) & 255
        if c == "%": return (m % n) if n != 0 else 0
        if c == ">": return (m >> n) if n < 8 else 0
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
        prog, i, start, last = parse(src, version=self.version), 0, None, NIL
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
                if isinstance(t, tuple) and t[0] == ord("@") and "@" in self._arity:
                    s = self.ev(self.arg(t[1], 0), NIL)
                    trans = self.arg(t[1], 1)
                    while True:
                        self.tick()
                        res = self.ev(trans, s)
                        if isinstance(res, tuple):
                            s, out_v = res[0], res[1]
                            if out_v is not NIL:
                                last = out_v
                                self.h = [out_v] + self.h[:255]
                                self.emit(out_v)
                        else:
                            last = NIL
                            break
                    continue
                last = self.ev(t, NIL)
                if last is not NIL:
                    self.h = [last] + self.h[:255]
                    self.emit(last)
        except Limit:
            pass
        return self.row[:self.limit]


if __name__ == "__main__":
    import sys
    sys.setrecursionlimit(100000)
    version = "v3"
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] in ("--v1", "--v2", "--v3"):
        version, args = args[0][2:], args[1:]
    print(Machine(seed=1, limit=16, version=version).run(args[0]))
