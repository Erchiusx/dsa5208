#include "chess.hpp"

#include <omp.h>

#ifdef USE_MPI
#include <mpi.h>
#endif

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr int INF = 1000000;
constexpr int MATE = 30000;
constexpr int MAX_GPU_DEPTH = 12;

struct Stats {
    std::uint64_t nodes = 0;
    std::uint64_t leaves = 0;
    std::uint64_t cutoffs = 0;
};

int piece_value(int type) {
    constexpr int values[] = {100, 320, 330, 500, 900, 0};
    return type >= 0 && type < 6 ? values[type] : 0;
}

int evaluate(const chess::Board& board) {
    int white = 0;
    for (int sq = 0; sq < 64; ++sq) {
        const chess::Piece piece = board.at(chess::Square(sq));
        const int code = static_cast<int>(piece);
        if (code < 12) white += code < 6 ? piece_value(code) : -piece_value(code - 6);
    }
    return board.sideToMove() == chess::Color::WHITE ? white : -white;
}

bool drawn(const chess::Board& board) {
    return board.isRepetition() || board.isHalfMoveDraw() || board.isInsufficientMaterial();
}

int negamax(chess::Board& board, int depth, int ply, int alpha, int beta, Stats& stats,
            bool prune = true) {
    ++stats.nodes;
    chess::Movelist moves;
    chess::movegen::legalmoves(moves, board);
    if (moves.empty()) {
        ++stats.leaves;
        return board.inCheck() ? -MATE + ply : 0;
    }
    if (drawn(board)) {
        ++stats.leaves;
        return 0;
    }
    if (depth == 0) {
        ++stats.leaves;
        return evaluate(board);
    }

    int best = -INF;
    for (const chess::Move move : moves) {
        board.makeMove(move);
        const int score = -negamax(board, depth - 1, ply + 1, -beta, -alpha, stats, prune);
        board.unmakeMove(move);
        best = std::max(best, score);
        if (prune) alpha = std::max(alpha, score);
        if (prune && alpha >= beta) {
            ++stats.cutoffs;
            break;
        }
    }
    return best;
}

struct Result {
    int score = -INF;
    int move_index = -1;
    Stats stats;
    double seconds = 0;
    double preparation_seconds = 0;
    double device_seconds = 0;
    bool ran_on_device = false;
    std::size_t tree_nodes = 0;
};

using Clock = std::chrono::steady_clock;
double elapsed(Clock::time_point start) {
    return std::chrono::duration<double>(Clock::now() - start).count();
}

Result serial_search(const chess::Board& initial, const chess::Movelist& moves, int depth,
                     bool prune = true) {
    Result result;
    auto start = Clock::now();
    if (moves.empty()) {
        chess::Board board = initial;
        result.score = negamax(board, depth, 0, -INF, INF, result.stats, prune);
    } else if (drawn(initial)) {
        result.score = 0;
        result.stats.nodes = result.stats.leaves = 1;
    } else {
        result.stats.nodes = 1;
        int alpha = -INF;
        for (int i = 0; i < moves.size(); ++i) {
            chess::Board board = initial;
            board.makeMove(moves[i]);
            const int score = -negamax(board, depth - 1, 1, -INF, prune ? -alpha : INF,
                                       result.stats, prune);
            if (score > result.score) {
                result.score = score;
                result.move_index = i;
            }
            if (prune) alpha = std::max(alpha, score);
        }
    }
    result.seconds = elapsed(start);
    return result;
}

