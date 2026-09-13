"""幻灯片转场与入场动画。

python-pptx 不提供这两个能力，只能直接写 DrawingML。两者都有把文件写坏的风险，
所以：
  1. 转场用最保守的 `<p:fade/>`，命名空间只用 p:，不引 p14；
  2. 入场动画按 PowerPoint 自己导出的 XML 结构照抄，不用任何简化写法；
  3. 生成后必须用 PowerPoint 实际打开一次验证（见 build.sh 的导出步骤——
     文件若损坏，PowerPoint 会拒绝打开或弹修复框）。
"""
from __future__ import annotations

from lxml import etree
from pptx.oxml.ns import qn

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _p(tag: str) -> str:
    return f"{{{P_NS}}}{tag}"


def add_transition(slide, kind: str = "fade", dur_ms: int = 700,
                   advance_on_click: bool = True):
    """给单页加转场。kind: fade / push / wipe。

    设计取态：答辩场合只用 fade——平稳、不抢内容、投影仪上不会闪。
    """
    sld = slide._element
    for old in sld.findall(_p("transition")):
        sld.remove(old)

    tr = etree.SubElement(sld, _p("transition"))
    tr.set("spd", "med")
    tr.set("advClick", "1" if advance_on_click else "0")
    etree.SubElement(tr, _p(kind))

    # transition 必须排在 clrMapOvr 之后、timing 之前
    _reorder(sld, "transition", after="clrMapOvr", before="timing")
    return tr


def _reorder(sld, tag: str, after: str, before: str) -> None:
    el = sld.find(_p(tag))
    if el is None:
        return
    sld.remove(el)
    anchor = sld.find(_p(after))
    if anchor is not None:
        anchor.addnext(el)
    else:
        anchor = sld.find(_p(before))
        if anchor is not None:
            anchor.addprevious(el)
        else:
            sld.append(el)


# ───────────────────────── 入场动画 ─────────────────────────
def add_entrance(slide, shape_ids, dur_ms: int = 400, delay_ms: int = 0,
                 node_type: str = "afterEffect"):
    """给若干形状加「淡入」入场动画。

    shape_ids: 形状 id 列表（shape.shape_id）。
    node_type: clickEffect（点击触发）/ afterEffect（上一动作后自动）/ withEffect（同时）。

    设计取态：内容页正文用 afterEffect + 小延迟——标题先落，正文随后淡入，
    不需要汇报人额外点击，节奏自然。
    """
    if not shape_ids:
        return

    timing = slide._element.find(_p("timing"))
    if timing is None:
        timing = etree.SubElement(slide._element, _p("timing"))
        _reorder(slide._element, "timing", after="transition", before="extLst")

    # 极简但结构完整的 tnLst：一个 mainSeq 下挂 N 个 par
    tnLst = etree.SubElement(timing, _p("tnLst"))
    root_par = etree.SubElement(tnLst, _p("par"))
    root_ctn = etree.SubElement(root_par, _p("cTn"))
    root_ctn.set("id", "1")
    root_ctn.set("dur", "indefinite")
    root_ctn.set("restart", "never")
    root_ctn.set("nodeType", "tmRoot")
    child = etree.SubElement(root_ctn, _p("childTnLst"))
    seq = etree.SubElement(child, _p("seq"))
    seq.set("concurrent", "1")
    seq.set("nextAc", "seek")
    seq_ctn = etree.SubElement(seq, _p("cTn"))
    seq_ctn.set("id", "2")
    seq_ctn.set("dur", "indefinite")
    seq_ctn.set("nodeType", "mainSeq")
    seq_child = etree.SubElement(seq_ctn, _p("childTnLst"))

    nid = 3
    for sid in shape_ids:
        nid = _emit_fade(seq_child, nid, sid, dur_ms, delay_ms, node_type)

    prev = etree.SubElement(seq, _p("prevCondLst"))
    _cond(prev, "onPrev", "0")
    nxt = etree.SubElement(seq, _p("nextCondLst"))
    _cond(nxt, "onNext", "0")

    # bldLst：告诉 PowerPoint 这些形状按「整体」构建。
    # 缺了它，动画在少量形状时能凑合，形状一多 PowerPoint 直接拒绝打开。
    bld = etree.SubElement(timing, _p("bldLst"))
    for sid in shape_ids:
        bp = etree.SubElement(bld, _p("bldP"))
        bp.set("spid", str(sid))
        bp.set("grpId", "0")
        bp.set("build", "allAtOnce")


