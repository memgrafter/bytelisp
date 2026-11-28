# bytelisp: a minimal bracket-free homoiconic Lisp over bytes (specification, reference interpreter, and the language written in itself)

bytelisp is a prefix-notation, bracket-free, name-free Lisp over bytes. Programs read random bytes and emit bytes. Code is data: quoting a program gives its own bytes, and `!` runs such data. Every byte string over the version's symbols is a valid program.

### Versions
- **v1** (19 symbols + `F`): minimal homoiconic core.
- **v2** (25 symbols + `F`): v1 + 6 primitives (`<`, `*`, `U`, `H`, `N`, `@`) matching the capabilities of Brainf\*ck + 10 macros† (ordering, scaling, variable-length block buffers, deep indexed history, value repetition, and private non-emitted state).
- **v3** (28 symbols + `F`): v2 + 3 bitwise and modular primitives (`X`, `%`, `>`) beyond Brainf\*ck + 10 macros†.

Every v1 program is a valid v2 program, and every v2 program is a valid v3 program, with identical semantics.

### Symbols

#### v1 core (19 symbols)
| Byte | Value | Arguments | Meaning |
|---|---|---|---|
| `_` | 95 | 0 | false, and the empty list; emits nothing |
| `0` | 48 | 0 | the byte 0 |
| `,` | 44 | 0 | a fresh random byte from the input; each evaluation draws a new one |
| `x` | 120 | 0 | the value of the most recent statement that was not `_` (`h[0]`) |
| `y` | 121 | 0 | the one before `x` (`h[1]`) |
| `z` | 122 | 0 | the one before `y` (`h[2]`) |
| `$` | 36 | 0 | the argument given by the enclosing `!` or `@` (`_` at the top level) |
| `:` | 58 | 0 | as a statement: the loop marker; inside an expression: `_` |
| `^` | 94 | 1 | byte + 1 mod 256 |
| `v` | 118 | 1 | byte - 1 mod 256 |
| `A` | 65 | 1 | first part of a pair; `_` for anything else |
| `D` | 68 | 1 | second part of a pair; `_` for anything else |
| `'` | 39 | 1 | quote: its argument, unevaluated, as data |
| `+` | 43 | 2 | sum mod 256 |
| `-` | 45 | 2 | difference mod 256 |
| `.` | 46 | 2 | a pair |
| `!` | 33 | 2 | eval: evaluate the first value as an expression, with `$` set to the second value |
| `=` | 61 | 2 | the byte 1 if both are the same byte or both `_`; otherwise `_` (always `_` if either is a pair) |
| `?` | 63 | 3 | if the first is not `_`, the second, otherwise the third; only the chosen one is evaluated |

#### v2 extensions (+6 symbols: Brainf\*ck + macros parity)
| Byte | Value | Arguments | Meaning |
|---|---|---|---|
| `<` | 60 | 2 | unsigned byte comparison: `1` if first < second, otherwise `_` |
| `*` | 42 | 2 | product mod 256 |
| `U` | 85 | 2 | unfold: evaluate the first argument to count `n`, then evaluate the second argument `n` times and return the list `(v1, (v2, ... (vn, _)))` (`_` if `n = 0`) |
| `H` | 72 | 1 | indexed history: `h[n]` for byte `n` in `0..255` (`H0` = `x`, `H^0` = `y`, `H^^0` = `z`) |
| `N` | 78 | 2 | repeat: evaluate both arguments, then build a list of `p` copies of `q` (1 step and 1 pair per copy) |
| `@` | 64 | 2 | as a top-level statement: stateful loop `@ init trans` (see below); inside an expression: `_` (operands not evaluated) |

#### v3 extensions (+3 symbols: bitwise and modular)
| Byte | Value | Arguments | Meaning |
|---|---|---|---|
| `X` | 88 | 2 | bitwise XOR mod 256 |
| `%` | 37 | 2 | unsigned modulo (`m % n`, or `0` when `n = 0`) |
| `>` | 62 | 2 | logical right shift (`m >> n`, or `0` when `n >= 8`) |

`F` (70) ends a program text; what follows it is ignored.

### Syntax
A program is a sequence of expressions, called statements. An expression is a symbol followed by as many expressions as it takes arguments. Arguments missing at the end of the text are `_`. There are no spaces, brackets or names, and no syntax errors.

