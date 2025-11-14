import sys
import argparse
import os
import tempfile
import subprocess
import shutil
import re

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Анализатор зависимостей пакетов (этап 3)",
        add_help=False
    )

    parser.add_argument("--package", required=True, help="Имя анализируемого пакета (или стартовая вершина в test mode)")
    parser.add_argument("--repo", required=True, help="Git URL / локальный путь / путь к test-файлу (в режиме test)")
    parser.add_argument("--mode", required=True, choices=["clone", "local", "test"], help="Режим работы с репозиторием")
    parser.add_argument("--max-depth", required=True, type=int, help="Максимальная глубина анализа зависимостей (0..N)")
    parser.add_argument("--filter", required=False, default="", help="Подстрока для исключения пакетов; '-' трактуется как пустой фильтр")

    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    if args.max_depth < 0:
        parser.error("--max-depth must be non-negative.")

    if args.filter == "-":
        args.filter = ""

    return args


def run_git_clone(repo_url, dest_dir):
    try:
        subprocess.check_call(["git", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        raise RuntimeError("git is not available on PATH.")
    try:
        subprocess.check_call(["git", "clone", "--depth", "1", repo_url, dest_dir],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"git clone failed: {e.stderr.decode().strip() if isinstance(e.stderr, bytes) else str(e)}")


def find_cargo_tomls(root_dir):
    matches = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if "Cargo.toml" in filenames:
            matches.append(os.path.join(dirpath, "Cargo.toml"))
    return matches

def read_file_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception as e:
        raise RuntimeError(f"Failed to read file {path}: {e}")

def parse_toml_package_name(lines):
    in_package = False
    name_re = re.compile(r'^\s*name\s*=\s*["\']([^"\']+)["\']')
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.lower().startswith("[package"):
            in_package = True
            continue
        if in_package:
            if s.startswith("["):
                break
            m = name_re.match(line)
            if m:
                return m.group(1)
    return None

def parse_toml_dependencies(lines):
    deps = set()
    in_dependencies = False
    dep_section_re = re.compile(r'^\s*\[dependencies\]\s*$', re.IGNORECASE)
    dep_table_re = re.compile(r'^\s*\[dependencies\.([^\]]+)\]\s*$', re.IGNORECASE)
    key_val_re = re.compile(r'^\s*([A-Za-z0-9_\-]+)\s*=')
    inline_deps_re = re.compile(r'^\s*dependencies\s*=\s*{')
    for i, line in enumerate(lines):
        if dep_section_re.match(line):
            in_dependencies = True
            continue
        m_table = dep_table_re.match(line)
        if m_table:
            name = m_table.group(1).strip().strip('"').strip("'")
            if name:
                deps.add(name)
            in_dependencies = False
            continue
        if in_dependencies:
            if line.strip().startswith("[") and not dep_section_re.match(line):
                in_dependencies = False
                continue
            s = line.split("#", 1)[0].strip()
            if not s:
                continue
            m_kv = key_val_re.match(s)
            if m_kv:
                deps.add(m_kv.group(1).strip())
                continue
        if inline_deps_re.match(line):
            inline = line
            j = i + 1
            while "}" not in inline and j < len(lines):
                inline += " " + lines[j]
                j += 1
            for m in re.finditer(r'([A-Za-z0-9_\-]+)\s*=', inline):
                deps.add(m.group(1))
    return sorted(deps)


def parse_test_graph_file(path):
    if not os.path.exists(path):
        raise RuntimeError(f"Test graph file not found: {path}")
    graph = {}
    for raw in read_file_lines(path):
        line = raw.split("#",1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            raise RuntimeError(f"Bad line in test file (expected 'A: B C'): {raw}")
        left, right = line.split(":",1)
        node = left.strip()
        if not node:
            continue
        deps = [tok for tok in right.strip().split() if tok]
        graph[node] = deps
    return graph


def build_graph_from_repo(root_dir):
    tomls = find_cargo_tomls(root_dir)
    packages = {}
    name_to_path = {}
    for t in tomls:
        lines = read_file_lines(t)
        name = parse_toml_package_name(lines)
        deps = parse_toml_dependencies(lines)
        if name:
            packages[name] = deps
            name_to_path[name] = t
    all_nodes = dict((k, list(v)) for k, v in packages.items())
    for deps in packages.values():
        for d in deps:
            if d not in all_nodes:
                all_nodes[d] = []
    return all_nodes


def bfs_recursive_levels(start, graph, max_depth, filter_substr):
    visited = set()
    levels = []

    if filter_substr and filter_substr in start:
        return visited, levels

    levels.append([start])
    visited.add(start)

    def recurse(frontier, depth):
        if depth >= max_depth:
            return
        next_frontier = []
        for node in frontier:
            for nbr in graph.get(node, []):
                if filter_substr and filter_substr in nbr:
                    continue
                if nbr not in visited:
                    visited.add(nbr)
                    next_frontier.append(nbr)
        if next_frontier:
            levels.append(next_frontier)
            recurse(next_frontier, depth + 1)

    recurse(levels[0], 0)
    return visited, levels

def collect_edges_within_levels(levels, graph):
    edges = []
    nodes_set = set()
    for lvl in levels:
        nodes_set.update(lvl)
    for node in nodes_set:
        for nbr in graph.get(node, []):
            if nbr in nodes_set:
                edges.append((node, nbr))
    return edges


def main():
    try:
        args = parse_arguments()

        workdir = None
        graph = {}

        try:
            if args.mode == "clone":
                workdir = tempfile.mkdtemp(prefix="repo_clone_")
                run_git_clone(args.repo, workdir)
                graph = build_graph_from_repo(workdir)
            elif args.mode == "local":
                if not os.path.exists(args.repo):
                    raise RuntimeError(f"Local path does not exist: {args.repo}")
                if os.path.isfile(args.repo) and os.path.basename(args.repo).lower() == "cargo.toml":
                    base = os.path.dirname(os.path.abspath(args.repo))
                    graph = build_graph_from_repo(base)
                else:
                    graph = build_graph_from_repo(os.path.abspath(args.repo))
            else:
                graph = parse_test_graph_file(args.repo)

            start = args.package
            if start not in graph:

                if args.mode == "test":
                    raise RuntimeError(f"Start node '{start}' not found in test graph.")
                else:
                    graph.setdefault(start, [])

            visited, levels = bfs_recursive_levels(start, graph, args.max_depth, args.filter)

            edges = collect_edges_within_levels(levels, graph)

            for a, b in sorted(edges):
                print(f"{a} -> {b}")

            if levels:
                for i, lvl in enumerate(levels):
                    print(f"Level {i}: {' '.join(lvl)}")

        finally:
            if args.mode == "clone" and workdir and os.path.isdir(workdir):
                try:
                    shutil.rmtree(workdir)
                except Exception:
                    pass

    except SystemExit as e:
        if e.code != 0:
            print("Error: Invalid arguments", file=sys.stderr)
        sys.exit(e.code)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

main()
