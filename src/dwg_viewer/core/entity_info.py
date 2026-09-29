from __future__ import annotations

import math
from typing import Any

from ezdxf import bbox
from ezdxf.entities import DXFEntity
from ezdxf.math import Matrix44, Vec3


def _find_transform_to_handle(
    entities, target_handle: str, blocks, matrix: Matrix44, depth: int
) -> Matrix44 | None:
    for entity in entities:
        try:
            if str(entity.dxf.get("handle", "")) == target_handle:
                return matrix
        except Exception:
            pass
        try:
            if entity.dxftype() == "INSERT" and depth < 12:
                block = blocks.get(entity.dxf.get("name", ""))
                if block is None:
                    continue
                try:
                    child = entity.matrix44()
                except Exception:
                    child = Matrix44()
                found = _find_transform_to_handle(
                    list(block), target_handle, blocks, child @ matrix, depth + 1
                )
                if found is not None:
                    return found
        except Exception:
            continue
    return None


def entity_world_extents(entity: DXFEntity):
    """Returns the world extents of an entity.

    Entities nested in block references have coordinates in the block
    definition system; this composes the INSERT transform chain so the result
    is in world (model space) coordinates.
    """
    local = entity_extents(entity)
    if local is None:
        return None
    doc = getattr(entity, "doc", None)
    if doc is None:
        return local
    try:
        handle = str(entity.dxf.get("handle", ""))
    except Exception:
        return local
    if not handle:
        return local
    try:
        matrix = _find_transform_to_handle(
            list(doc.modelspace()), handle, doc.blocks, Matrix44(), 0
        )
    except Exception:
        matrix = None
    if matrix is None:
        return local
    extmin, extmax = local
    xs: list[float] = []
    ys: list[float] = []
    for x in (extmin.x, extmax.x):
        for y in (extmin.y, extmax.y):
            point = matrix.transform(Vec3(x, y, 0.0))
            xs.append(point.x)
            ys.append(point.y)
    return (Vec3(min(xs), min(ys), 0.0), Vec3(max(xs), max(ys), 0.0))



def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


# Human readable meaning of common DXF group codes.
GROUP_CODE_MEANINGS: dict[int, str] = {
    0: "实体/记录类型",
    1: "主文本值",
    2: "名称（如块名、样式名）",
    3: "附加文本值",
    5: "Handle（图元唯一句柄）",
    6: "线型名",
    7: "文字样式名",
    8: "图层名",
    9: "变量名标识",
    10: "主点 X（起点/中心等）",
    11: "第二点 X",
    12: "第三点 X",
    13: "第四点 X",
    20: "主点 Y",
    21: "第二点 Y",
    22: "第三点 Y",
    23: "第四点 Y",
    30: "主点 Z",
    31: "第二点 Z",
    32: "第三点 Z",
    33: "第四点 Z",
    38: "标高 (elevation)",
    39: "厚度 (thickness)",
    40: "起点宽度 / 半径 / 高度等",
    41: "终点宽度 / X 比例",
    42: "弓度 (bulge)",
    43: "恒定宽度 / Y 比例",
    44: "Z 比例 / 间距",
    45: "填充/行距等浮点值",
    48: "线型比例",
    49: "重复的浮点值",
    50: "旋转角度",
    51: "起始角度",
    52: "结束角度",
    62: "颜色（ACI 索引；256=ByLayer，0=ByBlock）",
    66: "是否跟随顶点/属性（1=有）",
    67: "空间标志（0=模型空间，1=图纸空间）",
    70: "标志位（含义随实体而定）",
    71: "标志/计数",
    72: "标志/计数",
    73: "标志/计数",
    74: "标志/计数",
    75: "标志/计数",
    76: "标志/计数",
    78: "顶点数等计数",
    90: "32 位整数（顶点数/标志）",
    91: "32 位整数",
    92: "32 位整数",
    100: "子类标记（如 AcDbEntity）",
    102: "控制字符串（反应器/扩展字典）",
    105: "Handle（DIMSTYLE 用）",
    210: "拉伸方向 X",
    220: "拉伸方向 Y",
    230: "拉伸方向 Z",
    280: "8 位整数（标志）",
    281: "8 位整数",
    282: "8 位整数",
    283: "8 位整数",
    284: "8 位整数",
    290: "布尔值（0/1）",
    291: "布尔值（0/1）",
    300: "任意字符串",
    301: "任意字符串",
    310: "二进制数据（十六进制）",
    330: "所有者 Handle（软指针）",
    340: "对象 Handle（软指针）",
    347: "材质 Handle",
    350: "对象 Handle（软指针）",
    360: "硬所有者 Handle（扩展字典）",
    370: "线宽（单位 1/100 mm）",
    390: "打印样式 Handle",
    410: "布局名",
    420: "真彩色（24 位 RGB，0xRRGGBB）",
    430: "颜色名（颜色簿）",
    440: "透明度（0–255）",
    999: "注释",
    1000: "XDATA 字符串",
    1001: "XDATA 应用名（AppID）",
    1002: "XDATA 控制字符串",
    1003: "XDATA 图层名",
    1004: "XDATA 二进制数据",
    1005: "XDATA Handle",
    1040: "XDATA 浮点值",
    1041: "XDATA 距离",
    1042: "XDATA 比例",
    1070: "XDATA 16 位整数",
    1071: "XDATA 32 位整数",
}

