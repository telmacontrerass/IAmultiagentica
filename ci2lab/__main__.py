"""Package entry point so ``python -m ci2lab`` runs the CLI.

Delegates to :func:`ci2lab.cli.main` and propagates its exit code via
:class:`SystemExit`.
"""

from ci2lab.cli import main

raise SystemExit(main())