### Values
A byte (0 to 255), `_`, or a pair of two values. Only `_` is false; every byte, 0 included, is true. Arithmetic, counts (`U`, `N`), and history indices (`H`) read `_` and pairs as 0. Arguments are evaluated left to right.

### Statements and output
- Statements are evaluated in order. A statement whose value is not `_` is emitted, and its value becomes `x` (shifting `h[0..254]` into `h[1..255]`; all 256 slots start as `_`).
- Emitting: a byte emits itself; a pair emits its first part, then its second part; `_` emits nothing.
- `:` as a statement marks a point. At the end of the program, if a marker was passed, at least one statement follows it, and the last evaluated statement's value was not `_`, execution continues after the first marker. Later markers do nothing.
- `@ init trans` (v2+) as a top-level statement evaluates `init` once to get private state `s`, then loops: each iteration takes one step and evaluates `trans` with `$ = s`. If the result is a pair `(s', out)`, state becomes `s'` and if `out` is not `_` then `out` is pushed onto history and emitted (and becomes `last`); if `out` is `_`, the step is silent and the loop continues. When `trans` returns a non-pair, `last` becomes `_` and the `@` loop terminates.
- Only statements (and non-`_` outputs of `@`) emit. Sub-expressions, and everything evaluated by `!`, are silent. `x`, `y`, `z`, and `H` are visible everywhere.

### Code as data
`'` followed by an argument-free symbol gives that symbol's byte value. `'` followed by a symbol with arguments gives the list (byte value, quoted argument, ...), built from pairs and ended by `_`. `!` evaluates such data: a byte that is not an argument-free symbol, or a list whose first part is not a symbol with arguments in the active version, evaluates to `_`. A quoted expression is a function of one parameter, `$`; recursion passes the function to itself inside `$`. Numbers come from quoting: `'0` is 48, `A'+__` is 43.

### Limits
Three limits can end a run; none is an error: an output limit (bytes emitted), a step budget, and an optional pair-allocation budget (`max_pairs`, counting pairs built by `.`, `U`, and `N`). One step is one expression evaluated, one statement or `@`/`N` loop position visited, or one node visited while emitting (a value can hold no bytes at all and still be large, e.g. `.__:.xx`).

### Examples (one random input sequence, `random.Random(1)`)
| Program | Version | Output | What it does |
|---|---|---|---|
| `,,+xy` | v1 | 68 32 100 | two random bytes, then their sum |
| `:0,,+xy` | v1 | 0 68 32 100 0 130 60 190 ... | the same after a 0, repeated until the output limit |
| `,:+xy` | v1 | 68 68 136 204 84 32 116 148 ... | one random byte, then each value is the sum of the two before it |
| `,!'+$$x` | v1 | 68 136 | a random byte, then its double (a quoted expression used as a function) |
| `^^^_:?=x0_vx` | v1 | 3 2 1 0 | counts down from 3 and halts |
| `'+,,!x_!y,` | v1 | 43 44 44 100 57 | emits the code `+,,` as data, then runs it twice |
| `,,?<xyyx` | v2 | 68 32 68 | two random bytes, then their maximum |
| `U^^^^0,:x` | v2 | 68 32 130 60 68 32 130 60 ... | draws a 4-byte random block and repeats it forever |
| `@0?<$^^^^0.^$$_` | v2 | 0 1 2 3 | private-state counter `0..3` via `@`, then halts |
| `^^^0^^0Xxy` | v3 | 3 2 1 | `3`, `2`, then their bitwise XOR (`3 ^ 2 = 1`) |

### Reference interpreter (Python)
The standalone reference interpreter lives in `bytelisp.py` (standard library only). It supports `version="v1"`, `"v2"`, and `"v3"` (default `"v3"`), Python's `random.Random(seed)` by default, and an optional `SplitMix64(seed)` byte stream.

From the command line:
```bash
python bytelisp.py ',,+xy'
python bytelisp.py --v2 'U^^^^0,:x'
python bytelisp.py --v1 '^^^_:?=x0_vx'
```

### The language written in itself (v1)
Two v1 expressions. Each is shown case by case, then as the exact bytes.

**`EV`** evaluates one expression. Its `$` is the list (expression, EV, argument, h1, h2, h3); h1 to h3 are the `x`, `y`, `z` of the interpreted program.

Pieces of `$` used below:

