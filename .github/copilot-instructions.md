# InkSim Development Instructions

- This project uses `uv` and the project virtual environment at `.venv`.
- Use `uvr <command>` for Python commands so dependencies are resolved from `.venv`.
- Use `uv sync` to create or update the environment from `pyproject.toml`.
- Do not search for or invoke system `python` or `python3` when working on this project.
- The project supports Python 3.12 or newer, as specified by `pyproject.toml`. The local setup script currently defaults to Python 3.14.
- Run the application with `uvr inksim` or `uvr python -m inksim`.
- Before changing code, inspect the relevant source and existing project conventions.
- Keep code and comments in English.


