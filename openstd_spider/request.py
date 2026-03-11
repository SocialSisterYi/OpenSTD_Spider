import random
import time
from os import PathLike
from typing import Callable, Optional

import aiofiles
from httpx import AsyncClient

from openstd_spider.schema import StdSearchResult

from .exception import DownloadError
from .parse.gb688 import gb688_parse_page_sheet
from .parse.openstd import openstd_parse_meta, openstd_parse_search_result
from .schema import Gb688Page, StdMetaFull, StdStatus, StdType

BASE_URL_OPENSTD = "https://openstd.samr.gov.cn/bzgk/gb/"
BASE_URL_GB688 = "http://c.gb688.cn/bzgk/gb/"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0"


class OpenstdDto:
    def __init__(self):
        self._client = AsyncClient(
            headers={
                "User-Agent": UA,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            },
            base_url=BASE_URL_OPENSTD,
            follow_redirects=False,
        )

    async def get_std_meta(self, std_id: str) -> StdMetaFull:
        """获取标准元数据
        Args:
            std_id: 标准id
        Returns:
            StdMeta: 标准元数据
        """
        resp = await self._client.get(
            "/newGbInfo",
            params={
                "hcno": std_id,
            },
        )
        resp.raise_for_status()
        return openstd_parse_meta(resp.text)

    async def search(
        self,
        keyword: str = "",
        std_status: StdStatus = StdStatus.ALL,
        std_type: StdType = StdType.ALL,
        cate="",
        date="",
        ps: int = 10,
        pn: int = 1,
        order_by: str = "",
        order: str = "",
    ) -> StdSearchResult:
        """搜索标准文件列表
        Args:
            keyword: 关键字
            std_status: 标准状态
            std_type: 标准类型
            cate: 标准分类
            date: 标准日期
            ps: 每页项数
            pn: 页码
            order_by: 排序依据
            order: 排序
        Returns:
            StdSearchResult: 搜索结果
        """
        resp = await self._client.get(
            "/std_list",
            params={
                "r": random.random(),
                "page": pn,
                "pageSize": ps,
                "p.p1": std_type.value,
                "p.p2": keyword,
                "p.p5": std_status.value,
                "p.p6": cate,
                "p.p7": date,
                "p.p90": order_by,
                "p.p91": order,
            },
        )
        resp.raise_for_status()
        return openstd_parse_search_result(resp.text)


class Gb688Dto:
    def __init__(self):
        self._client = AsyncClient(
            headers={
                "User-Agent": UA,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            },
            base_url=BASE_URL_GB688,
            follow_redirects=False,
        )

    async def get_pages(self, std_id: str) -> list[Gb688Page]:
        """获取文档页
        Args:
            std_id: 标准id
        Returns:
            list[Gb688Page]: 页面结构数据
        """
        resp = await self._client.get(
            "/showGb",
            params={
                "type": "online",
                "hcno": std_id,
            },
            headers={
                "Referer": f"https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno={std_id}"
            },
        )
        resp.raise_for_status()
        pages = gb688_parse_page_sheet(resp.text)
        if len(pages) == 0:
            raise DownloadError
        return pages

    async def get_pageimg(self, img_id: str) -> bytes:
        """获取文档页
        Args:
            img_id: 图片资源id
        Returns:
            bytes: 预览图片数据
        """
        resp = await self._client.get(
            "/viewGbImg",
            params={
                "fileName": img_id,
            },
            headers={
                "Cache-Alive": "chunked",
            },
            follow_redirects=True,
        )
        resp.raise_for_status()
        return resp.content

    async def download_pdf(
        self,
        std_id: str,
        path: PathLike,
        cb: Optional[Callable[[int, int], None]] = None,
    ):
        """下载pdf文件
        Args:
          std_id: 标准id
          fp: 下载文件IO对象
          cb: 下载进度回调
        """
        async with self._client.stream(
            "GET",
            "/viewGb",
            params={
                "hcno": std_id,
            },
        ) as resp:
            resp.raise_for_status()
            total_size = int(resp.headers.get("Content-Length", 0))
            if (
                not resp.headers.get("Content-Disposition", "").endswith(".pdf")
                and total_size != 0
            ):
                # 文件不为pdf
                raise DownloadError
            async with aiofiles.open(path, "wb") as fp:
                size = 0
                async for chunck in resp.aiter_bytes(1024 * 100):
                    size += len(chunck)
                    await fp.write(chunck)
                    if cb:
                        cb(total_size, size)

    async def get_captcha(self) -> bytes:
        """获取人机验证码
        Returns:
            bytes: 验证码图片数据
        """
        resp = await self._client.get(f"/gc?_{int(time.time() * 1000)}")
        resp.raise_for_status()
        return resp.content

    async def submit_captcha(self, code: str) -> bool:
        """提交人机验证码
        Args:
            code: 验证码内容
        Returns:
            bool: 验证码是否正确
        """
        resp = await self._client.post(
            "/verifyCode",
            data={
                "verifyCode": code,
                "agreeIECTips": "true",
            },
        )
        resp.raise_for_status()
        return resp.text == "success"
