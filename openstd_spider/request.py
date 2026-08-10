import asyncio
import random
import time
from os import PathLike, unlink
from typing import Callable, Optional

import aiofiles
from httpx import AsyncClient, HTTPStatusError, Timeout, TransportError

from openstd_spider.schema import StdSearchResult

from .exception import DownloadError
from .parse.gb688 import gb688_parse_page_sheet
from .parse.openstd import openstd_parse_meta, openstd_parse_search_result
from .schema import Gb688Page, StdMetaFull, StdStatus, StdType

BASE_URL_OPENSTD = "https://openstd.samr.gov.cn/bzgk/std/"
# 注：预览/下载服务已从 c.gb688.cn 整体迁移回主站 openstd.samr.gov.cn（c.gb688.cn 已废弃，返回 502）
BASE_URL_GB688 = "https://openstd.samr.gov.cn/bzgk/std/"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36 Edg/150.0.0.0"


class OpenstdDto:
    def __init__(self):
        self._client = AsyncClient(
            headers={
                "User-Agent": UA,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            },
            base_url=BASE_URL_OPENSTD,
            follow_redirects=True,
            timeout=Timeout(
                connect=30.0,  # 增加连接超时
                read=120.0,
                write=30.0,
                pool=10.0
            ),
        )

    async def _request(self, url: str, params: dict):
        # 带网络重试的 GET：政府站点偶发断连(RemoteProtocolError/超时),最多重试 3 次
        for attempt in range(3):
            try:
                resp = await self._client.get(url, params=params)
                resp.raise_for_status()
                return resp
            except HTTPStatusError:
                # 4xx/5xx 是业务错误,不重试,直接抛出
                raise
            except TransportError:
                if attempt == 2:
                    raise
                await asyncio.sleep(1.0 * (attempt + 1))

    async def get_std_meta(self, std_id: str) -> StdMetaFull:
        """获取标准元数据
        Args:
            std_id: 标准id
        Returns:
            StdMeta: 标准元数据
        """
        resp = await self._request(
            "/newGbInfo",
            params={
                "hcno": std_id,
            },
        )
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
        resp = await self._request(
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
        return openstd_parse_search_result(resp.text)


class Gb688Dto:
    def __init__(self):
        self._client = AsyncClient(
            headers={
                "User-Agent": UA,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            },
            base_url=BASE_URL_GB688,
            follow_redirects=True,
            timeout=Timeout(connect=15.0, read=120.0, write=30.0, pool=10.0),
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
                "Referer": f"https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno={std_id}",
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

    async def prepare_download(self, std_id: str) -> None:
        """访问下载中转页,在当前 session 中种下下载所需的 token。

        网站的下载链路为:中转页(showGb?type=download) -> 验证码 -> viewGb。
        必须先打开中转页,再提交验证码,viewGb 才会返回真正的 PDF;
        否则 viewGb 只会返回空响应。因此该方法需在过验证码之前调用。
        """
        resp = await self._client.get(
            "/showGb",
            params={
                "type": "download",
                "hcno": std_id,
                "request_locale": "zh",
            },
            headers={
                "Referer": f"https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno={std_id}",
            },
        )
        resp.raise_for_status()

    async def download_pdf(
        self,
        std_id: str,
        path: PathLike,
        cb: Optional[Callable[[int, int], None]] = None,
    ):
        """下载pdf文件
        Args:
          std_id: 标准id
          path: 下载文件路径
          cb: 下载进度回调
        """
        # 真正返回 PDF 的是 viewGb;showGb?type=download 只是中转页(返回 HTML)。
        # 前置条件:当前 session 已依次通过 prepare_download(中转页 token)与验证码授权。
        async with self._client.stream(
            "GET",
            "/viewGb",
            params={
                "hcno": std_id,
            },
            headers={
                "Referer": f"https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno={std_id}",
            },
        ) as resp:
            resp.raise_for_status()
            total_size = int(resp.headers.get("Content-Length", 0))
            if not resp.headers.get("Content-Disposition", "").endswith(".pdf") and total_size != 0:
                # 文件不为pdf
                raise DownloadError
            async with aiofiles.open(path, "wb") as fp:
                size = 0
                async for chunck in resp.aiter_bytes(1024 * 100):
                    size += len(chunck)
                    await fp.write(chunck)
                    if cb:
                        cb(total_size, size)
        if size == 0:
            # 服务器返回空内容（如未通过验证码授权,或"即将实施"标准尚未公开 PDF）,避免生成 0 字节文件假装成功
            unlink(path)
            raise DownloadError

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