# (low, high, meaning) — used when no exact code entry exists.
_GROUP_CODE_RANGES = (
    (300, 309, "任意字符串"),
    (310, 319, "二进制数据"),
    (320, 329, "对象 Handle"),
    (330, 339, "软指针 Handle"),
    (340, 349, "软指针 Handle"),
    (350, 359, "软指针 Handle"),
    (360, 369, "硬所有者 Handle"),
    (390, 399, "打印样式 Handle"),
    (400, 409, "16 位整数"),
    (410, 419, "字符串"),
    (420, 429, "32 位整数"),
    (430, 439, "字符串（颜色名）"),
    (440, 449, "32 位整数（透明度）"),
    (450, 459, "长整数"),
    (460, 469, "浮点值"),
    (470, 481, "字符串"),
    (999, 999, "注释"),
    (1000, 1009, "XDATA 字符串"),
    (1010, 1019, "XDATA 三维点 X/Y/Z"),
    (1020, 1029, "XDATA 三维点 X/Y/Z"),
    (1030, 1039, "XDATA 三维点 X/Y/Z"),
    (1040, 1041, "XDATA 浮点/距离"),
    (1042, 1049, "XDATA 浮点/比例"),
    (1050, 1059, "XDATA 浮点"),
    (1060, 1069, "XDATA 16 位整数"),
    (1070, 1070, "XDATA 16 位整数"),
    (1071, 1071, "XDATA 32 位整数"),
)


def describe_code(code: int) -> str:
    meaning = GROUP_CODE_MEANINGS.get(code)
    if meaning:
        return meaning
    for low, high, text in _GROUP_CODE_RANGES:
        if low <= code <= high:
            return text
    if 10 <= code <= 18:
        return "点坐标 X"
    if 20 <= code <= 28:
        return "点坐标 Y"
    if 30 <= code <= 38:
        return "点坐标 Z"
    if 40 <= code <= 48:
        return "浮点值（宽度/比例/角度等）"
    if 60 <= code <= 79:
        return "16 位整数（标志/计数）"
    if 90 <= code <= 99:
        return "32 位整数"
    return ""


def collect_codes(text: str) -> list[int]:
    """Extracts the group codes used in a dumped tag list."""
    codes: set[int] = set()
    for line in text.splitlines():
        stripped = line.lstrip()
        head = stripped.split(" ", 1)[0]
        if head.isdigit() or (head[:1] == "-" and head[1:].isdigit()):
            try:
                codes.add(int(head))
            except ValueError:
                continue
    return sorted(codes)


def group_code_help(codes: list[int]) -> list[tuple[str, str]]:
    return [(str(code), describe_code(code)) for code in codes]


