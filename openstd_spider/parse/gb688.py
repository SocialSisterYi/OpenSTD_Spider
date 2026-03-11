import re
import urllib.parse
from pathlib import Path

import cv2
import numpy as np
from bs4 import BeautifulSoup

from ..schema import Gb688Block, Gb688Page


def gb688_uniq_imgid(page_infos: list[Gb688Page]) -> set[str]:
    return set(page_info.img_id for page_info in page_infos)


def gb688_parse_page_sheet(html_text: str) -> list[Gb688Page]:
    """解析页面和图块表"""
    pagesheets = []
    html = BeautifulSoup(html_text, "lxml")
    for page in html.select("div#viewer div.page"):
        page_blocks = []
        for block in page.select('span[class^="pdfImg"]'):
            _, block_x, block_y = block["class"][0].split("-")
            style_matches = re.search(
                r"background-position: *-(\d+)px +-(\d+)px", block["style"]
            )
            page_blocks.append(
                Gb688Block(
                    x=int(block_x),
                    y=int(block_y),
                    img_x=int(style_matches.group(1)),
                    img_y=int(style_matches.group(2)),
                )
            )
        page_blocks.sort(key=lambda x: (x.y, x.x))
        style = page["style"]
        pagesheets.append(
            Gb688Page(
                no=int(page["id"]),
                img_id=urllib.parse.unquote(page["bg"]),
                h=int(re.search(r"height: *(\d+)px", style).group(1)),
                w=int(re.search(r"width: *(\d+)px", style).group(1)),
                blocks=page_blocks,
            )
        )
    return pagesheets


def image_paste_white(img: np.ndarray):
    """透明图层加白背景"""
    bg = np.full((*img.shape[:2], 3), 255, np.uint8)
    # 分离通道
    alpha = img[:, :, 3]
    img = img[:, :, :3]

    alpha = alpha.astype(float) / 255.0
    alpha = np.expand_dims(alpha, axis=-1)

    composite = img * alpha + bg * (1 - alpha)
    composite = composite.astype(np.uint8)
    return composite


def gb688_reorganize_page(page: Gb688Page, raw_img_file: Path, page_img_file: Path):
    """重组页面"""
    raw_img = cv2.imread(str(raw_img_file), cv2.IMREAD_UNCHANGED)
    raw_img = image_paste_white(raw_img)
    block_h, block_w = page.h // 10, page.w // 10

    page_img = np.full((page.h, page.w, 3), 255, np.uint8)
    for block in page.blocks:
        # 提取图块
        block_img = raw_img[
            block.img_y : block.img_y + block_h,
            block.img_x : block.img_x + block_w,
        ]

        # 粘贴图块
        page_y = block.y * block_h
        page_x = block.x * block_w
        page_img[page_y : page_y + block_h, page_x : page_x + block_w] = block_img

    cv2.imwrite(str(page_img_file), page_img)