Result root_search(const chess::Board& initial, const chess::Movelist& moves, int depth,
                   bool use_omp, bool use_mpi, int rank, int ranks) {
    Result result;
    if (moves.empty() || drawn(initial)) return serial_search(initial, moves, depth);
    auto start = Clock::now();
    std::vector<int> scores(moves.size(), -INF);
    std::vector<Stats> per_move(moves.size());
    const int n = moves.size();
#pragma omp parallel for schedule(dynamic, 1) if(use_omp)
    for (int i = 0; i < n; ++i) {
        if (use_mpi && i % ranks != rank) continue;
        chess::Board board = initial;
        board.makeMove(moves[i]);
        scores[i] = -negamax(board, depth - 1, 1, -INF, INF, per_move[i]);
    }
#ifdef USE_MPI
    if (use_mpi) {
        std::vector<int> combined(n);
        MPI_Allreduce(scores.data(), combined.data(), n, MPI_INT, MPI_MAX, MPI_COMM_WORLD);
        scores.swap(combined);
    }
#endif
    for (int i = 0; i < n; ++i) {
        if (scores[i] > result.score) {
            result.score = scores[i];
            result.move_index = i;
        }
        result.stats.nodes += per_move[i].nodes;
        result.stats.leaves += per_move[i].leaves;
        result.stats.cutoffs += per_move[i].cutoffs;
    }
    result.stats.nodes += rank == 0 ? 1 : 0;
#ifdef USE_MPI
    if (use_mpi) {
        std::uint64_t local[] = {result.stats.nodes, result.stats.leaves, result.stats.cutoffs};
        std::uint64_t total[3];
        MPI_Allreduce(local, total, 3, MPI_UINT64_T, MPI_SUM, MPI_COMM_WORLD);
        result.stats = {total[0], total[1], total[2]};
    }
#endif
    result.seconds = elapsed(start);
#ifdef USE_MPI
    if (use_mpi) {
        double longest = 0;
        MPI_Allreduce(&result.seconds, &longest, 1, MPI_DOUBLE, MPI_MAX, MPI_COMM_WORLD);
        result.seconds = longest;
    }
#endif
    return result;
}

struct FrontierNode {
    int first_child = -1;
    int child_count = 0;
    int task_index = -1;
};

struct Frontier {
    std::vector<FrontierNode> nodes;
    std::vector<chess::Board> boards;
    std::vector<int> task_plies;
};

void build_frontier(Frontier& frontier, int index, chess::Board& board, int levels, int ply,
                    std::size_t max_nodes) {
    chess::Movelist moves;
    chess::movegen::legalmoves(moves, board);
    if (levels == 0 || moves.empty() || drawn(board)) {
        frontier.nodes[index].task_index = static_cast<int>(frontier.boards.size());
        frontier.boards.push_back(board);
        frontier.task_plies.push_back(ply);
        return;
    }
    if (frontier.nodes.size() + static_cast<std::size_t>(moves.size()) > max_nodes)
        throw std::runtime_error("CPU frontier exceeds --max-tree-nodes; lower --split-depth");
    const int first = static_cast<int>(frontier.nodes.size());
    frontier.nodes.resize(frontier.nodes.size() + moves.size());
    frontier.nodes[index].first_child = first;
    frontier.nodes[index].child_count = moves.size();
    for (int i = 0; i < moves.size(); ++i) {
        board.makeMove(moves[i]);
        build_frontier(frontier, first + i, board, levels - 1, ply + 1, max_nodes);
        board.unmakeMove(moves[i]);
    }
}

int combine_frontier(const Frontier& frontier, int index, const std::vector<int>& scores) {
    const FrontierNode& node = frontier.nodes[index];
    if (node.task_index >= 0) return scores[node.task_index];
    int best = -INF;
    for (int i = 0; i < node.child_count; ++i)
        best = std::max(best, -combine_frontier(frontier, node.first_child + i, scores));
    return best;
}

Result frontier_search(const chess::Board& initial, int depth, int split_depth,
                       std::size_t max_nodes, bool use_mpi, int rank, int ranks) {
    auto start = Clock::now();
    Frontier frontier;
    frontier.nodes.resize(1);
    chess::Board board = initial;
    build_frontier(frontier, 0, board, split_depth, 0, max_nodes);
    const int n = static_cast<int>(frontier.boards.size());
    std::vector<int> scores(n, -INF);
    std::vector<Stats> per_task(n);
#pragma omp parallel for schedule(dynamic, 1)
    for (int i = 0; i < n; ++i) {
        if (use_mpi && i % ranks != rank) continue;
        scores[i] = negamax(frontier.boards[i], depth - frontier.task_plies[i], frontier.task_plies[i],
                            -INF, INF, per_task[i]);
    }
#ifdef USE_MPI
    if (use_mpi) {
        std::vector<int> combined(n);
        MPI_Allreduce(scores.data(), combined.data(), n, MPI_INT, MPI_MAX, MPI_COMM_WORLD);
        scores.swap(combined);
    }
#endif
    Result result;
    result.tree_nodes = frontier.nodes.size();
    if (frontier.nodes[0].task_index >= 0) {
        result.score = scores[frontier.nodes[0].task_index];
    } else {
        const FrontierNode& root = frontier.nodes[0];
        for (int i = 0; i < root.child_count; ++i) {
            const int score = -combine_frontier(frontier, root.first_child + i, scores);
            if (score > result.score) {
                result.score = score;
                result.move_index = i;
            }
        }
    }
    for (int i = 0; i < n; ++i) {
        result.stats.nodes += per_task[i].nodes;
        result.stats.leaves += per_task[i].leaves;
        result.stats.cutoffs += per_task[i].cutoffs;
    }
    if (rank == 0) result.stats.nodes += frontier.nodes.size() - frontier.boards.size();
#ifdef USE_MPI
    if (use_mpi) {
        std::uint64_t local[] = {result.stats.nodes, result.stats.leaves, result.stats.cutoffs};
        std::uint64_t total[3];
        MPI_Allreduce(local, total, 3, MPI_UINT64_T, MPI_SUM, MPI_COMM_WORLD);
        result.stats = {total[0], total[1], total[2]};
    }
#endif
    result.seconds = elapsed(start);
#ifdef USE_MPI
    if (use_mpi) {
        double longest = 0;
        MPI_Allreduce(&result.seconds, &longest, 1, MPI_DOUBLE, MPI_MAX, MPI_COMM_WORLD);
        result.seconds = longest;
    }
#endif
    return result;
}