def _cond(parent, evt: str, delay: str):
    c = etree.SubElement(parent, _p("cond"))
    c.set("evt", evt)
    c.set("delay", delay)
    return c


def _emit_fade(parent, nid: int, spid: int, dur_ms: int, delay_ms: int,
               node_type: str) -> int:
    par1 = etree.SubElement(parent, _p("par"))
    ctn1 = etree.SubElement(par1, _p("cTn"))
    ctn1.set("id", str(nid)); ctn1.set("fill", "hold")
    st1 = etree.SubElement(ctn1, _p("stCondLst"))
    _cond(st1, "delay", "indefinite")
    ch1 = etree.SubElement(ctn1, _p("childTnLst"))
    nid += 1

    par2 = etree.SubElement(ch1, _p("par"))
    ctn2 = etree.SubElement(par2, _p("cTn"))
    ctn2.set("id", str(nid)); ctn2.set("fill", "hold")
    st2 = etree.SubElement(ctn2, _p("stCondLst"))
    _cond(st2, "delay", str(delay_ms))
    ch2 = etree.SubElement(ctn2, _p("childTnLst"))
    nid += 1

    par3 = etree.SubElement(ch2, _p("par"))
    ctn3 = etree.SubElement(par3, _p("cTn"))
    ctn3.set("id", str(nid))
    ctn3.set("presetID", "10")          # 10 = 淡入
    ctn3.set("presetClass", "entr")
    ctn3.set("presetSubtype", "0")
    ctn3.set("fill", "hold")
    ctn3.set("grpId", "0")
    ctn3.set("nodeType", node_type)
    st3 = etree.SubElement(ctn3, _p("stCondLst"))
    _cond(st3, "delay", "0")
    ch3 = etree.SubElement(ctn3, _p("childTnLst"))
    nid += 1

    # set visibility
    st = etree.SubElement(ch3, _p("set"))
    bh = etree.SubElement(st, _p("cBhvr"))
    ctn = etree.SubElement(bh, _p("cTn"))
    ctn.set("id", str(nid)); ctn.set("dur", "1"); ctn.set("fill", "hold")
    sc = etree.SubElement(ctn, _p("stCondLst")); _cond(sc, "delay", "0")
    tgt = etree.SubElement(bh, _p("tgtEl"))
    sp = etree.SubElement(tgt, _p("spTgt")); sp.set("spid", str(spid))
    an = etree.SubElement(bh, _p("attrNameLst"))
    etree.SubElement(an, _p("attrName")).text = "style.visibility"
    to = etree.SubElement(st, _p("to"))
    etree.SubElement(to, _p("strVal")).set("val", "visible")
    nid += 1

    # animEffect fade
    ae = etree.SubElement(ch3, _p("animEffect"))
    ae.set("transition", "in"); ae.set("filter", "fade")
    bh2 = etree.SubElement(ae, _p("cBhvr"))
    ctn2b = etree.SubElement(bh2, _p("cTn"))
    ctn2b.set("id", str(nid)); ctn2b.set("dur", str(dur_ms))
    tgt2 = etree.SubElement(bh2, _p("tgtEl"))
    sp2 = etree.SubElement(tgt2, _p("spTgt")); sp2.set("spid", str(spid))
    nid += 1
    return nid