def entity_extents(entity: DXFEntity):
    try:
        extents = bbox.extents([entity], fast=True)
    except Exception:
        return None
    if extents is None or not extents.has_data:
        return None
    return extents.extmin, extents.extmax


def _basic_pairs(entity: DXFEntity) -> list[tuple[str, Any]]:
    pairs: list[tuple[str, Any]] = [
        ("类型", entity.dxftype()),
        ("Handle", entity.dxf.get("handle", "")),
        ("图层", entity.dxf.get("layer", "")),
    ]
    if (color := entity.dxf.get("color", None)) is not None:
        pairs.append(("颜色(ACI)", color))
    if (true_color := entity.dxf.get("true_color", None)) is not None:
        pairs.append(("真彩色", f"#{int(true_color):06X}"))
    if (lineweight := entity.dxf.get("lineweight", None)) is not None:
        pairs.append(("线宽", lineweight))
    if linetype := entity.dxf.get("linetype", None):
        pairs.append(("线型", linetype))
    extents = entity_extents(entity)
    if extents is not None:
        extmin, extmax = extents
        xmin, xmax = sorted((extmin.x, extmax.x))
        ymin, ymax = sorted((extmin.y, extmax.y))
        width = xmax - xmin
        height = ymax - ymin
        pairs.append(("范围", f"({xmin:g}, {ymax:g}, {xmax:g}, {ymin:g})"))
        pairs.append(("宽度(X)", f"{width:g}"))
        pairs.append(("高度(Y)", f"{height:g}"))
    return pairs


def _xy(point) -> str:
    return f"({point.x:g}, {point.y:g})"


