_strict_fields = False


def set_strict_fields(enabled: bool) -> None:
    """Make ``emit`` reject fields no declared stream will carry, and
    ``set_context`` reject fields no catalogue declares.

    Off by default: a typo should not take a request down in production.
    """
    global _strict_fields
    _strict_fields = enabled


def strict_fields() -> bool:
    return _strict_fields
