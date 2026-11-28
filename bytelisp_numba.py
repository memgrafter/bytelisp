"""Fast parallel batch interpreter for bytelisp (v1, v2, v3) using Numba.

Matches ``bytelisp.Machine(..., rng=SplitMix64(seed), version=version)`` 1:1 on output bytes,
emitted length, step count, max eval depth, stop reason, and pair allocations.
"""

from __future__ import annotations

import sys

import numpy as np
from numba import njit, prange

from bytelisp import (
    ARITY,
    END,
    HALT,
    MEMORY,
    OUTPUT,
    STEPS,
    STOP_NAMES,
    VERSIONS,
    Machine,
    SplitMix64,
    version_spec,
)


def program_body(program: str | bytes) -> str:
    """Return executable program text cut at the first ``F``."""
    if isinstance(program, (bytes, bytearray)):
        program = program.decode("latin-1")
    i = program.find(END)
    return program if i < 0 else program[:i]


_VERSION_TABLES: dict[str, tuple[np.ndarray, np.ndarray]] = {}
for _vname, _vsyms in VERSIONS.items():
    _at = np.zeros(256, dtype=np.int64)
    _vt = np.zeros(256, dtype=np.bool_)
    for _c in _vsyms:
        _at[ord(_c)] = ARITY[_c]
        _vt[ord(_c)] = True
    _VERSION_TABLES[_vname] = (_at, _vt)


def encode_programs(programs: list[str | bytes], version: str = "v3") -> tuple[np.ndarray, np.ndarray]:
    """Encode program texts to a padded ``[B, Lmax]`` uint8 array and length vector."""
    if version not in _VERSION_TABLES:
        raise ValueError(f"unknown version {version!r}: choose from {tuple(VERSIONS)}")
    _, valid = _VERSION_TABLES[version]
    bodies = [program_body(p).encode("latin-1") for p in programs]
    L = max([1] + [len(b) for b in bodies])
    arr = np.zeros((len(bodies), L), dtype=np.uint8)
    lens = np.zeros(len(bodies), dtype=np.int64)
    for i, b in enumerate(bodies):
        v = np.frombuffer(b, dtype=np.uint8)
        if len(v) and not valid[v].all():
            raise ValueError(f"program {i} has bytes outside bytelisp {version}: {b!r}")
        arr[i, :len(b)] = v
        lens[i] = len(b)
    return arr, lens


@njit(cache=True)
def _splitmix(state):
    state = state + np.uint64(0x9E3779B97F4A7C15)
    z = state
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return state, z ^ (z >> np.uint64(31))


@njit(cache=True)
def _grow1(a, need):
    n = a.shape[0]
    while n < need:
        n *= 2
    b = np.empty(n, dtype=a.dtype)
    b[:a.shape[0]] = a
    return b


@njit(cache=True)
def _grow2(a, need):
    n = a.shape[0]
    while n < need:
        n *= 2
    b = np.empty((n, a.shape[1]), dtype=a.dtype)
    b[:a.shape[0]] = a
    return b


@njit(cache=True)
def _arg(car, cdr, args, i):
    for _ in range(i):
        args = cdr[args - 256] if args >= 256 else -1
    return car[args - 256] if args >= 256 else -1


