"""The one Jinja environment every rendered file of the box comes from.

Templates render config files, not HTML: no autoescaping, undefined variables are errors, and
block tags leave no stray blank lines behind.
"""

from jinja2 import Environment, PackageLoader, StrictUndefined


def template_environment() -> Environment:
    return Environment(
        loader=PackageLoader("vibedpn", "templates"),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
