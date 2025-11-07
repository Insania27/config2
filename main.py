import sys
import argparse

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Анализатор зависимостей пакетов",
        add_help=False
    )

    parser.add_argument(
        "--package",
        required=True,
        help="Имя анализируемого пакета"
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="URL репозитория"
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["clone", "local"],
        help="Режим работы с репозиторием"
    )
    parser.add_argument(
        "--max-depth",
        required=True,
        type=int,
        help="Максимальная глубина анализа зависимостей"
    )

    parser.add_argument(
        "--filter",
        required=True,
        default="",
        help="Фильтр"
    )

    if "-h" in sys.argv or "--help" in sys.argv:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()


    if args.max_depth < 0:
        parser.error("--max-depth must be non-negative.")

    return args

def main():
    try:
        args = parse_arguments()
        print(f"package: {args.package}")
        print(f"repo: {args.repo}")
        print(f"mode: {args.mode}")
        print(f"max-depth: {args.max_depth}")
        print(f"filter: {args.filter}")
    except SystemExit as e:
        if e.code != 0:
            print(f"Error: Invalid arguments", file=sys.stderr)
        sys.exit(e.code)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


main()