# RichText (富文本消息) 兼容层
#
# Telegram Bot API 10.1 引入 RichMessage 富文本消息, 内容在 message.rich_message,
# 不再走 message.text。PTB 22.x 尚未暴露 rich_message 字段(官方 issue #5261 未合入),
# 导致反垃圾/违禁词/关键词回复/发言检查等所有基于 message.text 的检查
# 收不到富文本消息的内容。
#
# 这里在 Message.de_json 处拦截: 若消息带 rich_message 且没有 text,
# 先把富文本里的纯文本提取出来塞进 data["text"], 再交给 PTB 正常解析,
# 这样 update.message.text 就被填充了, 现有文本检查零改动生效。
import logging

from telegram import Message

logger = logging.getLogger(__name__)

# 跳过不含可见文本的字段, 避免重复/误收
_SKIP_KEYS = {
    "entities", "link_preview_options", "file_id", "photo", "document",
    "animation", "audio", "video", "voice", "sticker", "thumbnail",
}


def _rich_plain_text(node) -> str:
    """从 rich_message 的 JSON 里提取纯文本(容错式递归)。"""
    if isinstance(node, list):
        return "".join(_rich_plain_text(x) for x in node)
    if not isinstance(node, dict):
        return ""
    # RichText 变体都直接带 text 字段(可见文本)
    if isinstance(node.get("text"), str):
        return node["text"]
    out = []
    for key, value in node.items():
        if key in _SKIP_KEYS:
            continue
        if isinstance(value, (list, dict)):
            out.append(_rich_plain_text(value))
    return "".join(out)


def _find_location(node):
    """递归在 rich_message JSON 里找坐标(latitude/longitude 数值), 返回 (lat, lng) 或 None。

    富文本位置卡片(RichBlockMap)里带 location: {latitude, longitude}。
    """
    if isinstance(node, dict):
        lat, lng = node.get("latitude"), node.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return (lat, lng)
        for v in node.values():
            found = _find_location(v)
            if found:
                return found
    elif isinstance(node, list):
        for x in node:
            found = _find_location(x)
            if found:
                return found
    return None


_orig_de_json = Message.de_json
_logged_rich = False


@classmethod
def _patched_de_json(cls, data, bot):
    global _logged_rich
    if isinstance(data, dict) and data.get("rich_message"):
        data = dict(data)
        rich = data["rich_message"]
        # 注入纯文本: 让反垃圾/违禁词/关键词回复等基于 message.text 的检查生效
        if not data.get("text"):
            data["text"] = _rich_plain_text(rich)
        # 注入位置: RichBlockMap 的坐标 -> message.location, 让反垃圾 block_location 拦截生效
        loc = _find_location(rich)
        if loc and not data.get("location"):
            data["location"] = {"latitude": loc[0], "longitude": loc[1]}
        if not _logged_rich:
            _logged_rich = True
            logger.info(f"RichText message -> text={data.get('text', '')[:60]!r} loc={loc}")
    return _orig_de_json(data, bot)


Message.de_json = _patched_de_json
logger.info("RichText compat layer installed (message.text injection)")
