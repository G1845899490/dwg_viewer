from __future__ import annotations

from ezdxf.addons.drawing.unified_text_renderer import UnifiedTextRenderer
from ezdxf.fonts import fonts

CJK_FONT_CANDIDATES = (
    "ARIALUNI.ttf",  # Arial Unicode MS - pan Unicode
    "simsun.ttc",  # SimSun
    "msyh.ttc",  # Microsoft YaHei
    "simhei.ttf",  # SimHei
    "simkai.ttf",  # KaiTi
    "Deng.ttf",  # DengXian
)

_fallback_name = ""
_installed = False


def _is_cjk(codepoint: int) -> bool:
    return (
        0x2E80 <= codepoint <= 0x2FFF  # CJK radicals, Kangxi
        or 0x3000 <= codepoint <= 0x30FF  # CJK punctuation, kana
        or 0x3100 <= codepoint <= 0x312F  # Bopomofo
        or 0x31A0 <= codepoint <= 0x31BF
        or 0x3400 <= codepoint <= 0x4DBF  # CJK ext A
        or 0x4E00 <= codepoint <= 0x9FFF  # CJK unified
        or 0xF900 <= codepoint <= 0xFAFF  # CJK compatibility
        or 0xFE30 <= codepoint <= 0xFE4F
        or 0xFF00 <= codepoint <= 0xFFEF  # fullwidth forms
        or 0x20000 <= codepoint <= 0x2FA1F  # CJK ext B-F
    )


def _contains_cjk(text: str) -> bool:
    return any(_is_cjk(ord(ch)) for ch in text)


def available_cjk_font() -> str:
    for name in CJK_FONT_CANDIDATES:
        if fonts.font_manager.has_font(name):
            return name
    return ""


class CjkFallbackTextRenderer(UnifiedTextRenderer):
    """Text renderer which substitutes a CJK capable font for text containing CJK
    characters, because many CAD text styles reference fonts without CJK glyphs
    (e.g. arial.ttf) and would otherwise render as ``.notdef`` boxes.
    """

    def __init__(self, fallback_name: str):
        super().__init__()
        self._fallback_name = fallback_name
        self._fallback_font = None

    def _fallback(self):
        if self._fallback_font is None:
            self._fallback_font = fonts.make_font(self._fallback_name, 1.0)
        return self._fallback_font

    def _font_for(self, text: str, font_face):
        if self._fallback_name and _contains_cjk(text):
            return self._fallback()
        return self.get_font(font_face)

    def get_text_path(self, text, font_face, cap_height=1.0):
        return self._font_for(text, font_face).text_path_ex(text, cap_height)

    def get_text_glyph_paths(self, text, font_face, cap_height=1.0):
        return self._font_for(text, font_face).text_glyph_paths(text, cap_height)

    def get_text_line_width(self, text, font_face, cap_height=1.0):
        return self._font_for(text, font_face).text_width_ex(text, cap_height)


def install_cjk_fallback() -> str:
    global _fallback_name, _installed
    if _installed:
        return _fallback_name
    name = available_cjk_font()
    if name:
        from ezdxf.addons.drawing.pipeline import RenderPipeline2d

        RenderPipeline2d.text_engine = CjkFallbackTextRenderer(name)
        _fallback_name = name
    _installed = True
    return _fallback_name
