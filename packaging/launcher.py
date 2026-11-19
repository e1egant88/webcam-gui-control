"""Entry script for the packaged executables (GestureControl.exe / gesture-control-cli.exe)."""

import sys

from gesture_control.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
