import sys
import argparse
import os
import tempfile
import subprocess
import shutil
import re

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Анализатор зависимостей пакетов (этап 2)",
        add_help=False
    )

    parser.add_argument("--package", required=True, help="Имя анализируемого пакета")
    parser.add_argument("--repo", required=True, help="URL репозитория или путь к локальной директории/файлу")
    parser.add_argument("--mode", required=True, choices=["clone", "local"], help="Режим работы с репозиторием")
    parser.add_argument("--max-depth", required=True, type=int, help="Максимальная глубина анализа зависимостей")
    parser.add_argument("--filter", required=False, default="", help="Фильтр (не используется на этом этапе)")

    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    if args.max_depth < 0:
        parser.error("--max-depth must be non-negative.")

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

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception as e:
        raise RuntimeError(f"Failed to read file {path}: {e}")

def parse_toml_package_name(lines):
    in_package = False
    name_re = re.compile(r'^\s*name\s*=\s*["\']([^"\']+)["\']')
    for line in lines:
        line_strip = line.strip()
        if line_strip.startswith("[") and line_strip.lower().startswith("[package"):
            in_package = True
            continue
        if in_package:
            if line_strip.startswith("["):
                break
            m = name_re.match(line)
            if m:
                return m.group(1)
    return None

def extract_dependencies(lines):
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

def locate_package_cargo_toml(root_dir, package_name):
    tomls = find_cargo_tomls(root_dir)
    if not tomls:
        raise RuntimeError("No Cargo.toml found in repository.")
    for path in tomls:
        lines = read_file(path)
        name = parse_toml_package_name(lines)
        if name == package_name:
            return path
    if len(tomls) == 1:
        return tomls[0]
    for path in tomls:
        if os.path.basename(os.path.dirname(path)) == package_name:
            return path
    raise RuntimeError(f"Cargo.toml for package '{package_name}' not found.")

def main():
    try:
        args = parse_arguments()
        workdir = None
        try:
            if args.mode == "clone":
                workdir = tempfile.mkdtemp(prefix="repo_clone_")
                run_git_clone(args.repo, workdir)
            else:
                if not os.path.exists(args.repo):
                    raise RuntimeError(f"Local path does not exist: {args.repo}")
                if os.path.isfile(args.repo):
                    if os.path.basename(args.repo).lower() == "cargo.toml":
                        workdir = os.path.dirname(os.path.abspath(args.repo))
                    else:
                        raise RuntimeError("Provided file is not Cargo.toml")
                else:
                    workdir = os.path.abspath(args.repo)

            cargo_toml_path = locate_package_cargo_toml(workdir, args.package)
            lines = read_file(cargo_toml_path)
            deps = extract_dependencies(lines)

            if args.filter:
                deps = [d for d in deps if args.filter in d]

            for d in deps:
                print(d)

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
