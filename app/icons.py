"""Small stroke icons drawn for Mrigel (24x24, currentColor)."""

from markupsafe import Markup

_PATHS = {
    "home": '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v9.5h13V10"/><path d="M10 19.5v-5h4v5"/>',
    "list": '<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
    "queue": '<rect x="4" y="3.5" width="16" height="6" rx="2"/><path d="M6 13.5h12M8 17.5h8M10 21h4"/>',
    "upload": '<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5"/><path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15"/>',
    "download": '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5"/><path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15"/>',
    "ban": '<circle cx="12" cy="12" r="8.5"/><path d="m6 6 12 12"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M21.5 12h-3M5.5 12h-3M18.7 5.3l-2.1 2.1M7.4 16.6l-2.1 2.1M18.7 18.7l-2.1-2.1M7.4 7.4 5.3 5.3"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5"/><path d="M16 4.8a3.5 3.5 0 0 1 0 6.4M18 14.8c2 .7 3.2 2.4 3.5 5.2"/>',
    "logout": '<path d="M14 4h4.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H14"/><path d="M10 16.5 5.5 12 10 7.5M5.5 12H15"/>',
    "chat": '<path d="M4 18.5V6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H8z"/><path d="M8.5 9h7M8.5 12.5h4"/>',
    "send": '<path d="M20.5 3.5 10 14"/><path d="m20.5 3.5-6.5 17-4-6.5-6.5-4z"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "phone": '<path d="M5 4h3.5l1.5 4.5-2.2 1.4a11 11 0 0 0 6.3 6.3l1.4-2.2L20 15.5V19a1.5 1.5 0 0 1-1.6 1.5C10.6 20 4 13.4 3.5 5.6A1.5 1.5 0 0 1 5 4z"/>',
    "phone-off": '<path d="M5 4h3.5l1.5 4.5-2.2 1.4a11 11 0 0 0 6.3 6.3l1.4-2.2L20 15.5V19a1.5 1.5 0 0 1-1.6 1.5C10.6 20 4 13.4 3.5 5.6A1.5 1.5 0 0 1 5 4z"/><path d="m3 3 18 18"/>',
    "truck": '<path d="M2.5 6.5h11v10h-11z"/><path d="M13.5 10h4l3 3.5v3h-7"/><circle cx="6.5" cy="17.5" r="1.8"/><circle cx="17" cy="17.5" r="1.8"/>',
    "package": '<path d="M12 3 20 7.5v9L12 21l-8-4.5v-9z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/>',
    "parcel-check": '<path d="M12 3 20 7.5v9L12 21l-8-4.5v-9z"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
    "box-return": '<path d="M12 3 20 7.5v9L12 21l-8-4.5v-9z"/><path d="M14.5 13.5h-5M11.5 11 9 13.5l2.5 2.5"/>',
    "sparkles": '<path d="M12 3.5 13.6 9 19 10.5 13.6 12 12 17.5 10.4 12 5 10.5 10.4 9z"/><path d="M19 3v4M17 5h4M5.5 16v4M3.5 18h4"/>',
    "alert": '<path d="M12 3.5 21.5 20h-19z"/><path d="M12 10v4.5M12 17.5v.01"/>',
    "shield": '<path d="M12 3 19.5 6v6c0 4.3-3.2 7.6-7.5 9-4.3-1.4-7.5-4.7-7.5-9V6z"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "globe": '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.6 3.5 5.4 3.5 8.5s-1.1 5.9-3.5 8.5c-2.4-2.6-3.5-5.4-3.5-8.5s1.1-5.9 3.5-8.5z"/>',
    "chart": '<path d="M4 4v16h16"/><path d="M8 15v-3M12 15V8M16 15v-5"/>',
    "map-pin": '<path d="M12 21s-6.5-6-6.5-11A6.5 6.5 0 0 1 18.5 10c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
    "coins": '<ellipse cx="9" cy="7" rx="5.5" ry="2.5"/><path d="M3.5 7v4c0 1.4 2.5 2.5 5.5 2.5s5.5-1.1 5.5-2.5V7"/><path d="M9.5 15.5c.8.5 2.3 1 4.5 1 3 0 5.5-1.1 5.5-2.5v-4c0-1.2-1.8-2.2-4.3-2.4"/><path d="M19.5 14v4c0 1.4-2.5 2.5-5.5 2.5S8.5 19.4 8.5 18v-2.5"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "arrow-back": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "copy": '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6A1.5 1.5 0 0 0 14 4.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
    "note": '<path d="M5 4.5h14v15H5z"/><path d="M8.5 9h7M8.5 12.5h7M8.5 16h4"/>',
    "skip": '<path d="M6 6.5 13 12l-7 5.5zM17.5 6.5v11"/>',
    "key": '<circle cx="8" cy="15" r="4.5"/><path d="m11.5 11.5 8.5-8.5M17 6l2.5 2.5M14.5 8.5 16.5 10.5"/>',
    "bookmark": '<path d="M6.5 3.5h11v17L12 16.5l-5.5 4z"/>',
    "inbox": '<path d="M3.5 13.5 6 5h12l2.5 8.5V19a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 19z"/><path d="M3.5 13.5H8.5l1.5 2.5h4l1.5-2.5h5"/>',
    "tag": '<path d="M3.5 12V4.5a1 1 0 0 1 1-1H12l8.5 8.5-8.5 8.5z"/><circle cx="8" cy="8" r="1.5"/>',
    "megaphone": '<path d="M4 10v4h3l7 4.5v-13L7 10z"/><path d="M18 9a4 4 0 0 1 0 6M7 14l1 5.5h3L10 15"/>',
    "cart": '<circle cx="9" cy="19.5" r="1.5"/><circle cx="17.5" cy="19.5" r="1.5"/><path d="M2.5 3.5h3l2.5 12h11l2-8.5H6.5"/>',
    "zap": '<path d="M13 2.5 4.5 13.5H12L11 21.5l8.5-11H12z"/>',
    "plug": '<path d="M9 3.5v5M15 3.5v5M6.5 8.5h11V12a5.5 5.5 0 0 1-11 0z"/><path d="M12 17.5v3"/>',
    "wallet": '<path d="M4 6.5A2 2 0 0 1 6 4.5h11.5v3"/><path d="M4 6.5v11A2 2 0 0 0 6 19.5h14v-12H6a2 2 0 0 1-2-1z"/><circle cx="16.5" cy="13.5" r="1.2"/>',
    "layout": '<rect x="3.5" y="3.5" width="17" height="17" rx="2"/><path d="M3.5 9.5h17M10 9.5v11"/>',
    "file": '<path d="M6 3.5h8l4.5 4.5v12.5H6z"/><path d="M14 3.5V8h4.5M9 13h6M9 16.5h6"/>',
    "refresh": '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3L19.5 9"/><path d="M19.5 4v5h-5"/>',
}


def icon(name: str, size: int = 20, cls: str = "") -> Markup:
    body = _PATHS.get(name, _PATHS["package"])
    return Markup(
        f'<svg class="icon {cls}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true" focusable="false">{body}</svg>'
    )