// The external library builds the complete legal tree on the host. Only the
// alpha-beta traversal and leaf evaluation of this tree are offloaded.
struct TreeNode {
    int first_child = -1;
    int child_count = 0;
    int leaf_index = -1;
    int terminal_score = 0;
};

struct LeafBoard {
    std::int8_t pieces[64] = {};
    std::int8_t side_to_move = 0;
};

struct Tree {
    std::vector<TreeNode> nodes;
    std::vector<LeafBoard> leaves;
};

void build_node(Tree& tree, int index, chess::Board& board, int depth, int ply,
                std::size_t max_nodes) {
    chess::Movelist moves;
    chess::movegen::legalmoves(moves, board);
    if (moves.empty()) {
        tree.nodes[index].terminal_score = board.inCheck() ? -MATE + ply : 0;
        return;
    }
    if (drawn(board)) return;
    if (depth == 0) {
        LeafBoard leaf;
        for (int sq = 0; sq < 64; ++sq)
            leaf.pieces[sq] = static_cast<std::int8_t>(static_cast<int>(board.at(chess::Square(sq))));
        leaf.side_to_move = board.sideToMove() == chess::Color::WHITE ? 0 : 1;
        tree.nodes[index].leaf_index = static_cast<int>(tree.leaves.size());
        tree.leaves.push_back(leaf);
        return;
    }
    if (tree.nodes.size() + static_cast<std::size_t>(moves.size()) > max_nodes)
        throw std::runtime_error("GPU tree exceeds --max-tree-nodes; choose a shallower depth");
    const int first = static_cast<int>(tree.nodes.size());
    tree.nodes.resize(tree.nodes.size() + moves.size());
    tree.nodes[index].first_child = first;
    tree.nodes[index].child_count = moves.size();
    for (int i = 0; i < moves.size(); ++i) {
        board.makeMove(moves[i]);
        build_node(tree, first + i, board, depth - 1, ply + 1, max_nodes);
        board.unmakeMove(moves[i]);
    }
}

#pragma omp declare target

int device_piece_value(int type) {
    switch (type) {
        case 0: return 100;
        case 1: return 320;
        case 2: return 330;
        case 3: return 500;
        case 4: return 900;
        default: return 0;
    }
}

int device_evaluate(const LeafBoard& board) {
    int white = 0;
    for (int sq = 0; sq < 64; ++sq) {
        const int code = board.pieces[sq];
        if (code < 12) white += code < 6 ? device_piece_value(code) : -device_piece_value(code - 6);
    }
    return board.side_to_move == 0 ? white : -white;
}

struct Frame {
    int index;
    int next;
    int best;
    int alpha;
    int beta;
};

