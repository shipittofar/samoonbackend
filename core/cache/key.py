class CacheKeys:
    MENU_CATEGORY_LIST = "menu:categories:branch:{branch_id}"
    MENU_CATEGORY_DETAIL = "menu:category:branch:{branch_id}:id:{category_id}"

    MENU_ITEM_LIST = "menu:items:branch:{branch_id}:category:{category_id}"
    MENU_ITEM_LIST_FOR_CONSOLE = "console:menu:items:branch:{branch_id}"
    MENU_ITEM_DETAIL = "menu:item:branch:{branch_id}:category:{category_id}:id:{item_id}"

    EXTRA_LIST = "menu:extras:branch:{branch_id}"
    EXTRA_DETAIL = "menu:extra:branch:{branch_id}:id:{extra_id}"

    EXTRA_GROUP_LIST = "menu:extra_groups:branch:{branch_id}"
    EXTRA_GROUP_DETAIL = "menu:extra_group:branch:{branch_id}:id:{group_id}"

    TAG_LIST = "menu:tags:branch:{branch_id}"
    TAG_DETAIL = "menu:tag:branch:{branch_id}:id:{tag_id}"

    MENU_ITEM_EXTRA_LIST = "menu:item_extras:item:{item_id}"

    MENU_BRANCH_ITEMS_ALL = "menu:branch:{branch_id}:items:all"
    MENU_BRANCH_CATEGORIES_WITH_ITEMS = "menu:branch:{branch_id}:categories_with_items"

    TENANT_DETAIL = "tenant:id:{tenant_id}"
    TENANT_LIST_BY_OWNER = "tenant:owner:{user_id}:list"
    TENANT_LIST_ALL = "tenant:list:all"

    BRANCH_DETAIL = "branch:tenant:{tenant_id}:id:{branch_id}"
    BRANCH_LIST = "branch:tenant:{tenant_id}:list"

    BRANCH_DETAIL_GLOBAL = "branch:detail:global:{branch_id}"
    BRANCH_LIST_ALL = "branch:list:all"

    DISCOVER_LIST = "discover:list:all"
