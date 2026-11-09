"""Draw appendix chessboards directly from the benchmark FEN definitions."""

import ast
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle


PROJECT = Path(__file__).resolve().parents[1]
ASSETS = PROJECT / "report" / "assets"
ASSETS.mkdir(exist_ok=True)


def benchmark_fens():
    tree = ast.parse((PROJECT / "scripts" / "multiposition.py").read_text())
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "POSITIONS" for target in node.targets)
    )
    return {"initial": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", **ast.literal_eval(assignment.value)}


CASES = [
    ("initial", "Initial position", 8),
    ("kiwipete", "Kiwipete", 6),
    ("rook_endgame", "Rook/pawn", 9),
    ("tactical", "Tactical", 6),
    ("minor_endgame", "Minor pieces", 9),
    ("ruy_lopez", "Ruy Lopez", 4),
    ("queens_gambit", "Queen's Gambit", 4),
]
GLYPHS = dict(zip("KQRBNPkqrbnp", "♔♕♖♗♘♙♚♛♜♝♞♟"))


def parse_fen(fen):
    parts = fen.split()
    assert len(parts) == 6, fen
    rows = parts[0].split("/")
    assert len(rows) == 8 and parts[1] in ("w", "b"), fen
    board = []
    for row in rows:
        squares = []
        for char in row:
            if char.isdigit():
                assert char in "12345678", fen
                squares.extend([None] * int(char))
            else:
                assert char in GLYPHS, fen
                squares.append(char)
        assert len(squares) == 8, fen
        board.append(squares)
    assert sum(piece == "K" for row in board for piece in row) == 1
    assert sum(piece == "k" for row in board for piece in row) == 1
    return board, parts[1]


def check_appendix_fens(fens):
    appendix = (PROJECT / "report" / "main.tex").read_text().split("\\section{Exact benchmark positions}", 1)[1]
    items = re.findall(r"\\item\[([^]]+)\](.*?)(?=\\item\[|\\end\{description\})", appendix, re.S)
    assert len(items) == len(CASES), "Appendix and board count differ"
    for (key, title, depth), (label, body) in zip(CASES, items):
        assert label == f"{title} (depth {depth})", (label, title)
        report_fen = " ".join(re.findall(r"\\texttt\{([^}]+)\}", body))
        assert report_fen == fens[key], (key, report_fen, fens[key])


def draw_board(ax, fen, title, depth):
    board, side = parse_fen(fen)
    for row in range(8):
        for col in range(8):
            square = "#F0E9DC" if (row + col) % 2 == 0 else "#748FA1"
            ax.add_patch(Rectangle((col, row), 1, 1, facecolor=square, edgecolor="none"))
            piece = board[row][col]
            if piece:
                white = piece.isupper()
                face = "#FFFCF5" if white else "#263B4B"
                ink = "#1D3444" if white else "#FFFDF6"
                ax.add_patch(Circle((col + .5, row + .5), .405, facecolor=face,
                                    edgecolor="#1D3444" if white else "#FFFDF6", linewidth=.8))
                ax.text(col + .5, row + .505, GLYPHS[piece], ha="center", va="center",
                        fontsize=24, color=ink, fontfamily="DejaVu Sans")
    ax.set_xlim(0, 8)
    ax.set_ylim(8, 0)
    ax.set_aspect("equal")
    ax.set_xticks([i + .5 for i in range(8)], list("abcdefgh"), fontsize=8)
    ax.set_yticks([i + .5 for i in range(8)], list("87654321"), fontsize=8)
    ax.tick_params(length=0, pad=2)
    for spine in ax.spines.values():
        spine.set_color("#344E5E")
        spine.set_linewidth(.8)
    who = "White" if side == "w" else "Black"
    ax.set_title(f"{title}  |  depth {depth}\n{who} to move", fontsize=10.5,
                 color="#173C52", fontweight="bold", pad=9)


def fen_lines(fen, width=43):
    """Break at rank separators where possible without omitting FEN characters."""
    placement, fields = fen.split(" ", 1)
    rank_tokens = [rank + ("/" if i < 7 else "") for i, rank in enumerate(placement.split("/"))]
    lines = []
    current = ""
    for token in rank_tokens:
        if current and len(current + token) > width:
            lines.append(current)
            current = ""
        current += token
    if len(current) + 1 + len(fields) <= width:
        current += " " + fields
    else:
        lines.append(current)
        current = fields
    lines.append(current)
    rebuilt = "".join(lines[:-1]) + " " + fields if lines[-1] == fields else "".join(lines)
    assert rebuilt == fen
    return lines


def make_page(cases, fens, path):
    fig = plt.figure(figsize=(8.0, 9.2), layout="constrained")
    grid = fig.add_gridspec(2, 2, wspace=.13, hspace=.12)
    for index, (key, title, depth) in enumerate(cases):
        cell = grid[index // 2, index % 2].subgridspec(2, 1, height_ratios=[8.4, 1.2], hspace=.04)
        ax = fig.add_subplot(cell[0])
        draw_board(ax, fens[key], title, depth)
        label = fig.add_subplot(cell[1])
        label.axis("off")
        lines = fen_lines(fens[key])
        label.text(.015, .98, "FEN: " + lines[0] + "\n" + "\n".join("        " + line for line in lines[1:]),
                   transform=label.transAxes, ha="left", va="top", fontsize=8.5,
                   fontfamily="DejaVu Sans Mono", color="#253342", linespacing=1.25)
    if len(cases) == 3:
        ax = fig.add_subplot(grid[1, 1])
        ax.axis("off")
        ax.text(.08, .85, "How to read these boards", transform=ax.transAxes,
                fontsize=13, fontweight="bold", color="#173C52")
        ax.text(.08, .66,
                "White is at the bottom in every diagram.\n"
                "Files a-h run from left to right; ranks\n"
                "1-8 run from bottom to top.\n\n"
                "The label gives the side to move and the\n"
                "fixed search depth. FEN line breaks are\n"
                "typographic; join the lines to recover the\n"
                "exact input. No diagram is a best move.",
                transform=ax.transAxes, fontsize=10.5, va="top", linespacing=1.5,
                color="#344E5E")
    fig.savefig(path, bbox_inches="tight", pad_inches=.08)
    plt.close(fig)


if __name__ == "__main__":
    fens = benchmark_fens()
    assert set(fens) == {key for key, _, _ in CASES}
    check_appendix_fens(fens)
    for fen in fens.values():
        parse_fen(fen)
    make_page(CASES[:4], fens, ASSETS / "boards_1.pdf")
    make_page(CASES[4:], fens, ASSETS / "boards_2.pdf")
    print("Generated seven boards in two vector figure pages; all FENs match the appendix")