int device_search(const TreeNode* nodes, const LeafBoard* leaves, int root,
                  std::uint64_t* visited, std::uint64_t* leaf_visits, std::uint64_t* cutoffs) {
    Frame stack[MAX_GPU_DEPTH + 2];
    int top = 0;
    stack[0] = {root, 0, -INF, -INF, INF};
    *visited = 1;
    *leaf_visits = 0;
    *cutoffs = 0;
    while (top >= 0) {
        Frame& current = stack[top];
        const TreeNode& node = nodes[current.index];
        if (node.child_count == 0 || current.next >= node.child_count || current.alpha >= current.beta) {
            int value = current.best;
            if (node.child_count == 0) {
                ++*leaf_visits;
                value = node.leaf_index >= 0 ? device_evaluate(leaves[node.leaf_index]) : node.terminal_score;
            }
            --top;
            if (top < 0) return value;
            Frame& parent = stack[top];
            const int score = -value;
            if (score > parent.best) parent.best = score;
            if (score > parent.alpha) parent.alpha = score;
            if (parent.alpha >= parent.beta && parent.next < nodes[parent.index].child_count) ++*cutoffs;
            continue;
        }
        const int child = node.first_child + current.next++;
        const int child_alpha = -current.beta;
        const int child_beta = -current.alpha;
        ++top;
        stack[top] = {child, 0, -INF, child_alpha, child_beta};
        ++*visited;
    }
    return 0;
}

#pragma omp end declare target

Result gpu_search(const chess::Board& initial, const chess::Movelist& moves, int depth,
                  std::size_t max_nodes, bool require_device) {
    if (depth > MAX_GPU_DEPTH) throw std::runtime_error("GPU depth exceeds fixed device stack");
    if (moves.empty() || drawn(initial)) {
        if (require_device) throw std::runtime_error("no offloadable root moves in this position");
        return serial_search(initial, moves, depth);
    }
    Result result;
    auto total_start = Clock::now();
    Tree tree;
    tree.nodes.resize(moves.size());
    for (int i = 0; i < moves.size(); ++i) {
        chess::Board board = initial;
        board.makeMove(moves[i]);
        build_node(tree, i, board, depth - 1, 1, max_nodes);
    }
    result.preparation_seconds = elapsed(total_start);
    result.tree_nodes = tree.nodes.size();
    if (tree.leaves.empty()) tree.leaves.emplace_back();

    const int n = moves.size();
    const int node_count = static_cast<int>(tree.nodes.size());
    const int leaf_count = static_cast<int>(tree.leaves.size());
    TreeNode* nodes = tree.nodes.data();
    LeafBoard* leaves = tree.leaves.data();
    std::vector<int> scores(n);
    std::vector<std::uint64_t> visited(n), leaf_visits(n), cutoffs(n);
    int* score_ptr = scores.data();
    std::uint64_t* visit_ptr = visited.data();
    std::uint64_t* leaf_visit_ptr = leaf_visits.data();
    std::uint64_t* cutoff_ptr = cutoffs.data();
    int on_device = 0;
    auto device_start = Clock::now();
#pragma omp target map(from: on_device)
    { on_device = !omp_is_initial_device(); }
    if (require_device && !on_device)
        throw std::runtime_error("OpenMP target fell back to CPU; use --backend gpu-host for a host smoke test");
#pragma omp target teams distribute parallel for map(to: nodes[0:node_count], leaves[0:leaf_count]) map(from: score_ptr[0:n], visit_ptr[0:n], leaf_visit_ptr[0:n], cutoff_ptr[0:n])
    for (int i = 0; i < n; ++i)
        score_ptr[i] = -device_search(nodes, leaves, i, &visit_ptr[i], &leaf_visit_ptr[i], &cutoff_ptr[i]);
    result.device_seconds = elapsed(device_start);
    result.ran_on_device = on_device != 0;
    result.seconds = elapsed(total_start);
    result.stats.nodes = 1;
    for (int i = 0; i < n; ++i) {
        if (scores[i] > result.score) {
            result.score = scores[i];
            result.move_index = i;
        }
        result.stats.nodes += visited[i];
        result.stats.leaves += leaf_visits[i];
        result.stats.cutoffs += cutoffs[i];
    }
    return result;
}

struct Options {
    std::string backend = "serial";
    std::string fen = std::string(chess::constants::STARTPOS);
    int depth = 4;
    int threads = 1;
    int split_depth = 1;
    std::size_t max_tree_nodes = 2000000;
};

