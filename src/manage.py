#!/usr/bin/env python
"""Django's command-line utility for administrative tasks.

Lives next to the packages it drives. Python puts this file's own directory on `sys.path` when it
runs as a script, so `python src/manage.py ...` works from a bare checkout with nothing installed;
after `uv sync` the editable install resolves the same imports from anywhere.

Most invocations go through the Makefile — `make migrate`, `make run`, `make worker`.
"""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
