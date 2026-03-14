import asyncio
import inspect
import sys
from enum import Enum
from functools import partial, wraps
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.box import SQUARE
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, DownloadColumn, Progress, TaskProgressColumn, TextColumn, TimeRemainingColumn
from rich.styled import Styled
from rich.table import Table
from typer import Argument, Option, Typer

from openstd_spider import (
    Gb688Dto,
    HandleCaptchaError,
    NotFoundError,
    OpenstdDto,
    StdListItem,
    StdMetaFull,
    StdSearchResult,
    StdStatus,
    StdType,
    __version__,
    download_preview_img_impl,
    fuck_captcha_impl,
    reorganize_page_impl,
)
from openstd_spider.parse.gb688 import gb688_uniq_imgid
from openstd_spider.pdf import async_render_pdf_impl
from openstd_spider.utils import is_std_code, name2std_type, parse_std_id, std_status2name


class AsyncTyper(Typer):
    @staticmethod
    def maybe_run_async(decorator, f):
        if inspect.iscoroutinefunction(f):

            @wraps(f)
            def runner(*args, **kwargs):
                return asyncio.run(f(*args, **kwargs))

            decorator(runner)
        else:
            decorator(f)
        return f

    def callback(self, *args, **kwargs):
        decorator = super().callback(*args, **kwargs)
        return partial(self.maybe_run_async, decorator)

    def command(self, *args, **kwargs):
        decorator = super().command(*args, **kwargs)
        return partial(self.maybe_run_async, decorator)


console = Console(highlight=False)

app = AsyncTyper(
    name="OpenSTD Spider",
    help=f"国家标准全文公开系统下载工具  Version: {__version__}",
    add_completion=False,
    pretty_exceptions_show_locals=False,
    no_args_is_help=True,
)
openstd_dto = OpenstdDto()
gb688_dto = Gb688Dto()


async def search_one(keyword: str) -> StdListItem:
    "搜索精确标准编号信息"
    result = await openstd_dto.search(
        keyword=keyword,
    )
    item_cnt = len(result.items)
    if item_cnt == 1:
        return result.items[0]
    elif item_cnt > 1:
        console.print("❌[red]查询到多条结果, 请输入完整的标准编号")
        sys.exit(-1)
    else:
        console.print("❌[red]未查询到对应标准编号的内容")
        sys.exit(-1)


async def url_or_code2std_id(target: str) -> str:
    "通过url或精确标准编号得到标准id"
    target = target.strip()
    if is_std_code(target):
        result = await search_one(target)
        std_id = result.id
    else:
        std_id = parse_std_id(target)
        if std_id is None:
            console.print(f"❌[red]目标资源id错误")
            sys.exit(-1)
    return std_id


def std_status_colored(status: StdStatus):
    "标准状态颜色显示"
    match status:
        case StdStatus.PUBLISHED:
            color = "green"
        case StdStatus.TOBEIMP:
            color = "yellow"
        case StdStatus.WITHDRAWN | StdStatus.NOTIMP:
            color = "red"
    return Styled(std_status2name(status), color)


def show_std_list(result: StdSearchResult):
    "输出标准搜索列表"
    tb = Table("序号", "标准编号", "标准名", "状态", "发布日期", "实施日期")
    tb.columns[2].overflow = "fold"
    for idx, item in enumerate(result.items):
        tb.add_row(
            str(idx),
            Styled(item.std_code, "bold green"),
            item.name_cn,
            std_status_colored(item.status),
            item.pub_date.strftime("%Y-%m-%d") if item.pub_date else "无",
            item.impl_date.strftime("%Y-%m-%d") if item.impl_date else "无",
        )
    console.print(tb)
    console.print(f"[bold green]{result.page}/{result.total_page}[/]页 共[bold green]{result.total_item}[/]条")


