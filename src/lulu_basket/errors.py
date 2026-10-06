class ToolError(Exception):
    """Base for every expected failure; the CLI maps it to exit 1."""


class ScrapeError(ToolError):
    pass


class SnapshotError(ToolError):
    pass


class SolveError(ToolError):
    pass