@njit(cache=True)
def _run_one(body, blen, arity, T, max_steps, max_pairs, seed, out_row):
    # Parse (Polish notation, right to left; missing trailing arguments become `_`)
    pend = 0
    for j in range(blen):
        if pend == 0:
            pend = 1
        pend += arity[body[j]] - 1
    ntok = blen + pend
    toks = np.empty(ntok, dtype=np.int64)
    for j in range(blen):
        toks[j] = body[j]
    for j in range(blen, ntok):
        toks[j] = 95                                    # `_`
    cap = 4 * ntok + 64
    car = np.empty(cap, dtype=np.int64)
    cdr = np.empty(cap, dtype=np.int64)
    npair = 0
    vst = np.empty(ntok + 1, dtype=np.int64)
    vsp = 0
    for j in range(ntok - 1, -1, -1):
        c = toks[j]
        k = arity[c]
        if k == 0:
            vst[vsp] = c
            vsp += 1
        else:
            tail = -1
            for m in range(k):
                car[npair] = vst[vsp - k + m]
                cdr[npair] = tail
                tail = 256 + npair
                npair += 1
            vsp -= k
            car[npair] = c
            cdr[npair] = tail
            vst[vsp] = 256 + npair
            npair += 1
            vsp += 1
    nst = vsp
    stmts = np.empty(nst, dtype=np.int64)
    for j in range(nst):
        stmts[j] = vst[nst - 1 - j]
    npair_static = npair

    # Explicit-stack execution
    frames = np.empty((64, 7), dtype=np.int64)          # op, stage, args, a, p/rem, u_head, u_tail
    sp = 0
    est = np.empty(64, dtype=np.int64)
    esp = 0
    rng = np.uint64(seed)
    hist = np.full(256, -1, dtype=np.int64)             # ring buffer: hist[hhead]=x, +1=y, +2=z, +idx=H(idx)
    hhead = 0
    used = 0
    nout = 0
    depth = 0
    maxdepth = 0
    stop = 0
    i = 0
    start = -1
    last = -1
    at_phase = 0                                        # 0 normal, 1 @-init, 2 @-loop
    at_trans = -1
    at_state = -1
    t = -1
    a = -1
    r = -1
    mode = 0                                            # 0 stmt loop, 1 call, 2 return, 3 emit, 4 @-tick
    while True:
        if mode == 3:
            if esp == 0:
                mode = 4 if at_phase == 2 else 0
                continue
        if mode != 2:                                   # tick
            if nout >= T:
                stop = 1
                break
            if used >= max_steps:
                stop = 2
                break
            used += 1
        if mode == 0:
            if i >= nst:
                if start < 0 or start >= nst or last == -1:
                    stop = 0
                    break
                i = start
                continue
            t = stmts[i]
            i += 1
            if t == 58:                                 # `:`
                if start < 0:
                    start = i
                continue
            if t >= 256 and car[t - 256] == 64 and arity[64] > 0:   # top-level `@`
                at_args = cdr[t - 256]
                at_trans = _arg(car, cdr, at_args, 1)
                at_phase = 1
                a = -1
                sp = 0
                t = _arg(car, cdr, at_args, 0)
                mode = 1
                continue
            a = -1
            sp = 0
            mode = 1
        elif mode == 4:                                 # `@` transition step (already ticked above)
            t = at_trans
            a = at_state
            sp = 0
            mode = 1
        elif mode == 1:
            if t < 256:
                if t == 48:
                    r = 0
                elif t == 44:
                    rng, z = _splitmix(rng)
                    r = np.int64(z >> np.uint64(56))
                elif t == 120:
                    r = hist[hhead]
                elif t == 121:
                    r = hist[(hhead + 1) & 255]
                elif t == 122:
                    r = hist[(hhead + 2) & 255]
                elif t == 36:
                    r = a
                else:
                    r = -1
                mode = 2
            else:
                head = car[t - 256]
                args = cdr[t - 256]
                k = arity[head] if 0 <= head < 256 else 0
                if k == 0 or head == 64:                # 0-arity or nested `@` -> NIL
                    r = -1
                    mode = 2
                elif head == 39:                        # `'`
                    r = _arg(car, cdr, args, 0)
                    mode = 2
                else:
                    if sp == frames.shape[0]:
                        frames = _grow2(frames, sp + 1)
                    frames[sp, 0] = head
                    frames[sp, 1] = 0
                    frames[sp, 2] = args
                    frames[sp, 3] = a
                    frames[sp, 4] = -1
                    frames[sp, 5] = -1
                    frames[sp, 6] = -1
                    sp += 1
                    t = _arg(car, cdr, args, 0)
        elif mode == 2:
            if sp == 0:                                 # statement return (or `@` init/step)
                if at_phase == 1:
                    at_state = r
                    at_phase = 2
                    mode = 4
                    continue
                if at_phase == 2:
                    if r >= 256:
                        at_state = car[r - 256]
                        out_v = cdr[r - 256]
                        if out_v != -1:
                            last = out_v
                            hhead = (hhead - 1) & 255
                            hist[hhead] = out_v
                            est[0] = out_v
                            esp = 1
                            mode = 3
                        else:
                            mode = 4
                    else:
                        at_phase = 0
                        last = -1
                        mode = 0
                    continue
                last = r
                if r != -1:
                    hhead = (hhead - 1) & 255
                    hist[hhead] = r
                    est[0] = r
                    esp = 1
                    mode = 3
                else:
                    mode = 0
                continue
            f = sp - 1
            op = frames[f, 0]
            if op == 256:                               # back from `!`
                sp -= 1
                depth -= 1
            elif op == 63:                              # `?`
                sp -= 1
                a = frames[f, 3]
                t = _arg(car, cdr, frames[f, 2], 1 if r != -1 else 2)
                mode = 1
            elif op == 85:                              # `U`: unfold repeated evaluations
                if frames[f, 1] == 0:
                    cnt = r if 0 <= r < 256 else 0
                    if cnt == 0:
                        sp -= 1
                        r = -1
                    else:
                        frames[f, 1] = 1
                        frames[f, 4] = cnt
                        frames[f, 5] = -1
                        frames[f, 6] = -1
                        a = frames[f, 3]
                        t = _arg(car, cdr, frames[f, 2], 1)
                        mode = 1
                else:
                    if npair - npair_static >= max_pairs:
                        stop = 3
                        break
                    if npair == car.shape[0]:
                        car = _grow1(car, npair + 1)
                        cdr = _grow1(cdr, npair + 1)
                    car[npair] = r
                    cdr[npair] = -1
                    cell = 256 + npair
                    npair += 1
                    if frames[f, 5] == -1:
                        frames[f, 5] = cell
                        frames[f, 6] = cell
                    else:
                        cdr[frames[f, 6] - 256] = cell
                        frames[f, 6] = cell
                    rem = frames[f, 4] - 1
                    if rem > 0:
                        frames[f, 4] = rem
                        a = frames[f, 3]
                        t = _arg(car, cdr, frames[f, 2], 1)
                        mode = 1
                    else:
                        r = frames[f, 5]
                        sp -= 1
            elif op == 94 or op == 118:                 # `^` `v`
                sp -= 1
                n = r if 0 <= r < 256 else 0
                r = (n + 1) % 256 if op == 94 else (n + 255) % 256
            elif op == 65 or op == 68:                  # `A` `D`
                sp -= 1
                if r >= 256:
                    r = car[r - 256] if op == 65 else cdr[r - 256]
                else:
                    r = -1
            elif op == 72:                              # `H` indexed history 0..255
                sp -= 1
                idx = r if 0 <= r < 256 else 0
                r = hist[(hhead + idx) & 255]
            elif frames[f, 1] == 0:                     # binary: evaluate second operand
                frames[f, 4] = r
                frames[f, 1] = 1
                a = frames[f, 3]
                t = _arg(car, cdr, frames[f, 2], 1)
                mode = 1
            else:
                p = frames[f, 4]
                q = r
                sp -= 1
                if op == 46:                            # `.`
                    if npair - npair_static >= max_pairs:
                        stop = 3
                        break
                    if npair == car.shape[0]:
                        car = _grow1(car, npair + 1)
                        cdr = _grow1(cdr, npair + 1)
                    car[npair] = p
                    cdr[npair] = q
                    r = 256 + npair
                    npair += 1
                elif op == 33:                          # `!`
                    depth += 1
                    if depth > maxdepth:
                        maxdepth = depth
                    if sp == frames.shape[0]:
                        frames = _grow2(frames, sp + 1)
                    frames[sp, 0] = 256
                    sp += 1
                    t = p
                    a = q
                    mode = 1
                elif op == 61:                          # `=`
                    r = 1 if (p < 256 and q < 256 and p == q) else -1
                elif op == 78:                          # `N`: repeat value
                    cnt = p if 0 <= p < 256 else 0
                    acc = -1
                    for _ in range(cnt):
                        if nout >= T:
                            stop = 1
                            break
                        if used >= max_steps:
                            stop = 2
                            break
                        used += 1
                        if npair - npair_static >= max_pairs:
                            stop = 3
                            break
                        if npair == car.shape[0]:
                            car = _grow1(car, npair + 1)
                            cdr = _grow1(cdr, npair + 1)
                        car[npair] = q
                        cdr[npair] = acc
                        acc = 256 + npair
                        npair += 1
                    if stop != 0:
                        break
                    r = acc
                else:                                   # byte binary ops: `+` `-` `<` `*` `X` `%` `>`
                    m = p if 0 <= p < 256 else 0
                    n = q if 0 <= q < 256 else 0
                    if op == 43:                        # `+`
                        r = (m + n) % 256
                    elif op == 45:                      # `-`
                        r = (m - n + 256) % 256
                    elif op == 60:                      # `<`
                        r = 1 if m < n else -1
                    elif op == 42:                      # `*`
                        r = (m * n) % 256
                    elif op == 88:                      # `X`
                        r = (m ^ n) & 255
                    elif op == 37:                      # `%`
                        r = (m % n) if n != 0 else 0
                    else:                               # `>`
                        r = (m >> n) if n < 8 else 0
        else:                                           # emit: one node per step
            esp -= 1
            x = est[esp]
            if 0 <= x < 256:
                out_row[nout] = x
                nout += 1
            elif x >= 256:
                if esp + 2 > est.shape[0]:
                    est = _grow1(est, esp + 2)
                est[esp] = cdr[x - 256]
                est[esp + 1] = car[x - 256]
                esp += 2
    return nout, used, maxdepth, stop, npair - npair_static


