"""Frontend-aligned defaults for Website Builder (see frontend/src/types/website-builder.ts)."""

DEFAULT_SECTIONS = [
    {"key": "hero", "enabled": True, "order": 0},
    {"key": "featured_menu", "enabled": True, "order": 1},
    {"key": "about", "enabled": True, "order": 2},
    {"key": "promotions", "enabled": True, "order": 3},
    {"key": "reviews", "enabled": True, "order": 4},
    {"key": "branches", "enabled": True, "order": 5},
    {"key": "gallery", "enabled": True, "order": 6},
    {"key": "events", "enabled": False, "order": 7},
    {"key": "faq", "enabled": False, "order": 8},
    {"key": "contact", "enabled": True, "order": 9},
]

DEFAULT_HERO = {
    "alignment": "center",
    "theme": "dark",
    "overlayOpacity": 0.45,
    "mobileVariant": "compact",
}

DEFAULT_THEME = {
    "borderRadius": "xl",
    "cardStyle": "elevated",
    "darkModePreference": "system",
}

DEFAULT_LAYOUT = {
    "sections": DEFAULT_SECTIONS,
    "hero": DEFAULT_HERO,
    "about": {},
    "contact": {},
    "faq": [],
    "theme": DEFAULT_THEME,
    "status": "draft",
}