def _type_specific_pairs(entity: DXFEntity) -> list[tuple[str, Any]]:
    """Returns the most important measurements for the entity type."""
    dxftype = entity.dxftype()
    dxf = entity.dxf
    pairs: list[tuple[str, Any]] = []

    def add(key: str, value: Any) -> None:
        pairs.append((key, value))

    try:
        if dxftype == "LINE":
            start = dxf.start
            end = dxf.end
            add("起点", _xy(start))
            add("终点", _xy(end))
            delta_x = end.x - start.x
            delta_y = end.y - start.y
            add("长度", f"{math.hypot(delta_x, delta_y):g}")
            add("角度(°)", f"{math.degrees(math.atan2(delta_y, delta_x)) % 360:g}")
        elif dxftype == "CIRCLE":
            center = dxf.center
            radius = dxf.radius
            add("圆心", _xy(center))
            add("半径", f"{radius:g}")
            add("直径", f"{2 * radius:g}")
            add("周长", f"{2 * math.pi * radius:g}")
            add("面积", f"{math.pi * radius * radius:g}")
        elif dxftype == "ARC":
            center = dxf.center
            radius = dxf.radius
            start_angle = dxf.start_angle
            end_angle = dxf.end_angle
            sweep = (end_angle - start_angle) % 360
            add("圆心", _xy(center))
            add("半径", f"{radius:g}")
            add("起始角度(°)", f"{start_angle:g}")
            add("终止角度(°)", f"{end_angle:g}")
            add("圆心角(°)", f"{sweep:g}")
            add("弧长", f"{math.radians(sweep) * radius:g}")
        elif dxftype == "LWPOLYLINE":
            try:
                points = list(entity.get_points("xyb"))
            except Exception:
                points = list(entity.get_points())
            add("顶点数", len(points))
            add("闭合", "是" if dxf.get("flags", 0) & 1 else "否")
            for index, point in enumerate(points[:200], start=1):
                x, y = point[0], point[1]
                bulge = point[2] if len(point) > 2 else 0
                text = f"({x:g}, {y:g})"
                if bulge:
                    text += f"  凸度={bulge:g}"
                add(f"顶点{index}", text)
            if len(points) > 200:
                add("...", f"省略 {len(points) - 200} 个顶点")
        elif dxftype == "POLYLINE":
            vertices = list(entity.vertices)
            add("顶点数", len(vertices))
            add("闭合", "是" if dxf.get("flags", 0) & 1 else "否")
            for index, vertex in enumerate(vertices[:200], start=1):
                location = vertex.dxf.get("location", None)
                bulge = vertex.dxf.get("bulge", 0)
                text = _xy(location) if location is not None else ""
                if bulge:
                    text += f"  凸度={bulge:g}"
                add(f"顶点{index}", text)
            if len(vertices) > 200:
                add("...", f"省略 {len(vertices) - 200} 个顶点")
        elif dxftype == "ELLIPSE":
            center = dxf.center
            major = dxf.major_axis
            ratio = dxf.ratio
            major_len = math.hypot(major.x, major.y)
            add("中心", _xy(center))
            add("长半轴", f"{major_len:g}")
            add("短半轴", f"{major_len * ratio:g}")
            add("起始参数(°)", f"{math.degrees(dxf.start_param):g}")
            add("终止参数(°)", f"{math.degrees(dxf.end_param):g}")
        elif dxftype == "SPLINE":
            add("阶数", dxf.get("degree", ""))
            add("控制点数", len(entity.control_points))
            add("拟合点数", len(entity.fit_points))
            add("闭合", "是" if dxf.get("flags", 0) & 1 else "否")
        elif dxftype == "POINT":
            location = dxf.location
            add("坐标", _xy(location))
        elif dxftype == "TEXT":
            add("内容", dxf.get("text", ""))
            add("高度", dxf.get("height", ""))
            add("旋转(°)", dxf.get("rotation", 0))
            add("插入点", _xy(dxf.get("insert", Vec3(0, 0, 0))))
        elif dxftype == "MTEXT":
            text = entity.text or ""
            add("内容", text[:300])
            add("字高", dxf.get("char_height", ""))
            add("插入点", _xy(dxf.get("insert", Vec3(0, 0, 0))))
        elif dxftype == "HATCH":
            add("图案", dxf.get("pattern_name", ""))
            add("实体填充", "是" if dxf.get("solid_fill", 0) else "否")
            add("边界数", len(entity.paths))
            add("关联", "是" if dxf.get("associative", 0) else "否")
        elif dxftype == "INSERT":
            add("块名", dxf.get("name", ""))
            insert_point = dxf.get("insert", None)
            if insert_point is not None:
                add("插入点", _xy(insert_point))
            add("X 比例", dxf.get("xscale", 1))
            add("Y 比例", dxf.get("yscale", 1))
            add("Z 比例", dxf.get("zscale", 1))
            add("旋转(°)", dxf.get("rotation", 0))
            add("列数", dxf.get("column_count", 1))
            add("行数", dxf.get("row_count", 1))
        elif dxftype in ("SOLID", "TRACE", "3DFACE"):
            for name in ("vtx0", "vtx1", "vtx2", "vtx3"):
                vertex = dxf.get(name, None)
                if vertex is not None:
                    add(name, _xy(vertex))
        elif dxftype == "DIMENSION":
            add("类型", dxf.get("dimtype", 0))
            measurement = dxf.get("actual_measurement", None)
            if measurement is not None:
                add("测量值", f"{measurement:g}")
            add("文字", dxf.get("text", ""))
    except Exception:
        pass
    return pairs


def _attribute_pairs(entity: DXFEntity) -> list[tuple[str, Any]]:
    try:
        attribs = entity.dxf.all_existing_dxf_attribs()
    except Exception:
        return []
    return [(str(key), value) for key, value in attribs.items()]


def _xdata_pairs(entity: DXFEntity) -> list[tuple[str, Any]]:
    xdata = getattr(entity, "xdata", None)
    data = getattr(xdata, "data", None) if xdata is not None else None
    if not data:
        return []
    pairs: list[tuple[str, Any]] = []
    for appid, tags in data.items():
        for tag in tags:
            if tag.code == 1001:
                continue  # application name is already shown as prefix
            pairs.append((f"[{appid}] {tag.code}", tag.value))
    return pairs


