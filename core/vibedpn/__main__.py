"""`python -m vibedpn`: the CLI. The systemd units of the box (apply, update) and `vibedpn update`
itself run the CLI this way, through the Python of its venv, not through a PATH lookup."""

from vibedpn.cli import app

if __name__ == "__main__":
    app(prog_name="vibedpn")