def show_std_meta(meta: StdMetaFull, detail: bool = True):
    "输出标准详细信息"
    if detail:
        grid = Table(show_header=False, show_edge=False, padding=0)
        panel = Panel(
            grid,
            title=f"[red]标准号: {meta.std_code}" + ("  [bold yellow]采" if meta.is_ref else ""),
            box=SQUARE,
            title_align="left",
            border_style="blue",
            expand=False,
            width=100,
        )

        tb1 = Table(show_header=False, show_edge=False, padding=0, box=None)
        tb1.add_row("中文标准名称: ", meta.name_cn)
        tb1.add_row("英文标准名称: ", meta.name_en)
        tb1.add_row("标准状态: ", std_status_colored(meta.status))
        tb1.columns[1].overflow = "fold"
        grid.add_row(tb1)

        grid.add_section()
        grid.add_row(
            (
                ("[bold green]允许" if meta.allow_preview else "[bold red]禁止")
                + "预览[/]"
                + " "
                + ("[bold green]允许" if meta.allow_download else "[bold red]禁止")
                + "下载[/]"
            )
        )
        grid.add_section()

        tb2 = Table(show_header=False, show_edge=False, padding=0)
        tb2.add_row("[bold white]中国标准分类号（CCS）", meta.ccs)
        tb2.add_row("[bold white]国际标准分类号（ICS）", meta.ics)
        tb2.add_row(
            "[bold white]发布日期",
            meta.pub_date.strftime("%Y-%m-%d") if meta.pub_date else "无",
        )
        tb2.add_row(
            "[bold white]实施日期",
            meta.impl_date.strftime("%Y-%m-%d") if meta.impl_date else "无",
        )
        tb2.add_row("[bold white]主管部门", meta.maintenance_depat)
        tb2.add_row("[bold white]归口部门", meta.centralized_depat)
        tb2.add_row("[bold white]发布单位", meta.pub_depat)
        tb2.add_row("[bold white]备注", meta.comment)
        tb2.columns[1].overflow = "fold"
        grid.add_row(tb2)

        console.print(panel)
    else:
        console.print(f"[bold green]标准编号:[/] {meta.std_code}")
        console.print(f"[bold green]中文名称:[/] {meta.name_cn}")
        console.print(f"[bold green]英文名称:[/] {meta.name_en}")


async def download_preview(std_id: str, download_path: Path):
    "预览页面方式下载"
    page_infos = await gb688_dto.get_pages(std_id)
    img_ids = gb688_uniq_imgid(page_infos)
    page_cnt = len(page_infos)
    img_cnt = len(img_ids)

    with (
        TemporaryDirectory(prefix="openstdspider") as tmp_dir,
        Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn("[progress.percentage]{task.percentage:>3.0f}%[/] {task.completed}/{task.total}"),
            TimeRemainingColumn(),
            console=console,
        ) as progress,
    ):
        tmp_dir = Path(tmp_dir)

        bar1 = progress.add_task("缓存预览图", total=img_cnt)
        await download_preview_img_impl(
            gb688_dto,
            tmp_dir,
            img_ids,
            lambda cnt: progress.update(bar1, completed=cnt),
        )
        progress.remove_task(bar1)
        console.print(f"[green]✔ [bold green]预览图缓存完毕")

        bar2 = progress.add_task("重建页面", total=page_cnt)
        await reorganize_page_impl(
            page_infos,
            tmp_dir,
            lambda cnt: progress.update(bar2, completed=cnt),
        )
        progress.remove_task(bar2)
        console.print(f"[green]✔ [bold green]页面重建完毕")

        bar3 = progress.add_task("生成PDF", total=page_cnt)
        await async_render_pdf_impl(
            page_infos,
            tmp_dir,
            download_path,
            lambda cnt: progress.update(bar3, completed=cnt),
        )
        progress.remove_task(bar3)
        console.print(f"[green]✔ [bold green]pdf生成完毕")


