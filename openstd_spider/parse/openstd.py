import re
from datetime import date

from bs4 import BeautifulSoup

from ..exception import NotFoundError
from ..schema import StdListItem, StdMetaFull, StdSearchResult, StdStatus
from ..utils import name2std_status

# 列表页语义解析用的正则与关键词（openstd 站点列表的列数/列序不稳定，按内容而非列下标提取）
HCNO_RE = re.compile(r"'([0-9A-Fa-f]{16,})'")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
PAGE_RE = re.compile(r"共\s*(\d+)\s*条\s*标准\s*(\d+)\s*/\s*(\d+)")
STATUS_KEYWORDS = ("现行", "即将实施", "废止", "暂不实施")


def openstd_parse_meta(html_text: str) -> StdMetaFull:
    html = BeautifulSoup(html_text, "lxml")
    tag1 = html.select_one("div.bor2")
    tag2 = tag1.select_one("table.tdlist")
    tag3 = tag1.select("div[clsss='row'],[clsss='row detail']")

    std_code = list(tag1.select_one("table.mk1 tr td h1").strings)
    if std_code[0].startswith("您所查询的标准系统尚未收录"):
        raise NotFoundError
    is_ref = std_code[-1] == "采"
    _, std_code = std_code[0].split("标准号：")
    std_code = std_code.strip()

    if tag_pub_date := tag3[1].find(string=lambda x: "发布日期" in x):
        tag_pub_date = tag_pub_date.find_next().get_text(strip=True)
        tag_pub_date = m.group(0) if (m := DATE_RE.search(tag_pub_date)) else None
    else:
        tag_pub_date = None

    if tag_impl_date := tag3[1].find(string=lambda x: "实施日期" in x):
        tag_impl_date = tag_impl_date.find_next().get_text(strip=True)
        tag_impl_date = m.group(0) if (m := DATE_RE.search(tag_impl_date)) else None
    else:
        tag_impl_date = None

    return StdMetaFull(
        std_code=std_code,
        is_ref=is_ref,
        name_cn=tag2.select_one("tr:nth-of-type(1) td:nth-of-type(1) b").string,
        name_en=tag2.select_one("tr:nth-of-type(2) td:nth-of-type(1)").string.split("英文标准名称：")[1],
        status=name2std_status(tag2.select_one("tr:nth-of-type(3) td span").string.strip()),
        allow_preview=tag2.select_one("tr:nth-of-type(4) button.ck_btn") is not None,
        allow_download=tag2.select_one("tr:nth-of-type(4) button.xz_btn") is not None,
        pub_date=date.fromisoformat(tag_pub_date) if tag_pub_date else None,
        impl_date=date.fromisoformat(tag_impl_date) if tag_impl_date else None,
        ccs=tag3[0].find(string=lambda x: "中国标准分类号（CCS）" in x).find_next().string.strip(),
        ics=tag3[0].find(string=lambda x: "国际标准分类号（ICS）" in x).find_next().string.strip(),
        maintenance_depat=tag3[2].find(string=lambda x: "主管部门" in x).find_next().string.strip(),
        centralized_depat=tag3[2].find(string=lambda x: "归口部门" in x).find_next().string.strip(),
        pub_depat=tag3[3].find(string=lambda x: "发布单位" in x).find_next().string.strip(),
        comment=tag3[4].find(string=lambda x: "备注" in x).find_next().string.strip(),
    )


def openstd_parse_search_result(html_text: str) -> StdSearchResult:
    """解析标准列表页。

    openstd 站点的列表表格列数与列序并不稳定（不同查询可能返回 8 列或 10 列，
    "采标/标准性质"等列会动态增减），因此这里不依赖固定的列下标，而是按内容
    语义提取：
    - 标准号：以 "GB" 开头的 <a> 文本
    - 名称：同一行内另一个带 onclick 的 <a> 文本
    - id(hcno)：从 <a onclick="showInfo('HCNO')"> 中正则提取
    - 日期：行内所有 YYYY-MM-DD，按出现顺序前两个依次为发布/实施日期
    - 状态：<span> 文本命中状态关键词
    - 是否采标：某单元格文本恰为 "采"
    """
    items: list[StdListItem] = []
    html = BeautifulSoup(html_text, "lxml")
    for row in html.select("table.result_list>tbody:nth-of-type(2)>tr"):
        tds = row.find_all("td")
        hcno = None
        std_code = None
        name_cn = None
        for td in tds:
            a = td.find("a", attrs={"onclick": True})
            if a is None:
                continue
            m = HCNO_RE.search(a.get("onclick", ""))
            if m:
                hcno = m.group(1)
            text = a.get_text(strip=True)
            if not text:
                continue
            if std_code is None and text.startswith("GB"):
                std_code = text
            elif name_cn is None:
                name_cn = text
        # 行内所有日期，按出现顺序前两个为发布/实施日期
        dates = DATE_RE.findall(row.get_text())
        pub_date = dates[0] if len(dates) >= 1 else ""
        impl_date = dates[1] if len(dates) >= 2 else ""
        # 状态：<span> 文本命中关键词
        status_text = next(
            (s.get_text(strip=True) for s in row.find_all("span") if s.get_text(strip=True) in STATUS_KEYWORDS),
            "",
        )
        # 采标：某单元格文本恰为 "采"
        is_ref = any(td.get_text(strip=True) == "采" for td in tds)

        if std_code is None:
            # 异常行（没有标准号），跳过
            continue

        items.append(
            StdListItem(
                id=hcno or "",
                std_code=std_code,
                is_ref=is_ref,
                name_cn=name_cn or "",
                # ALL 仅作 dataclass 必填占位：列表项不存在全部状态,正常必命中状态关键词
                status=name2std_status(status_text) or StdStatus.ALL,
                pub_date=date.fromisoformat(pub_date) if pub_date else None,
                impl_date=date.fromisoformat(impl_date) if impl_date else None,
            )
        )

    # 分页信息，形如 "共 70494 条标准 1 / 7050"
    paging_node = html.select_one("div.hidden-xs")
    paging_text = paging_node.get_text(" ", strip=True) if paging_node else html.get_text(" ", strip=True)
    total_item = page = total_page = 0
    if m := PAGE_RE.search(paging_text):
        total_item, page, total_page = int(m.group(1)), int(m.group(2)), int(m.group(3))

    return StdSearchResult(
        items=items,
        total_item=total_item,
        page=page,
        total_page=total_page,
    )
