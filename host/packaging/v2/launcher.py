"""Windowed V2 entrypoint; package verification is explicit and isolated."""
import sys


def main():
    if sys.argv[1:2] == ["--verify-package"]:
        if len(sys.argv) != 3:
            return 2
        from package_smoke import run
        return run(sys.argv[2])
    from motortester.v2.gui import main as gui_main
    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
