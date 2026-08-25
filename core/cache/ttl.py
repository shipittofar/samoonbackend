class CacheTTL:
    """
    Centralized TTL values (in seconds) for every cached entity across the
    project. Grouped by app/domain so it's easy to find and tune later.
    """

    # ---- menu app ----
    MENU_CATEGORY = 60 * 60          # 1 hour
    MENU_ITEM = 60 * 60              # 1 hour
    EXTRA = 60 * 60                  # 1 hour
    EXTRA_GROUP = 60 * 60            # 1 hour
    TAG = 60 * 60                    # 1 hour
    MENU_ITEM_EXTRA = 60 * 60        # 1 hour

    MENU_BRANCH_ITEMS_ALL = 60 * 30                 # 30 minutes
    MENU_BRANCH_CATEGORIES_WITH_ITEMS = 60 * 30      # 30 minutes

    # ---- tenants app ----
    # Safety-net only — explicit invalidate_* is the primary correctness mechanism.
    TENANT = 60 * 10                 # 10 minutes
    BRANCH = 60 * 10                 # 10 minutes