@njit(parallel=True, cache=True)
def _run_batch(bodies, lens, arity, T, max_steps, max_pairs, seeds, out, n_out, steps, depth, stop, pairs):
    for i in prange(bodies.shape[0]):
        a, b, c, d, e = _run_one(bodies[i], lens[i], arity, T, max_steps, max_pairs, seeds[i], out[i])
        n_out[i] = a
        steps[i] = b
        depth[i] = c
        stop[i] = d
        pairs[i] = e


def run_batch(programs: list[str | bytes], seeds: np.ndarray | list[int], T: int = 4095,
              max_steps: int = 1 << 20, max_pairs: int = 1 << 16, version: str = "v3") -> dict:
    """Execute ``programs`` in parallel with Numba. Returns ``out [B, T]`` uint8 (zero-padded),
    ``n_out``, ``steps``, ``max_depth``, ``stop`` (HALT/OUTPUT/STEPS/MEMORY), ``pairs``, and ``body_len``."""
    arity_tab, _ = _VERSION_TABLES[version] if version in _VERSION_TABLES else _VERSION_TABLES["v3"]
    bodies, lens = encode_programs(programs, version=version)
    B = len(programs)
    seeds_arr = np.asarray(seeds, dtype=np.uint64)
    if seeds_arr.shape != (B,):
        raise ValueError("one seed per program")
    out = np.zeros((B, T), dtype=np.uint8)
    n_out = np.zeros(B, dtype=np.int64)
    steps = np.zeros(B, dtype=np.int64)
    depth = np.zeros(B, dtype=np.int64)
    stop = np.zeros(B, dtype=np.int64)
    pairs = np.zeros(B, dtype=np.int64)
    _run_batch(bodies, lens, arity_tab, int(T), int(max_steps), int(max_pairs), seeds_arr,
               out, n_out, steps, depth, stop, pairs)
    return {"out": out, "n_out": n_out, "steps": steps, "max_depth": depth, "stop": stop,
            "pairs": pairs, "body_len": lens}


