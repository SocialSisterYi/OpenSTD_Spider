import asyncio
from os import PathLike
from pathlib import Path
from typing import Callable, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from .parse.gb688 import Gb688Page


async def async_render_pdf_impl(
    page_infos: list[Gb688Page],
    base_dir: Path,
    pdf_path: PathLike,
    cb: Optional[Callable[[int], None]] = None,
):
    await asyncio.to_thread(render_pdf_impl, page_infos, base_dir, pdf_path, cb)


def render_pdf_impl(
    page_infos: list[Gb688Page],
    base_dir: Path,
    pdf_path: PathLike,
    cb: Optional[Callable[[int], None]] = None,
):
    """渲染为PDF"""
    page_cnt = len(page_infos)
    pdf = Canvas(str(pdf_path), pagesize=A4)
    page_w, page_h = A4

    for idx, page in enumerate(page_infos, 1):
        img_file = base_dir / f"P_{page.no}.png"
        img_reader = ImageReader(img_file)

        # 获取原始图片尺寸
        img_w, img_h = img_reader.getSize()

        scale_ratio = min(page_w / img_w, page_h / img_h)
        img_w = img_w * scale_ratio
        img_h = img_h * scale_ratio

        # 计算居中位置
        x_offset = (page_w - img_w) / 2
        y_offset = (page_h - img_h) / 2

        # 绘制图片到PDF
        pdf.drawImage(
            img_reader,
            x_offset,
            y_offset,
            width=img_w,
            height=img_h,
            preserveAspectRatio=True,
        )

        if idx < page_cnt:
            pdf.showPage()
        if cb:
            cb(idx)

    pdf.save()