| Name | Bytes | What it is |
|---|---|---|
| E | `A$` | the expression |
| EV | `AD$` | the evaluator itself |
| ARG | `ADD$` | the argument (`$` of the interpreted program) |
| H | `DDD$` | the list (h1, h2, h3) |
| ARG1 | `ADA$` | the first argument of the expression, unevaluated |
| S1, S2, S3 | `!AD$.ADA$D$`, `!AD$.ADDA$D$`, `!AD$.ADDDA$D$` | the value of the first, second, third argument: EV called on it with the same rest of `$` |

It starts with `=A$A$`: is E something other than a pair? If yes, the first table applies; if no, the second. In each table the tests run top to bottom, and if none matches the value is `_`.

E is a single byte:

| Symbol | Test | Value (bytes) | Meaning |
|---|---|---|---|
| `0` | `=A$'0` | `0` | the byte 0 |
| `,` | `=A$',` | `,` | a fresh random byte |
| `x` | `=A$'x` | `ADDD$` | h1 |
| `y` | `=A$'y` | `ADDDD$` | h2 |
| `z` | `=A$'z` | `ADDDDD$` | h3 |
| `$` | `=A$'$` | `ADD$` | the argument |

E is a list; its first part is tested:

| Symbol | Test | Value (names) | Value (bytes) | Meaning |
|---|---|---|---|---|
| `^` | `=AA$A'^_` | `^ S1` | `^!AD$.ADA$D$` | add one |
| `v` | `=AA$A'v_` | `v S1` | `v!AD$.ADA$D$` | subtract one |
| `A` | `=AA$A'A_` | `A S1` | `A!AD$.ADA$D$` | first part |
| `D` | `=AA$A'D_` | `D S1` | `D!AD$.ADA$D$` | second part |
| `'` | `=AA$A''_` | `ARG1` | `ADA$` | the first argument, unevaluated |
| `+` | `=AA$A'+__` | `+ S1 S2` | `+!AD$.ADA$D$!AD$.ADDA$D$` | sum |
| `-` | `=AA$A'-__` | `- S1 S2` | `-!AD$.ADA$D$!AD$.ADDA$D$` | difference |
| `.` | `=AA$A'.__` | `. S1 S2` | `.!AD$.ADA$D$!AD$.ADDA$D$` | pair |
| `=` | `=AA$A'=__` | `= S1 S2` | `=!AD$.ADA$D$!AD$.ADDA$D$` | equal |
| `!` | `=AA$A'!__` | `! EV . S1 . EV . S2 H` | `!AD$.!AD$.ADA$D$.AD$.!AD$.ADDA$D$DDD$` | evaluate the first value with the second as argument, same h1 to h3 |
| `?` | `=AA$A'?___` | `? S1 S2 S3` | `?!AD$.ADA$D$!AD$.ADDA$D$!AD$.ADDDA$D$` | choose; only the chosen argument is evaluated |

The tests get their numbers by quoting: `'0` is the byte value of `0`, and `A'+__` is the byte value of `+`.

`EV`, exact, 396 bytes (lines of 64; no line breaks in the program):
```
?=A$A$?=A$'00?=A$',,?=A$'xADDD$?=A$'yADDDD$?=A$'zADDDDD$?=A$'$AD
D$_?=AA$A'^_^!AD$.ADA$D$?=AA$A'v_v!AD$.ADA$D$?=AA$A'A_A!AD$.ADA$
D$?=AA$A'D_D!AD$.ADA$D$?=AA$A''_ADA$?=AA$A'+__+!AD$.ADA$D$!AD$.A
DDA$D$?=AA$A'-__-!AD$.ADA$D$!AD$.ADDA$D$?=AA$A'.__.!AD$.ADA$D$!A
D$.ADDA$D$?=AA$A'=__=!AD$.ADA$D$!AD$.ADDA$D$?=AA$A'!__!AD$.!AD$.
ADA$D$.AD$.!AD$.ADDA$D$DDD$?=AA$A'?___?!AD$.ADA$D$!AD$.ADDA$D$!A
D$.ADDDA$D$_
```

**`RUN`** runs a program given as a list of quoted statements and returns the list of statement values; as the value of a statement, that list emits the interpreted program's output. Its `$` is the list (statements left, RUN, EV, statements after the marker, last value, h1, h2, h3).

| Name | Bytes | What it is |
|---|---|---|
| S | `A$` | statements left |
| STMT, REST | `AA$`, `DA$` | the next statement, and the ones after it |
| RUN, EV | `AD$`, `ADD$` | the runner itself, and the evaluator |
| L | `ADDD$` | statements after the marker (`_` until a marker is passed) |
| LAST | `ADDDD$` | the last statement value |
| H | `DDDDD$` | the list (h1, h2, h3) |

