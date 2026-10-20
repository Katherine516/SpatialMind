"""Local knowledge CLI: python -m spatialmind.knowledge --database PATH COMMAND."""

import argparse
import json
from pathlib import Path

from .compiler import compile_page
from .evaluation import evaluate
from .store import KnowledgeStore


def main():
    parser = argparse.ArgumentParser(description="SpatialMind local research wiki")
    parser.add_argument("--database", required=True, help="Workspace knowledge.sqlite path")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health")
    sub.add_parser("sources")
    sub.add_parser("pages")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--scope", default="general")
    draft = sub.add_parser("compile")
    draft.add_argument("--title", required=True)
    draft.add_argument("--sources", nargs="+", required=True)
    draft.add_argument("--scope", default="general")
    draft.add_argument("--page-id")
    bench = sub.add_parser("evaluate")
    bench.add_argument("benchmark")
    args = parser.parse_args()
    store = KnowledgeStore(Path(args.database))
    if args.command == "health":
        result = store.workspace.health()
    elif args.command == "sources":
        result = store.list_sources()
    elif args.command == "pages":
        result = store.workspace.pages()
    elif args.command == "search":
        result = {"passages": store.search(args.query, scope=args.scope), "pages": store.workspace.search(args.query, args.scope)}
    elif args.command == "compile":
        result = compile_page(store, args.title, args.sources, scope=args.scope, page_id=args.page_id)
    else:
        result = evaluate(store, json.loads(Path(args.benchmark).read_text(encoding="utf-8")))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
