from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from dataclasses_json import config, dataclass_json


@dataclass
class Gb688Block:
    x: int
    y: int
    img_x: int
    img_y: int


@dataclass
class Gb688Page:
    no: int
    img_id: str
    h: int
    w: int
    blocks: list[Gb688Block]


class StdStatus(Enum):
    ALL = ""
    PUBLISHED = "PUBLISHED"
    TOBEIMP = "TOBEIMP"
    WITHDRAWN = "WITHDRAWN"


class StdType(Enum):
    ALL = 0
    GB = 1
    GBT = 2
    GBZ = 3


@dataclass_json
@dataclass
class StdMeta:
    std_code: str
    is_ref: bool
    name_cn: str
    status: StdStatus = field(metadata=config(encoder=lambda x: x.value))
    pub_date: None | date = field(metadata=config(encoder=lambda x: x.isoformat() if x else None))
    impl_date: None | date = field(metadata=config(encoder=lambda x: x.isoformat() if x else None))


@dataclass
class StdMetaFull(StdMeta):
    name_en: str
    allow_preview: bool
    allow_download: bool
    ccs: str
    ics: str
    maintenance_depat: str
    centralized_depat: str
    pub_depat: str
    comment: str


@dataclass
class StdListItem(StdMeta):
    id: str


@dataclass_json
@dataclass
class StdSearchResult:
    items: list[StdListItem]
    total_item: int
    page: int
    total_page: int
