"""Terminal presentation helpers: colour, status badges, tables, sections.

Colour is on when stdout is a TTY, off when NO_COLOR is set, forced with FORCE_COLOR=1.
Output is plain ASCII so it renders in any terminal and in captured logs.
"""
import os
import re
import sys

if os.name == "nt":  # enable ANSI escape handling on Windows 10+
    os.system("")
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass


def _color_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


USE_COLOR = _color_enabled()
CODES = {"red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35", "cyan": "36",
         "grey": "90", "bold": "1", "dim": "2"}
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
WIDTH = 78

STATUS_STYLE = {
    "PASS": ("green", "bold"), "SUCCESS": ("green", "bold"), "RERUN PASSED": ("green", "bold"),
    "FIXED": ("cyan", "bold"), "READY": ("green", "bold"),
    "FAIL": ("red", "bold"), "FAILED": ("red", "bold"), "ROLLED BACK": ("red", "bold"),
    "PARTIAL": ("yellow", "bold"), "PARTIAL SUCCESS": ("yellow", "bold"),
    "SKIPPED": ("grey",), "DRY RUN": ("yellow", "bold"), "ESCALATE": ("magenta", "bold"),
    "BLOCKED": ("magenta", "bold"), "INFO": ("blue",),
}


def style(text: str, *names: str) -> str:
    if not USE_COLOR or not names:
        return text
    return "\x1b[" + ";".join(CODES[n] for n in names) + "m" + text + "\x1b[0m"


def visible_len(text: str) -> int:
    return len(ANSI_RE.sub("", text))


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - visible_len(text))


def badge(status: str, width: int = 0) -> str:
    label = status if not width else status.ljust(width)
    return style(label, *STATUS_STYLE.get(status, ()))


def banner(title: str, subtitle: str = "") -> str:
    line = "=" * WIDTH
    out = [style(line, "cyan"), style(f"  {title}", "bold")]
    if subtitle:
        out.append(style(f"  {subtitle}", "grey"))
    out.append(style(line, "cyan"))
    return "\n".join(out)


def section(title: str) -> str:
    return "\n" + style(f"-- {title} ", "bold") + style("-" * max(3, WIDTH - len(title) - 4), "grey")


def table(headers, rows) -> str:
    rows = [[str(c) for c in row] for row in rows]
    widths = [visible_len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], visible_len(cell))
    sep = "  "
    head = sep.join(style(pad(h, widths[i]), "bold") for i, h in enumerate(headers))
    rule = sep.join("-" * w for w in widths)
    body = [sep.join(pad(cell, widths[i]) for i, cell in enumerate(row)) for row in rows]
    return "\n".join(["  " + head, "  " + rule] + ["  " + b for b in body])


def bullets(items, indent: int = 2, marker: str = "-") -> str:
    return "\n".join(" " * indent + f"{marker} {item}" for item in items)


def wrap(text: str, indent: int = 2, width: int = WIDTH) -> str:
    import textwrap
    return "\n".join(textwrap.fill(p, width=width, initial_indent=" " * indent, subsequent_indent=" " * indent)
                     for p in text.split("\n"))
