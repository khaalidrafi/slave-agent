"""Shared platform registry for slave-agent."""

from collections import OrderedDict
from typing import NamedTuple


class PlatformInfo(NamedTuple):
    """Metadata for a single platform entry."""
    label: str
    default_toolset: str


# Ordered so that TUI menus are deterministic.
PLATFORMS: OrderedDict[str, PlatformInfo] = OrderedDict([
    ("cli",            PlatformInfo(label="🖥️  CLI",            default_toolset="slave-cli")),
    ("telegram",       PlatformInfo(label="📱 Telegram",        default_toolset="slave-telegram")),
    ("discord",        PlatformInfo(label="💬 Discord",         default_toolset="slave-discord")),
    ("slack",          PlatformInfo(label="💼 Slack",           default_toolset="slave-slack")),
    ("whatsapp",       PlatformInfo(label="📱 WhatsApp",        default_toolset="slave-whatsapp")),
    ("whatsapp_cloud", PlatformInfo(label="📱 WhatsApp Business (Cloud)", default_toolset="slave-whatsapp")),
    ("signal",         PlatformInfo(label="📡 Signal",          default_toolset="slave-signal")),
    ("bluebubbles",    PlatformInfo(label="💙 BlueBubbles",     default_toolset="slave-bluebubbles")),
    ("email",          PlatformInfo(label="📧 Email",           default_toolset="slave-email")),
    ("homeassistant",  PlatformInfo(label="🏠 Home Assistant",  default_toolset="slave-homeassistant")),
    ("mattermost",     PlatformInfo(label="💬 Mattermost",      default_toolset="slave-mattermost")),
    ("matrix",         PlatformInfo(label="💬 Matrix",          default_toolset="slave-matrix")),
    ("dingtalk",       PlatformInfo(label="💬 DingTalk",        default_toolset="slave-dingtalk")),
    ("feishu",         PlatformInfo(label="🪽 Feishu",          default_toolset="slave-feishu")),
    ("wecom",          PlatformInfo(label="💬 WeCom",           default_toolset="slave-wecom")),
    ("wecom_callback", PlatformInfo(label="💬 WeCom Callback",  default_toolset="slave-wecom-callback")),
    ("weixin",         PlatformInfo(label="💬 Weixin",          default_toolset="slave-weixin")),
    ("qqbot",          PlatformInfo(label="💬 QQBot",           default_toolset="slave-qqbot")),
    ("yuanbao",        PlatformInfo(label="🤖 Yuanbao",         default_toolset="slave-yuanbao")),
    ("webhook",        PlatformInfo(label="🔗 Webhook",         default_toolset="slave-webhook")),
    ("api_server",     PlatformInfo(label="🌐 API Server",      default_toolset="slave-api-server")),
    ("cron",           PlatformInfo(label="⏰ Cron",            default_toolset="slave-cron")),
])


def _plugin_label(entry) -> str:
    return f"{entry.emoji}  {entry.label}" if entry.emoji else entry.label


def platform_label(key: str, default: str = "") -> str:
    """Return the display label for a platform key (builtin, then plugin registry), or *default*."""
    info = PLATFORMS.get(key)
    if info is not None:
        return info.label
    try:
        from gateway.platform_registry import platform_registry
        entry = platform_registry.get(key)
        if entry:
            return _plugin_label(entry)
    except Exception:
        pass
    return default


def get_all_platforms() -> "OrderedDict[str, PlatformInfo]":
    """PLATFORMS plus plugin-registered platforms (appended after builtins) — use for menus."""
    merged = OrderedDict(PLATFORMS)
    try:
        from gateway.platform_registry import platform_registry
        for entry in platform_registry.plugin_entries():
            if entry.name not in merged:
                merged[entry.name] = PlatformInfo(_plugin_label(entry), f"slave-{entry.name}")
    except Exception:
        pass
    return merged