Options parse_options(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--help") {
            std::cout << "Usage: chess_search [--backend serial|minimax|omp|mpi|gpu|gpu-host] "
                         "[--depth N] [--threads N] [--split-depth N] "
                         "[--fen 'FEN'] [--max-tree-nodes N]\n";
            std::exit(0);
        }
        if (i + 1 >= argc) throw std::runtime_error("missing value for " + arg);
        const std::string value = argv[++i];
        if (arg == "--backend") options.backend = value;
        else if (arg == "--depth") options.depth = std::stoi(value);
        else if (arg == "--threads") options.threads = std::stoi(value);
        else if (arg == "--split-depth") options.split_depth = std::stoi(value);
        else if (arg == "--fen") options.fen = value;
        else if (arg == "--max-tree-nodes") options.max_tree_nodes = std::stoull(value);
        else throw std::runtime_error("unknown option: " + arg);
    }
    if (options.depth < 1 || options.depth > MAX_GPU_DEPTH || options.threads < 1 || options.max_tree_nodes < 1 ||
        options.split_depth < 1 || options.split_depth > options.depth)
        throw std::runtime_error("depth must be 1..12; split-depth must be 1..depth; other counts positive");
    return options;
}

}  // namespace

int main(int argc, char** argv) {
    int rank = 0;
    int ranks = 1;
#ifdef USE_MPI
    int provided = 0;
    MPI_Init_thread(&argc, &argv, MPI_THREAD_FUNNELED, &provided);
    if (provided < MPI_THREAD_FUNNELED) {
        std::cerr << "MPI_THREAD_FUNNELED is required\n";
        MPI_Abort(MPI_COMM_WORLD, 2);
    }
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &ranks);
#endif
    try {
        const Options options = parse_options(argc, argv);
        if (ranks > 1 && options.backend != "mpi")
            throw std::runtime_error("multiple MPI ranks require --backend mpi");
        if (options.split_depth != 1 && options.backend != "omp" && options.backend != "mpi")
            throw std::runtime_error("--split-depth above 1 requires --backend omp or mpi");
#ifndef USE_MPI
        if (options.backend == "mpi") throw std::runtime_error("rebuild with mpic++ and -DUSE_MPI");
#endif
        omp_set_num_threads(options.threads);
        chess::Board board;
        if (!board.setFen(options.fen)) throw std::runtime_error("invalid FEN");
        chess::Movelist moves;
        chess::movegen::legalmoves(moves, board);
        Result result;
        if (options.backend == "serial") result = serial_search(board, moves, options.depth);
        else if (options.backend == "minimax") result = serial_search(board, moves, options.depth, false);
        else if (options.backend == "omp" || options.backend == "mpi") {
            if (options.split_depth == 1)
                result = root_search(board, moves, options.depth, options.backend == "omp" || options.threads > 1,
                                     options.backend == "mpi", rank, ranks);
            else
                result = frontier_search(board, options.depth, options.split_depth,
                                         options.max_tree_nodes, options.backend == "mpi", rank, ranks);
        }
        else if (options.backend == "gpu" || options.backend == "gpu-host")
            result = gpu_search(board, moves, options.depth, options.max_tree_nodes, options.backend == "gpu");
        else throw std::runtime_error("unknown backend: " + options.backend);

        if (rank == 0) {
            const std::string move = result.move_index < 0 ? "none" : chess::uci::moveToUci(moves[result.move_index]);
            std::cout << "backend=" << options.backend << " depth=" << options.depth
                      << " ranks=" << ranks << " threads=" << options.threads
                      << " score=" << result.score << " move=" << move
                      << " split_depth=" << options.split_depth
                      << " nodes=" << result.stats.nodes << " leaves=" << result.stats.leaves
                      << " cutoffs=" << result.stats.cutoffs << " seconds=" << result.seconds;
            if (options.split_depth > 1 && (options.backend == "omp" || options.backend == "mpi"))
                std::cout << " frontier_nodes=" << result.tree_nodes;
            if (options.backend == "gpu" || options.backend == "gpu-host")
                std::cout << " tree_nodes=" << result.tree_nodes
                          << " preparation_seconds=" << result.preparation_seconds
                          << " target_seconds=" << result.device_seconds
                          << " ran_on_device=" << result.ran_on_device;
            std::cout << '\n';
        }
#ifdef USE_MPI
        MPI_Finalize();
#endif
        return 0;
    } catch (const std::exception& error) {
        if (rank == 0) std::cerr << "error: " << error.what() << '\n';
#ifdef USE_MPI
        MPI_Abort(MPI_COMM_WORLD, 1);
#endif
        return 1;
    }
}
