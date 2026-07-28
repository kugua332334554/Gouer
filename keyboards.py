from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import config

def get_start_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("频道", callback_data="channel", style="primary", icon_custom_emoji_id="5771695636411847302"),
            InlineKeyboardButton("群组", callback_data="group", style="primary", icon_custom_emoji_id="5942877472163892475")
        ],
        [
            InlineKeyboardButton("快速发帖", callback_data="post_fast", style="success", icon_custom_emoji_id="5985774024968379294"),
            InlineKeyboardButton("高级版", callback_data="pro", style="success", icon_custom_emoji_id="4999002445444023072")
        ],
        [
            InlineKeyboardButton("克隆", callback_data="clone", style="success", icon_custom_emoji_id="5355051922862653659")
        ],
        [
            InlineKeyboardButton("时区", callback_data="timezone", style="primary", icon_custom_emoji_id="5258419835922030550"),
            InlineKeyboardButton("语言", callback_data="language", style="primary", icon_custom_emoji_id="5879585266426973039")
        ],
        [
            InlineKeyboardButton("帮助", url=config.LINK if config.LINK else "https://t.me", style="primary", icon_custom_emoji_id="5877443836174667888")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_timezone_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("UTC+8 北京/上海", callback_data="tz_UTC+8 北京/上海", icon_custom_emoji_id="5879585266426973039"),
            InlineKeyboardButton("UTC+0 伦敦", callback_data="tz_UTC+0 伦敦", icon_custom_emoji_id="5879585266426973039")
        ],
        [
            InlineKeyboardButton("UTC-5 纽约", callback_data="tz_UTC-5 纽约", icon_custom_emoji_id="5879585266426973039"),
            InlineKeyboardButton("UTC+9 东京", callback_data="tz_UTC+9 东京", icon_custom_emoji_id="5879585266426973039")
        ],
        [
            InlineKeyboardButton("« 返回主菜单", callback_data="back_to_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_add_channel_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    clean_username = bot_username.lstrip("@")
    url = f"https://t.me/{clean_username}?startchannel&admin=post_messages+edit_messages+delete_messages+change_info+invite_users+manage_chat+manage_topics"
    keyboard = [
        [InlineKeyboardButton("添加频道", url=url, style="primary", icon_custom_emoji_id="5775937998948404844")],
        [InlineKeyboardButton("« 返回主菜单", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_add_group_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    clean_username = bot_username.lstrip("@")
    url = f"https://t.me/{clean_username}?startgroup&admin=change_info+delete_messages+restrict_members+invite_users+pin_messages+manage_topics+promote_members+manage_video_chats+manage_chat"
    keyboard = [
        [InlineKeyboardButton("添加群组", url=url, style="primary", icon_custom_emoji_id="5775937998948404844")],
        [InlineKeyboardButton("« 返回主菜单", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_private_chat_keyboard(bot_username: str, target_type: str = "group_panel") -> InlineKeyboardMarkup:
    clean_username = bot_username.lstrip("@")
    url = f"https://t.me/{clean_username}?start={target_type}"
    keyboard = [
        [InlineKeyboardButton("进入私聊管理", url=url, style="primary", icon_custom_emoji_id="5985774024968379294")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_pagination_keyboard(items: list, page: int, item_type: str, bot_username: str, per_page: int = 5) -> InlineKeyboardMarkup:
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
        nav_buttons.append(InlineKeyboardButton("上一页", callback_data=f"page_{item_type}_{page - 1}", icon_custom_emoji_id="5875082500023258804"))
    nav_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("下一页", callback_data=f"page_{item_type}_{page + 1}", icon_custom_emoji_id="5875506366050734240"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
        
    clean_username = bot_username.lstrip("@")
    if item_type == "group":
        add_url = f"https://t.me/{clean_username}?startgroup&admin=change_info+delete_messages+restrict_members+invite_users+pin_messages+manage_topics+promote_members+manage_video_chats+manage_chat"
        add_text = "添加群组"
    else:
        add_url = f"https://t.me/{clean_username}?startchannel&admin=post_messages+edit_messages+delete_messages+change_info+invite_users+manage_chat+manage_topics"
        add_text = "添加频道"
        
    keyboard.append([InlineKeyboardButton(add_text, url=add_url, style="primary", icon_custom_emoji_id="5775937998948404844")])
    keyboard.append([InlineKeyboardButton("« 返回主菜单", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)

def get_group_manage_keyboard(chat_id: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("进群验证", callback_data=f"group_verify_{chat_id}", icon_custom_emoji_id="5931409969613116639")],
        [InlineKeyboardButton("« 返回群组列表", callback_data="group")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_group_verification_keyboard(chat_id: str, current_state: dict) -> InlineKeyboardMarkup:
    CHECK_EMOJI_ID = "5776375003280838798"
    CROSS_EMOJI_ID = "5778527486270770928"

    def opt_kwargs(is_selected: bool):
        """选中时返回高亮 style 和选中的表情 id，未选中则不带 icon_custom_emoji_id"""
        if is_selected:
            return {"style": "primary", "icon_custom_emoji_id": CHECK_EMOJI_ID}
        return {"style": "default"}

    keyboard = [
        # 状态行
        [
            InlineKeyboardButton("状态:", callback_data="noop"),
            InlineKeyboardButton(
                "开启", 
                callback_data=f"verify_set_status_1_{chat_id}", 
                style="primary" if current_state['status'] else "default",
                icon_custom_emoji_id=CHECK_EMOJI_ID if current_state['status'] else None
            ),
            InlineKeyboardButton(
                "关闭", 
                callback_data=f"verify_set_status_0_{chat_id}", 
                style="primary" if not current_state['status'] else "default",
                icon_custom_emoji_id=CROSS_EMOJI_ID if not current_state['status'] else None
            )
        ],
        # 模式行
        [InlineKeyboardButton("模式:", callback_data="noop")],
        [
            InlineKeyboardButton("按钮模式", callback_data=f"verify_set_mode_button_{chat_id}", **opt_kwargs(current_state['mode'] == 'button')),
            InlineKeyboardButton("数学题", callback_data=f"verify_set_mode_math_{chat_id}", **opt_kwargs(current_state['mode'] == 'math')),
            InlineKeyboardButton("验证码", callback_data=f"verify_set_mode_captcha_{chat_id}", **opt_kwargs(current_state['mode'] == 'captcha'))
        ],
        # 验证时长行
        [InlineKeyboardButton("验证时长:", callback_data="noop")],
        [
            InlineKeyboardButton("1分钟", callback_data=f"verify_set_dur_1_{chat_id}", **opt_kwargs(current_state['duration'] == 1)),
            InlineKeyboardButton("5分钟", callback_data=f"verify_set_dur_5_{chat_id}", **opt_kwargs(current_state['duration'] == 5)),
            InlineKeyboardButton("10分钟", callback_data=f"verify_set_dur_10_{chat_id}", **opt_kwargs(current_state['duration'] == 10))
        ],
        # 超时惩罚行
        [InlineKeyboardButton("超时惩罚:", callback_data="noop")],
        [
            InlineKeyboardButton("禁言", callback_data=f"verify_set_pen_mute_{chat_id}", **opt_kwargs(current_state['penalty'] == 'mute')),
            InlineKeyboardButton("踢出", callback_data=f"verify_set_pen_kick_{chat_id}", **opt_kwargs(current_state['penalty'] == 'kick'))
        ],
        # 返回按钮
        [InlineKeyboardButton("« 返回群组管理", callback_data=f"manage_group_{chat_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)
