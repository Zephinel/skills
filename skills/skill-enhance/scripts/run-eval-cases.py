#!/usr/bin/env python3
import sys

# Loading the target-local controller must not create scripts/__pycache__ in the
# live skill before the current subject is frozen.
sys.dont_write_bytecode = True

from stage3_hardened import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