async def download_file(std_id: str, download_path: Path):
    "文件方式下载"
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(binary_units=True),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        bar = progress.add_task("下载PDF")
        await gb688_dto.download_pdf(
            std_id,
            download_path,
            lambda total_size, size: progress.update(bar, total=total_size, completed=size),
        )
        progress.remove_task(bar)


class StdStatusSelect(Enum):
    PUBLISHED = "现行"
    TOBEIMP = "即将实施"
    WITHDRAWN = "废止"


class StdTypeSelect(Enum):
    GB = "GB"
    GBT = "GBT"
    GBZ = "GBZ"


@app.command(name="search")
async def search(
    ps: int = Option(10, "--ps", show_default=False, help="每页条数", min=10, max=50),
    pn: int = Option(1, "-p", "--pn", show_default=False, help="页码", min=1),
    std_status: StdStatusSelect | None = Option(None, "-s", "--status", show_default=False, help="标准状态"),
    std_type: StdTypeSelect | None = Option(None, "-t", "--type", show_default=False, help="标准类型"),
    json_output: bool = Option(False, "-j", "--json", help="json格式输出"),
    keyword: str = Argument("", help="关键字"),
):
    "搜索 浏览标准文件列表"
    result = await openstd_dto.search(
        keyword=keyword,
        std_type=StdType(name2std_type(std_type.name)) if std_type else StdType.ALL,
        std_status=StdStatus(std_status.name) if std_status else StdStatus.ALL,
        ps=ps,
        pn=pn,
    )
    if json_output:
        sys.stdout.write(result.to_json(ensure_ascii=False, separators=(",", ":")))
    else:
        show_std_list(result)


@app.command(name="info")
async def meta_info(
    json_output: bool = Option(False, "-j", "--json", help="json格式输出"),
    target: str = Argument(help="标准编号或url", show_default=False),
):
    "查询标准文件元数据"
    std_id = await url_or_code2std_id(target)
    try:
        meta = await openstd_dto.get_std_meta(std_id)
    except NotFoundError:
        console.print(f"❌[red]目标资源id不存在")
        sys.exit(-1)
    if json_output:
        sys.stdout.write(meta.to_json(ensure_ascii=False, separators=(",", ":")))
    else:
        show_std_meta(meta, detail=True)


@app.command(name="download")
async def download(
    detail: bool = Option(False, "-d", "--detail", help="是否展示详细元数据"),
    force_preview: bool = Option(False, "--preview", help="强制下载预览版本"),
    download_path: Path | None = Option(
        None, "-o", "--output", show_default=False, writable=True, help="下载路径或文件"
    ),
    target: str = Argument(help="标准编号或url", show_default=False),
):
    "下载标准文件PDF"
    if download_path is None:
        download_path = Path(".")

    std_id = await url_or_code2std_id(target)
    try:
        meta = await openstd_dto.get_std_meta(std_id)
    except NotFoundError:
        console.print(f"❌[bold red]目标资源id不存在")
        sys.exit(-1)

    show_std_meta(meta, detail=detail)
    console.print("[green]" + "─" * 30)

    if meta.allow_download or meta.allow_preview:
        try:
            await fuck_captcha_impl(gb688_dto)
        except HandleCaptchaError:
            console.print(f"[red]× [bold red]验证码识别失败")
            sys.exit(-1)
        console.print(f"[green]✔ [bold green]验证码识别成功")
    else:
        console.print(f"[red]× [bold red]资源不允许下载")
        sys.exit(-1)

    # 添加文件名
    if download_path.is_dir():
        download_path /= meta.std_code.replace("/", "") + ".pdf"

    if meta.allow_download and not force_preview:
        # 文件下载
        await download_file(std_id, download_path)
    elif meta.allow_preview:
        # 预览下载
        console.print(f"[yellow]! [bold yellow]不允许直接下载, 进行预览方式合并重组下载")
        await download_preview(std_id, download_path)

    console.print(f"[green]✔ [bold green]下载完成")