def _owner_pairs(entity: DXFEntity) -> list[tuple[str, Any]]:
    doc = getattr(entity, "doc", None)
    owner = None
    try:
        owner = entity.dxf.get("owner", None)
    except Exception:
        pass
    if not owner:
        return []
    pairs: list[tuple[str, Any]] = [("所有者 Handle", owner)]
    if doc is not None:
        try:
            record = doc.entitydb.get(owner)
            if record is not None:
                name = record.dxf.get("name", None)
                if name:
                    pairs.append(("所有者名称", name))
                else:
                    pairs.append(("所有者类型", record.dxftype()))
        except Exception:
            pass
    return pairs


def _layer_pairs(entity: DXFEntity) -> list[tuple[str, Any]]:
    doc = getattr(entity, "doc", None)
    try:
        name = entity.dxf.get("layer", "")
    except Exception:
        return []
    if doc is None or not name:
        return []
    try:
        layer = doc.layers.get(name)
    except Exception:
        return []
    if layer is None:
        return []
    pairs: list[tuple[str, Any]] = []
    try:
        pairs.append(("图层颜色(ACI)", layer.dxf.get("color", 7)))
    except Exception:
        pass
    try:
        tc = layer.dxf.get("true_color", None)
        if tc is not None:
            pairs.append(("图层真彩色", f"#{int(tc):06X}"))
    except Exception:
        pass
    try:
        pairs.append(("图层线型", layer.dxf.get("linetype", "")))
    except Exception:
        pass
    try:
        pairs.append(("图层线宽", layer.dxf.get("lineweight", 0)))
    except Exception:
        pass
    try:
        pairs.append(("关闭", "是" if layer.is_off() else "否"))
    except Exception:
        pass
    try:
        pairs.append(("冻结", "是" if layer.is_frozen() else "否"))
    except Exception:
        pass
    return pairs


def _extension_dict_pairs(entity: DXFEntity) -> list[tuple[str, Any]]:
    try:
        has = entity.has_extension_dict
    except Exception:
        return []
    if not has:
        return []
    doc = getattr(entity, "doc", None)
    pairs: list[tuple[str, Any]] = []
    try:
        ext = entity.get_extension_dict()
    except Exception:
        return []
    try:
        items = list(ext.items())
    except Exception:
        return []
    for key, value in items:
        handle = str(value)
        dxftype = ""
        if doc is not None:
            try:
                referenced = doc.entitydb.get(handle)
                if referenced is not None:
                    dxftype = referenced.dxftype()
            except Exception:
                dxftype = ""
        pairs.append((str(key), f"{handle} ({dxftype})" if dxftype else handle))
    return pairs


def _reactor_pairs(entity: DXFEntity) -> list[tuple[str, Any]]:
    try:
        if not entity.has_reactors:
            return []
        reactors = list(entity.reactors)
    except Exception:
        return []
    doc = getattr(entity, "doc", None)
    pairs: list[tuple[str, Any]] = []
    for handle in reactors:
        handle = str(handle)
        dxftype = ""
        if doc is not None:
            try:
                referenced = doc.entitydb.get(handle)
                if referenced is not None:
                    dxftype = referenced.dxftype()
            except Exception:
                dxftype = ""
        pairs.append((handle, dxftype or ""))
    return pairs


def entity_sections(entity: DXFEntity) -> list[tuple[str, list[tuple[str, str]]]]:
    sections: list[tuple[str, list[tuple[str, str]]]] = [
        ("基本信息", [(key, _format_value(value)) for key, value in _basic_pairs(entity)]),
    ]
    type_pairs = _type_specific_pairs(entity)
    if type_pairs:
        sections.append(
            ("类型数据", [(key, _format_value(value)) for key, value in type_pairs])
        )
    owner = _owner_pairs(entity)
    if owner:
        sections.append(("所有者", [(key, _format_value(value)) for key, value in owner]))
    layer = _layer_pairs(entity)
    if layer:
        sections.append(("所属图层", [(key, _format_value(value)) for key, value in layer]))
    sections.append(
        ("属性", [(key, _format_value(value)) for key, value in _attribute_pairs(entity)])
    )
    xdata = _xdata_pairs(entity)
    if xdata:
        sections.append(
            ("扩展数据 (XDATA)", [(key, _format_value(value)) for key, value in xdata])
        )
    ext_dict = _extension_dict_pairs(entity)
    if ext_dict:
        sections.append(
            ("扩展字典", [(key, _format_value(value)) for key, value in ext_dict])
        )
    reactors = _reactor_pairs(entity)
    if reactors:
        sections.append(
            ("反应器", [(key, _format_value(value)) for key, value in reactors])
        )
    return sections