The cases, tested in this order (`A$` first: are statements left?):

| Case | Test | Does (names) | Does (bytes) | Meaning |
|---|---|---|---|---|
| statements left, the next is the marker, a marker was already passed | `?A$ =AA$': ADDD$` | `! RUN . REST D $` | `!AD$.DA$D$` | go on with the rest, nothing else changes |
| statements left, the next is the first marker | (the third test fails) | `! RUN . REST . RUN . EV . REST . LAST H` | `!AD$.DA$.AD$.ADD$.DA$.ADDDD$DDDDD$` | go on with the rest and remember it as the loop body |
| statements left, an ordinary statement | (the second test fails) | `! ' CONT . VALUE $` | `!'.A$!ADD$.DAD$.ADD$.ADDD$.ADDDD$.A$?A$.A$.ADDDDDD$.ADDDDDDD$_DDDDDD$.!ADD$.AA$.ADD$._DDDDD$$` | evaluate it (VALUE), then call CONT with the value put in front of `$` |
| no statements left, a loop body is known and the last value is not `_` | `ADDD$ ADDDD$` | `! RUN . L . RUN . EV . L . LAST H` | `!AD$.ADDD$.AD$.ADD$.ADDD$.ADDDD$DDDDD$` | run the loop body again |
| no statements left, otherwise |  | `_` | `_` | end of the list of values |

VALUE is `!ADD$.AA$.ADD$._DDDDD$`: EV called on STMT with argument `_` and H.

CONT is the quoted expression below. Inside it `$` is (V, then the list above), so every name costs one more `D`; V is `A$`:

| Piece | Names | Bytes |
|---|---|---|
| whole | `. V ! RUN (REST RUN EV L V NEWH)` | `.A$!ADD$.DAD$.ADD$.ADDD$.ADDDD$.A$?A$.A$.ADDDDDD$.ADDDDDDD$_DDDDDD$` |
| NEWH | `? V (V h1 h2) H` | `?A$.A$.ADDDDDD$.ADDDDDDD$_DDDDDD$` |

It puts V in front of the values of the rest of the program. LAST becomes V, and V is pushed onto h1, h2, h3 unless it is `_`.

`RUN`, exact, 206 bytes (lines of 64):
```
?A$?=AA$':?ADDD$!AD$.DA$D$!AD$.DA$.AD$.ADD$.DA$.ADDDD$DDDDD$!'.A
$!ADD$.DAD$.ADD$.ADDD$.ADDDD$.A$?A$.A$.ADDDDDD$.ADDDDDDD$_DDDDDD
$.!ADD$.AA$.ADD$._DDDDD$$?ADDD$?ADDDD$!AD$.ADDD$.AD$.ADD$.ADDD$.
ADDDD$DDDDD$__
```

To run a program s1 s2 ... under it, one statement: `!'` RUN `.` P `.'` RUN `.'` EV `._._._._.__`, where P is `.'s1.'s2...` ended by `_` (the marker is written `.':`).

`RUN` returns only when the interpreted program halts, so a program that runs to the output limit shows nothing under it. The interpreter itself has no such restriction.

### Checks
Done with the reference interpreter above, the same random input on both sides:
- `,,+xy`, `,!'+$$x`, `^^^_:?=x0_vx`, `'+,,!x_!y,`: the output under `RUN` equals the direct output.
- 6,000 random byte strings of length 1 to 12 over the 19 v1 symbols: 319 skipped (no halt within 3,000 steps, or 200 bytes emitted); the other 5,681 give the same output directly and under `RUN`.
- `,,+xy` under `RUN` is 838 bytes; under `RUN` running `RUN`, 1,667 bytes; all three give 68 32 100.

### Appendix: using it from a Python REPL
In any Python session started in the repo folder:

