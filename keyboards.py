from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import config
from lang import t_sync, DEFAULT_LANG


def _(key: str, lang: str = DEFAULT_LANG) -> str:
    """Shortcut for t_sync — translate a key for a given language."""
    return t_sync(lang, key)


def get_start_keyboard(lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    import os as _os
    is_child = _os.getenv("BOT_IS_CHILD") == "1"
    keyboard = [
        [
            InlineKeyboardButton(_("channel_btn", lang), callback_data="channel", style="primary", icon_custom_emoji_id="5771695636411847302"),
            InlineKeyboardButton(_("group_btn", lang), callback_data="group", style="primary", icon_custom_emoji_id="5942877472163892475")
        ],
        [
            InlineKeyboardButton(_("post_fast_btn", lang), callback_data="post_fast", style="success", icon_custom_emoji_id="5985774024968379294"),
        ] + ([
            InlineKeyboardButton(_("pro_btn", lang), callback_data="pro", style="success", icon_custom_emoji_id="4999002445444023072")
        ] if not is_child else []),
    ]
    if not is_child:
        keyboard.append([
            InlineKeyboardButton(_("clone_btn", lang), callback_data="clone", style="success", icon_custom_emoji_id="5355051922862653659")
        ])
    keyboard.append([
        InlineKeyboardButton(_("timezone_btn", lang), callback_data="timezone", style="primary", icon_custom_emoji_id="5258419835922030550"),
        InlineKeyboardButton(_("language_btn", lang), callback_data="changelang", style="primary", icon_custom_emoji_id="5879585266426973039")
    ])
    if not is_child:
        keyboard.append([
            InlineKeyboardButton(_("help_channel_btn", lang), url=config.LINK if config.LINK else "https://t.me", style="primary", icon_custom_emoji_id="5771695636411847302")
        ])
    return InlineKeyboardMarkup(keyboard)

def get_timezone_keyboard(lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("UTC+8 北京/Shanghai", callback_data="tz_UTC+8 北京/上海", icon_custom_emoji_id="5879585266426973039"),
            InlineKeyboardButton("UTC+0 伦敦/London", callback_data="tz_UTC+0 伦敦", icon_custom_emoji_id="5879585266426973039")
        ],
        [
            InlineKeyboardButton("UTC-5 纽约/New York", callback_data="tz_UTC-5 纽约", icon_custom_emoji_id="5879585266426973039"),
            InlineKeyboardButton("UTC+9 东京/Tokyo", callback_data="tz_UTC+9 东京", icon_custom_emoji_id="5879585266426973039")
        ],
        [
            InlineKeyboardButton("« " + _("back_main", lang), callback_data="back_to_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_add_channel_keyboard(bot_username: str, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    clean_username = bot_username.lstrip("@")
    url = f"https://t.me/{clean_username}?startchannel&admin=post_messages+edit_messages+delete_messages+change_info+invite_users+manage_chat+manage_topics"
    keyboard = [
        [InlineKeyboardButton(_("add_channel_btn", lang), url=url, style="primary", icon_custom_emoji_id="5775937998948404844")],
        [InlineKeyboardButton("« " + _("back_main", lang), callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_add_group_keyboard(bot_username: str, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    clean_username = bot_username.lstrip("@")
    url = f"https://t.me/{clean_username}?startgroup&admin=change_info+delete_messages+restrict_members+invite_users+pin_messages+manage_topics+promote_members+manage_video_chats+manage_chat"
    keyboard = [
        [InlineKeyboardButton(_("add_group_btn", lang), url=url, style="primary", icon_custom_emoji_id="5775937998948404844")],
        [InlineKeyboardButton("« " + _("back_main", lang), callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_private_chat_keyboard(bot_username: str, target_type: str = "group_panel", lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    clean_username = bot_username.lstrip("@")
    url = f"https://t.me/{clean_username}?start={target_type}"
    keyboard = [
        [InlineKeyboardButton(_("private_manage_btn", lang), url=url, style="primary", icon_custom_emoji_id="5985774024968379294")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_pagination_keyboard(items: list, page: int, item_type: str, bot_username: str, per_page: int = 5, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    total_items = len(items)
    total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_items = items[start_idx:end_idx]
    emoji_id = "5796440171364749940" if item_type == "group" else "5771695636411847302"
    
    keyboard = []
    for chat_id, title in page_items:
        keyboard.append([InlineKeyboardButton(title, callback_data=f"manage_{item_type}_{chat_id}", icon_custom_emoji_id=emoji_id)])
    
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton(_("prev_page", lang), callback_data=f"page_{item_type}_{page - 1}", icon_custom_emoji_id="5875082500023258804"))
    nav_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton(_("next_page", lang), callback_data=f"page_{item_type}_{page + 1}", icon_custom_emoji_id="5875506366050734240"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
        
    clean_username = bot_username.lstrip("@")
    if item_type == "group":
        add_url = f"https://t.me/{clean_username}?startgroup&admin=change_info+delete_messages+restrict_members+invite_users+pin_messages+manage_topics+promote_members+manage_video_chats+manage_chat"
        add_text = _("add_group_btn", lang)
    else:
        add_url = f"https://t.me/{clean_username}?startchannel&admin=post_messages+edit_messages+delete_messages+change_info+invite_users+manage_chat+manage_topics"
        add_text = _("add_channel_btn", lang)

    keyboard.append([InlineKeyboardButton(add_text, url=add_url, style="primary", icon_custom_emoji_id="5775937998948404844")])
    keyboard.append([InlineKeyboardButton("« " + _("back_main", lang), callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)

def get_channel_manage_keyboard(chat_id: str, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_("dingshi_btn", lang), callback_data=f"group_dingshi_{chat_id}", icon_custom_emoji_id="5258419835922030550")],
        [InlineKeyboardButton(_("autobutton_btn", lang), callback_data=f"ab_panel_{chat_id}", icon_custom_emoji_id="5879841310902324730")],
        [InlineKeyboardButton(_("permission_btn", lang), callback_data=f"perm_panel_{chat_id}", icon_custom_emoji_id="5931409969613116639")],
        [InlineKeyboardButton(_("autodelete_btn", lang), callback_data=f"ad_panel_{chat_id}", icon_custom_emoji_id="5927054181285237634")],
        [InlineKeyboardButton("« " + _("back_channel_list", lang), callback_data="channel")]
    ])


def get_group_manage_keyboard(chat_id: str, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(_("verify_btn", lang), callback_data=f"group_verify_{chat_id}", icon_custom_emoji_id="5931409969613116639"),
         InlineKeyboardButton(_("welcome_btn", lang), callback_data=f"group_welcome_{chat_id}", icon_custom_emoji_id="4963072209334567688")],
        [InlineKeyboardButton(_("points_btn", lang), callback_data=f"group_jifen_{chat_id}", icon_custom_emoji_id="5197688912457245639"),
         InlineKeyboardButton(_("dingshi_btn", lang), callback_data=f"group_dingshi_{chat_id}", icon_custom_emoji_id="5258419835922030550")],
        [InlineKeyboardButton(_("censor_btn", lang), callback_data=f"group_weijinci_{chat_id}", icon_custom_emoji_id="5931409969613116639"),
         InlineKeyboardButton(_("night_btn", lang), callback_data=f"group_night_{chat_id}", icon_custom_emoji_id="5814500882506589776")],
        [InlineKeyboardButton(_("lottery_btn", lang), callback_data=f"group_choujiang_{chat_id}", icon_custom_emoji_id="5864128984798730231"),
         InlineKeyboardButton(_("autodelete_btn", lang), callback_data=f"ad_panel_{chat_id}", icon_custom_emoji_id="5927054181285237634")],
        [InlineKeyboardButton("反垃圾", callback_data=f"as_panel_{chat_id}", icon_custom_emoji_id="5447644880824181073"),
         InlineKeyboardButton("发言检查", callback_data=f"spk_panel_{chat_id}", icon_custom_emoji_id="5994378914636500516")],
        [InlineKeyboardButton("开关群", callback_data=f"tg_panel_{chat_id}", icon_custom_emoji_id="5363972600001216334"),
         InlineKeyboardButton(_("permission_btn", lang), callback_data=f"perm_panel_{chat_id}", icon_custom_emoji_id="5931409969613116639")],
        [InlineKeyboardButton(_("card_btn", lang), callback_data=f"card_panel_{chat_id}", icon_custom_emoji_id="5931409969613116639"),
         InlineKeyboardButton(_("ai_btn", lang), callback_data=f"ai_panel_{chat_id}", icon_custom_emoji_id="5931409969613116639")],
        [InlineKeyboardButton("« " + _("back_group_list", lang), callback_data="group")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_group_verification_keyboard(chat_id: str, current_state: dict, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    CHECK_EMOJI_ID = "5776375003280838798"
    CROSS_EMOJI_ID = "5778527486270770928"

    def opt_kwargs(is_selected: bool):
        if is_selected:
            return {"style": "primary", "icon_custom_emoji_id": CHECK_EMOJI_ID}
        return {"style": "default"}

    keyboard = [
        [
            InlineKeyboardButton(_("status_label", lang), callback_data="noop"),
            InlineKeyboardButton(
                _("enable_btn", lang),
                callback_data=f"verify_set_status_1_{chat_id}",
                style="primary" if current_state['status'] else "default",
                icon_custom_emoji_id=CHECK_EMOJI_ID if current_state['status'] else None
            ),
            InlineKeyboardButton(
                _("disable_btn", lang),
                callback_data=f"verify_set_status_0_{chat_id}",
                style="primary" if not current_state['status'] else "default",
                icon_custom_emoji_id=CROSS_EMOJI_ID if not current_state['status'] else None
            )
        ],
        [InlineKeyboardButton(_("mode_label", lang), callback_data="noop")],
        [
            InlineKeyboardButton(_("button_mode", lang), callback_data=f"verify_set_mode_button_{chat_id}", **opt_kwargs(current_state['mode'] == 'button')),
            InlineKeyboardButton(_("math_mode", lang), callback_data=f"verify_set_mode_math_{chat_id}", **opt_kwargs(current_state['mode'] == 'math')),
            InlineKeyboardButton(_("captcha_mode", lang), callback_data=f"verify_set_mode_captcha_{chat_id}", **opt_kwargs(current_state['mode'] == 'captcha'))
        ],
        [InlineKeyboardButton(_("verify_dur_label", lang), callback_data="noop")],
        [
            InlineKeyboardButton(_("1_minute", lang), callback_data=f"verify_set_dur_1_{chat_id}", **opt_kwargs(current_state['duration'] == 1)),
            InlineKeyboardButton(_("5_minutes", lang), callback_data=f"verify_set_dur_5_{chat_id}", **opt_kwargs(current_state['duration'] == 5)),
            InlineKeyboardButton(_("10_minutes", lang), callback_data=f"verify_set_dur_10_{chat_id}", **opt_kwargs(current_state['duration'] == 10))
        ],
        [InlineKeyboardButton(_("timeout_pen_label", lang), callback_data="noop")],
        [
            InlineKeyboardButton(_("mute_penalty", lang), callback_data=f"verify_set_pen_mute_{chat_id}", **opt_kwargs(current_state['penalty'] == 'mute')),
            InlineKeyboardButton(_("kick_penalty", lang), callback_data=f"verify_set_pen_kick_{chat_id}", **opt_kwargs(current_state['penalty'] == 'kick'))
        ],
        [InlineKeyboardButton("« " + _("back_group_manage", lang), callback_data=f"manage_group_{chat_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_group_jifen_keyboard(chat_id: str, state: dict, lang: str = DEFAULT_LANG) -> InlineKeyboardMarkup:
    CHECK_EMOJI_ID = "5776375003280838798"
    CROSS_EMOJI_ID = "5778527486270770928"

    def opt_kwargs(is_selected: bool):
        if is_selected:
            return {"style": "primary", "icon_custom_emoji_id": CHECK_EMOJI_ID}
        return {"style": "default"}

    keyboard = [
        [
            InlineKeyboardButton(_("func_status_label", lang), callback_data="noop"),
            InlineKeyboardButton(_("enable_btn", lang), callback_data=f"jifen_set_status_1_{chat_id}", style="primary" if state['status'] else "default", icon_custom_emoji_id=CHECK_EMOJI_ID if state['status'] else None),
            InlineKeyboardButton(_("disable_btn", lang), callback_data=f"jifen_set_status_0_{chat_id}", style="primary" if not state['status'] else "default", icon_custom_emoji_id=CROSS_EMOJI_ID if not state['status'] else None)
        ],
        [InlineKeyboardButton(_("points_per_msg_label", lang), callback_data="noop")],
        [
            InlineKeyboardButton(_("0_points", lang), callback_data=f"jifen_set_msgpts_0_{chat_id}", **opt_kwargs(state['msg_points'] == 0)),
            InlineKeyboardButton(_("1_point", lang), callback_data=f"jifen_set_msgpts_1_{chat_id}", **opt_kwargs(state['msg_points'] == 1)),
            InlineKeyboardButton(_("2_points", lang), callback_data=f"jifen_set_msgpts_2_{chat_id}", **opt_kwargs(state['msg_points'] == 2)),
            InlineKeyboardButton(_("5_points", lang), callback_data=f"jifen_set_msgpts_5_{chat_id}", **opt_kwargs(state['msg_points'] == 5))
        ],
        [
            InlineKeyboardButton(_("filter_stickers_label", lang), callback_data="noop"),
            InlineKeyboardButton(_("yes", lang), callback_data=f"jifen_set_sticker_1_{chat_id}", style="primary" if state['ignore_stickers'] else "default", icon_custom_emoji_id=CHECK_EMOJI_ID if state['ignore_stickers'] else None),
            InlineKeyboardButton(_("no", lang), callback_data=f"jifen_set_sticker_0_{chat_id}", style="primary" if not state['ignore_stickers'] else "default", icon_custom_emoji_id=CROSS_EMOJI_ID if not state['ignore_stickers'] else None)
        ],
        [InlineKeyboardButton(_("checkin_del_label", lang), callback_data="noop")],
        [
            InlineKeyboardButton(_("no_delete", lang), callback_data=f"jifen_set_del_0_{chat_id}", **opt_kwargs(state.get('delete_time', 0) == 0)),
            InlineKeyboardButton(_("10_seconds", lang), callback_data=f"jifen_set_del_10_{chat_id}", **opt_kwargs(state.get('delete_time', 0) == 10)),
            InlineKeyboardButton(_("30_seconds", lang), callback_data=f"jifen_set_del_30_{chat_id}", **opt_kwargs(state.get('delete_time', 0) == 30)),
            InlineKeyboardButton(_("1_minute", lang), callback_data=f"jifen_set_del_60_{chat_id}", **opt_kwargs(state.get('delete_time', 0) == 60))
        ],
        [InlineKeyboardButton("« " + _("back_group_manage", lang), callback_data=f"manage_group_{chat_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_pro_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("AI 订阅", callback_data="group", icon_custom_emoji_id="5332814802702056788")],
        [InlineKeyboardButton("名片订阅", callback_data="group", icon_custom_emoji_id="5363972600001216334")],
        [InlineKeyboardButton("« 返回主菜单", callback_data="back_to_main")]
    ])
