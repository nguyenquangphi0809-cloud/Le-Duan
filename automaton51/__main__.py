import sys

if sys.version_info < (3, 10):
    sys.exit("automaton51 cần Python 3.10 trở lên (máy đang có %d.%d). Cài bản mới tại https://www.python.org/downloads/"
             % sys.version_info[:2])

from .cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