```python
import sys
from bytelisp import Machine, parse

sys.setrecursionlimit(100000)


def run(program, seed=1, limit=16, steps=10**6, version="v3"):
    """The row a program emits (a list of bytes)."""
    return Machine(seed, limit, steps, version=version).run(program)


def value(expression, argument=None, seed=1, version="v3"):
    """The value of one expression: an int, None for `_`, or a (first, second) tuple."""
    return Machine(seed, version=version).ev(parse(expression, version=version)[0], argument)


def statements(program, version="v3"):
    """The program split into its statements, missing arguments written out as `_`."""
    def text(t):
        if not isinstance(t, tuple):
            return chr(t)
        s, a = chr(t[0]), t[1]
        while a is not None:
            s += text(a[0])
            a = a[1]
        return s
    return [text(t) for t in parse(program, version=version)]


EV = (
    "?=A$A$?=A$'00?=A$',,?=A$'xADDD$?=A$'yADDDD$?=A$'zADDDDD$?=A$'$AD"
    "D$_?=AA$A'^_^!AD$.ADA$D$?=AA$A'v_v!AD$.ADA$D$?=AA$A'A_A!AD$.ADA$"
    "D$?=AA$A'D_D!AD$.ADA$D$?=AA$A''_ADA$?=AA$A'+__+!AD$.ADA$D$!AD$.A"
    "DDA$D$?=AA$A'-__-!AD$.ADA$D$!AD$.ADDA$D$?=AA$A'.__.!AD$.ADA$D$!A"
    "D$.ADDA$D$?=AA$A'=__=!AD$.ADA$D$!AD$.ADDA$D$?=AA$A'!__!AD$.!AD$."
    "ADA$D$.AD$.!AD$.ADDA$D$DDD$?=AA$A'?___?!AD$.ADA$D$!AD$.ADDA$D$!A"
    'D$.ADDDA$D$_'
)

RUN = (
    "?A$?=AA$':?ADDD$!AD$.DA$D$!AD$.DA$.AD$.ADD$.DA$.ADDDD$DDDDD$!'.A"
    '$!ADD$.DAD$.ADD$.ADDD$.ADDDD$.A$?A$.A$.ADDDDDD$.ADDDDDDD$_DDDDDD'
    '$.!ADD$.AA$.ADD$._DDDDD$$?ADDD$?ADDDD$!AD$.ADDD$.AD$.ADD$.ADDD$.'
    'ADDDD$DDDDD$__'
)


def under(program):
    """The one-statement program that runs `program` under the v1 runner written in the language."""
    return ("!'" + RUN + "." + "".join(".'" + s for s in statements(program, version="v1")) + "_.'" + RUN
            + ".'" + EV + "._._._._.__")
```

Then:

| Call | Result |
|---|---|
| `run(",,+xy")` | `[68, 32, 100]` |
| `run(",,+xy", seed=2)` | `[28, 46, 74]` |
| `run(":0,,+xy")` | `[0, 68, 32, 100, 0, 130, 60, 190, 0, 253, 230, 227, 0, 241, 194, 179]` (cut at `limit=16`) |
| `run(",,?<xyyx", version="v2")` | `[68, 32, 68]` |
| `run("U^^^^0,:x", limit=8, version="v2")` | `[68, 32, 130, 60, 68, 32, 130, 60]` |
| `run("@0?<$^^^^0.^$$_", version="v2")` | `[0, 1, 2, 3]` |
| `run("^^^0^^0Xxy", version="v3")` | `[3, 2, 1]` |
| `value("+^0^^0")` | `3` |
| `value("!'+$$^^0")` | `4` |
| `value("'+,,")` | `(43, (44, (44, None)))` |
| `statements("^^^_:?=x0_vx")` | `['^^^_', ':', '?=x0_vx']` |
| `run(under(",,+xy"), steps=10**7, version="v1")` | `[68, 32, 100]` (`under(",,+xy")` is 838 bytes) |

Notes:
- `seed` fixes the random input, `limit` is the output limit in bytes, `steps` the step budget, `max_pairs` an optional pair-allocation budget. A run that reaches a limit returns what it has emitted.
- The results above are for Python's `random.Random(seed)`; passing `rng=SplitMix64(seed)` selects the splitmix64 byte stream.
- Keep `steps` finite in a session that cannot be interrupted. Because emitting costs steps, every call ends.
- Programs run through `under(...)` recurse deeply in Python; for long ones raise the recursion limit and run in a thread with a large stack (`threading.stack_size`).
- From the command line: `python bytelisp.py ',,+xy'` prints the row for seed 1 with an output limit of 16 (`--v1`, `--v2`, `--v3` select the version).

---

† Aditya Cowsik, Kfir Dolev, Michael Y. Li, G. Bruno De Luca, Nourya Cohen, Noah D. Goodman, and Yoav Levine, *"Self-Play Pretraining with Zero Data"* (2026), [arXiv:2609.30063](https://arxiv.org/abs/2609.30063), Appendix E (Brainf\*ck with 10 textual macros).
