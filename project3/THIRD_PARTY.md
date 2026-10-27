# Third-party software declaration

| Component | Source and pinned revision | License | Used for |
| --- | --- | --- | --- |
| `chess-library` by disservin | https://github.com/Disservin/chess-library at `2a608d58f44776909bb6e2c09505e97ba1451319` | MIT; see `third_party/chess-library/LICENSE` | FEN parsing, board state, legal move generation, move application/reversal, draw-rule helpers, UCI formatting |

The vendored `third_party/chess-library/chess.hpp` is unmodified. Its SHA-256
is `905b95c2ac870e488a5262c992e3aed0907a2233eb95b9a2835a3d47d9a3cf5d`.

The serial minimax/alpha-beta search, OpenMP and MPI task scheduling, GPU
search over a pre-expanded tree, material evaluation, tests, and PBS scripts
are this project's code. The instructor explicitly accepted using a credited
external library for legal moves and FEN parsing. This declaration should be
included with the source submission and summarized in the PDF report.
