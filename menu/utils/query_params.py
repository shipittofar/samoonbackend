def parse_tag_ids(value):
    """Parse comma-separated tag IDs from a query string value."""
    if value in (None, ""):
        return None
    try:
        parsed = [int(part.strip()) for part in str(value).split(",") if part.strip()]
    except (TypeError, ValueError):
        return []
    return parsed or None
