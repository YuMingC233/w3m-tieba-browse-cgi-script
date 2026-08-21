"""Shared constants for the legacy Tieba mobile adapter."""

TIEBA_HOSTS = {"tieba.baidu.com", "www.tieba.baidu.com"}

# These are legacy page endpoints, not a versioned or stability-guaranteed API.
MOBILE_THREAD_URL = "https://tieba.baidu.com/mo/q---1-3-0--2/m"
LZL_URL = "https://tieba.baidu.com/mo/q---1-3-0--2/flr"
CGI_URL = "file:/cgi-bin/tieba_filter.py?"

SAFE_UPSTREAM_PARAMS = ("pn", "see_lz", "r")

DROP_CLASSES = {
    # App promotions, popups, and dead JavaScript-only controls.
    "wake_app_tip",
    "pb_new_popup",
    "more_newspinner",
    "pb_newshare",
    "set_good_popup",
    "appPromote",
    "appBottomPromote",
    "jump_page_pop_back",
    "jump_page_pop_con",
    "jump_page_pop_common",
    "frs_sign_in_prompt",
    "frs_sign_in_prompt_img",
    "fixed_bar",
    "hongbao_page_pop_common",
    "bottom_reply",
    "client_ghost_icon",
    "footer_new",
    "pb_footer",
    # Per-post controls that w3m cannot use.
    "blue_kit_right",
    "list_item_more_operation",
    "lzl_cut_more_btn",
    "lzl_p_p",
    "lzl_s_r",
    "lzl_jb",
    "lzl_op_list",
    "lzl_li_pager",
    "father-cut-daoliu-normal-box",
    "father-cut-daoliu-from-toutiao-box",
    "father_cut_daoliu",
}

DROP_IDS = {
    "pb_reply_postor_wrap",
    "lzl_reply_postor_wrap",
}

VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
