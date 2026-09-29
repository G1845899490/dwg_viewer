from __future__ import annotations

import re

_NUMBER_PATTERN = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"

_NUMBER = re.compile(_NUMBER_PATTERN)
_ID_TOKEN = re.compile(r"[0-9A-Za-z]+")
_BOUNDS_KEY = re.compile(
    rf"(?<![A-Za-z])(left|top|right|bottom)\s*[:=]?\s*({_NUMBER_PATTERN})",
    re.IGNORECASE,
)
_POINT_KEY = re.compile(
    rf"(?<![A-Za-z])(x|y|z)\s*[:=]?\s*({_NUMBER_PATTERN})",
    re.IGNORECASE,
)
_BRACKET = re.compile(r"[\[\(]([^\[\]\(\)]*)[\]\)]")

_FULLWIDTH = str.maketrans(
    {
        "\uff08": "(",
        "\uff09": ")",
        "\uff0c": ",",
        "\uff1b": ";",
        "\u3000": " ",
        "\uff0d": "-",
        "\uff0b": "+",
        "\uff0e": ".",
        "\uff1d": "=",
        "\uff1a": ":",
    }
)

Point = tuple[float, float]
Bounds = tuple[float, float, float, float]


class ParseError(ValueError):
    pass


def _normalize(text: str) -> str:
    return text.translate(_FULLWIDTH)


def parse_floats(text: str) -> list[float]:
    return [float(match.group()) for match in _NUMBER.finditer(_normalize(text))]


def _named_values(text: str, pattern: re.Pattern) -> dict[str, float]:
    values: dict[str, float] = {}
    for match in pattern.finditer(_normalize(text)):
        key = match.group(1).lower()
        if key not in values:
            values[key] = float(match.group(2))
    return values


def _bracket_numbers(text: str) -> list[float]:
    matches = _BRACKET.findall(_normalize(text))
    if not matches:
        return []
    inner = matches[-1]
    return [float(value) for value in _NUMBER.findall(inner)]


def parse_id(text: str) -> list[str]:
    """Extracts candidate entity handles from a decorated string.

    All characters except letters and digits are treated as separators, so a
    value like ``cn.mica.dxf.helpers.Point@17c930f4`` yields the tokens
    ``cn``, ``mica``, ``dxf``, ``helpers``, ``Point``, ``17c930f4``.
    Hex looking tokens are returned first (longest first) because DXF handles
    are hexadecimal.
    """
    tokens = _ID_TOKEN.findall(text or "")
    if not tokens:
        return []
    hex_like = [token for token in tokens if re.fullmatch(r"[0-9A-Fa-f]+", token)]
    hex_like.sort(key=lambda token: (-len(token), token))
    ordered: list[str] = []
    seen: set[str] = set()
    for token in hex_like + tokens:
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


def parse_point(text: str) -> Point:
    named = _named_values(text, _POINT_KEY)
    if "x" in named and "y" in named:
        return named["x"], named["y"]

    bracket = _bracket_numbers(text)
    if len(bracket) >= 2:
        return bracket[0], bracket[1]

    numbers = parse_floats(text)
    if len(numbers) == 2:
        return numbers[0], numbers[1]
    raise ParseError(f"点坐标需要 2 个浮点数，实际识别到 {len(numbers)} 个")


def parse_bounds(text: str) -> Bounds:
    named = _named_values(text, _BOUNDS_KEY)
    if all(key in named for key in ("left", "top", "right", "bottom")):
        return (
            named["left"],
            named["top"],
            named["right"],
            named["bottom"],
        )

    numbers = parse_floats(text)
    if len(numbers) != 4:
        raise ParseError(f"范围需要 4 个浮点数，实际识别到 {len(numbers)} 个")
    normalized = _normalize(text)
    if "(" in normalized or ")" in normalized:
        x1, y1, x2, y2 = numbers
        return (min(x1, x2), max(y1, y2), max(x1, x2), min(y1, y2))
    return numbers[0], numbers[1], numbers[2], numbers[3]