def _dxf_version(entity: DXFEntity) -> str:
    doc = getattr(entity, "doc", None)
    return doc.dxfversion if doc is not None else "AC1032"


def entity_full_dump(entity: DXFEntity) -> str:
    """Returns every DXF tag of the entity as text."""
    from ezdxf.lldxf.tagwriter import TagCollector

    try:
        collector = TagCollector(dxfversion=_dxf_version(entity))
        tags = collector.dxftags(entity)
    except Exception:
        return ""
    return "\n".join(f"{tag.code:>4}  {_format_value(tag.value)}" for tag in tags)


def insert_block(insert: DXFEntity):
    doc = getattr(insert, "doc", None)
    if doc is None:
        return None
    try:
        return doc.blocks.get(insert.dxf.get("name", ""))
    except Exception:
        return None


def insert_internal_entities(insert: DXFEntity) -> list:
    block = insert_block(insert)
    return list(block) if block is not None else []


def insert_attribs(insert: DXFEntity) -> list:
    try:
        return list(insert.attribs)
    except Exception:
        return []


def insert_sections(insert: DXFEntity) -> list[tuple[str, list[tuple[str, str]]]]:
    block = insert_block(insert)
    sections: list[tuple[str, list[tuple[str, str]]]] = [
        (
            "块定义",
            [
                ("块名", insert.dxf.get("name", "")),
                ("内部图元数", str(len(block)) if block is not None else "0"),
            ],
        ),
        ("块引用信息", [(key, _format_value(value)) for key, value in _basic_pairs(insert)]),
        ("类型数据", [(key, _format_value(value)) for key, value in _type_specific_pairs(insert)]),
        ("属性", [(key, _format_value(value)) for key, value in _attribute_pairs(insert)]),
    ]
    attribs = insert_attribs(insert)
    if attribs:
        sections.append(
            (
                "属性文字 (ATTRIB)",
                [
                    (
                        attrib.dxf.get("tag", ""),
                        attrib.dxf.get("text", ""),
                    )
                    for attrib in attribs
                ],
            )
        )
    for title, pairs in (
        ("所有者", _owner_pairs(insert)),
        ("所属图层", _layer_pairs(insert)),
        ("扩展字典", _extension_dict_pairs(insert)),
        ("反应器", _reactor_pairs(insert)),
    ):
        if pairs:
            sections.append(
                (title, [(key, _format_value(value)) for key, value in pairs])
            )
    return sections


def insert_full_dump(insert: DXFEntity, max_entities: int = 500) -> str:
    version = _dxf_version(insert)
    parts = ["# INSERT 图元", entity_full_dump(insert)]
    for attrib in insert_attribs(insert):
        parts.append(
            f"\n## ATTRIB {attrib.dxf.get('tag', '')}\n{entity_full_dump(attrib)}"
        )
    block = insert_block(insert)
    if block is not None:
        entities = list(block)
        parts.append(
            f"\n# 块定义 '{insert.dxf.get('name', '')}' 内部图元 ({len(entities)})"
        )
        for entity in entities[:max_entities]:
            parts.append(
                f"\n## {entity.dxftype()} (Handle {entity.dxf.get('handle', '')})"
            )
            parts.append(entity_full_dump(entity))
        if len(entities) > max_entities:
            parts.append(f"\n... 省略 {len(entities) - max_entities} 个图元")
    return "\n".join(parts)
