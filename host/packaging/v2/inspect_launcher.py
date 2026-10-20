"""Console entrypoint: JSON/CSV inspection needs no Qt window."""
import sys
from motortester.v2.inspect import main

if __name__ == "__main__":
    # PowerShell redirection receives deterministic UTF-8 JSON.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
