#!/usr/bin/env python
"""Utilidad de Django. Por defecto usa la configuración de desarrollo (config.settings.dev)."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    if len(sys.argv) > 1 and sys.argv[1] == "test" and os.environ["DJANGO_SETTINGS_MODULE"].endswith(".dev"):
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