def run_reference(program: str | bytes, T: int = 4095, max_steps: int = 1 << 20,
                  max_pairs: int | None = 1 << 16, seed: int = 0, version: str = "v3") -> dict:
    """Run one program through ``bytelisp.Machine`` with ``SplitMix64(seed)``; matches ``run_batch`` 1:1."""
    if sys.getrecursionlimit() < 4 * max_steps + 1000:
        sys.setrecursionlimit(4 * max_steps + 1000)
    m = Machine(seed=seed, limit=T, steps=max_steps, max_pairs=max_pairs, rng=SplitMix64(seed), version=version)
    row = m.run(program_body(program))
    return {"out": row + [0] * (T - len(row)), "n_out": len(row), "steps": m.used, "max_depth": m.max_depth,
            "stop": m.stop, "pairs": m.pairs}


def sample_g0(n: int, max_len: int, rng: np.random.Generator, version: str = "v3") -> list[str]:
    """Sample ``n`` programs from the uniform prior g0 (uniform over alphabet + ``F``, forced ``F`` at ``max_len``)."""
    _, alpha, _ = version_spec(version)
    out = []
    for _ in range(n):
        s = []
        while len(s) < max_len - 1:
            c = alpha[int(rng.integers(len(alpha)))]
            if c == END:
                break
            s.append(c)
        out.append("".join(s))
    return out


__all__ = [
    "HALT", "OUTPUT", "STEPS", "MEMORY", "STOP_NAMES",
    "program_body", "encode_programs", "run_batch", "run_reference", "sample_g0",
]
