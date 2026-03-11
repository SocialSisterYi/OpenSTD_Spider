import re

from .schema import StdStatus, StdType

PATT_STD_ID_URL = re.compile(r"^(?:https://openstd\.samr\.gov\.cn/bzgk/gb/newGbInfo\?hcno=)?([0-9A-F]{32})")

PATT_STD_CODE = re.compile(r"^GB(/[TZ])? \S+", re.I)


def parse_std_id(text: str) -> str | None:
    match = PATT_STD_ID_URL.search(text)
    if match is not None:
        return match.group(1)
    return None


def is_std_code(text: str) -> bool:
    return PATT_STD_CODE.search(text) is not None


def std_status2name(std_status: StdStatus) -> str | None:
    match std_status:
        case StdStatus.PUBLISHED:
            return "现行"
        case StdStatus.TOBEIMP:
            return "即将实施"
        case StdStatus.WITHDRAWN:
            return "废止"
        case _:
            return None


def name2std_status(name: str) -> StdStatus | None:
    match name:
        case "现行":
            return StdStatus.PUBLISHED
        case "即将实施":
            return StdStatus.TOBEIMP
        case "废止":
            return StdStatus.WITHDRAWN
        case _:
            return None


def name2std_type(name: str) -> StdType | None:
    match name:
        case "GB":
            return StdType.GB
        case "GBT":
            return StdType.GBT
        case "GBZ":
            return StdType.GBZ
        case _:
            return None
