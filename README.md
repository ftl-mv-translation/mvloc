# mvloc, the core script for FTL: Multiverse Translation Project

## Running the script

The script is written in Python and managed by poetry. A standard setuptools may install it as a package,
or you may use poetry to manage the virtualenv and installation process.

The `mvloc` command can be invoked with either one of the following setups:

1. Use regular pip (or [pipx](https://github.com/pypa/pipx)) to install the package. (virtualenv is recommended)
2. Use poetry to install the package (`poetry install`), then run `poetry shell` to activate virtualenv. (*)

(*) Note that directly invoking `poetry run mvloc` might NOT work for `batch-` commands because of [this poetry bug](https://github.com/python-poetry/poetry/issues/965). Running `mvloc` inside the spawned shell won't have this issue.

All `mvloc` subcommands starting with `batch-` generates `report.txt` file that contains logs and outputs of all task
in a workflow.

## Disclaimer

FTL: Faster Than Light is a trademark of Subset Games. Unless otherwise stated, the authors and the contributors of this
repository is not affiliated with nor endorsed by Subset Games.
