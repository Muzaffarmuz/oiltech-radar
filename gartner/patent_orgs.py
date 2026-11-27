"""Извлечение и нормализация организаций из патентов Роспатента.

Без города.
«Домен/поддомен» в продукте = кластер / подкластер (coarse / fine направления).
Здесь: уникальные org + классификатор + максимально богатый набор ключей/алиасов.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from gartner.config import ROOT
from gartner.science_analytics import SCIENCE_CENTERS
from gartner.science_directions import COARSE_DIRECTIONS, FINE_DIRECTIONS, fine_to_coarse, normalize_fine

# Обязательные научные центры (даже если слабо встречаются в текущем срезе патентов)
SEED_ORGS: list[dict[str, Any]] = [
    {
        "canonical_name": "ТатНИПИнефть",
        "org_type": "nii",
        "aliases": (
            "татнипинефть",
            "тат нипи нефть",
            "tatnipineft",
            "институт татнипинефть",
            "татанефть нипи",
            "татнииинефть",
            "нии пи нефть",
            "татнефть нипи",
        ),
    },
    {
        "canonical_name": "Высшая школа нефти (Альметьевск)",
        "org_type": "university",
        "aliases": (
            "высшая школа нефти",
            "вшн альметьевск",
            "вшн",
            "агту вшн",
            "альметьевский государственный технологический университет",
            "альметьевский государственный нефтяной институт",
            "альметьевский государственный нефтяной",
            "гбоу во агту вшн",
            "higher school of petroleum",
            "agtu vshn",
        ),
    },
]

# Расширенный классификатор: всевозможные написания компаний / вузов / НИИ / иностранцев.
# Цель — склеить варианты в один canonical; список потом разберёте вручную.
EXTRA_ORG_ALIASES: list[dict[str, Any]] = [
    # --- операторы РФ ---
    {
        "canonical_name": "Татнефть",
        "org_type": "company",
        "aliases": (
            "татнефть",
            "пао татнефть",
            "публичное акционерное общество татнефть",
            "татнефть им. в.д. шашина",
            "татнефть имени в.д. шашина",
            "tatneft",
            "pjsc tatneft",
        ),
    },
    {
        "canonical_name": "Газпром",
        "org_type": "company",
        "aliases": ("газпром", "пао газпром", "pjsc gazprom", "gazprom"),
    },
    {
        "canonical_name": "Газпром нефть",
        "org_type": "company",
        "aliases": (
            "газпром нефть",
            "газпромнефть",
            "пао газпром нефть",
            "gazprom neft",
            "gazpromneft",
        ),
    },
    {
        "canonical_name": "Роснефть",
        "org_type": "company",
        "aliases": (
            "роснефть",
            "нк роснефть",
            "пао нк роснефть",
            "rosneft",
            "pjsc rosneft",
        ),
    },
    {
        "canonical_name": "Лукойл",
        "org_type": "company",
        "aliases": ("лукойл", "пао лукойл", "lukoil", "pjsc lukoil"),
    },
    {
        "canonical_name": "Сургутнефтегаз",
        "org_type": "company",
        "aliases": ("сургутнефтегаз", "пао сургутнефтегаз", "surgutneftegas"),
    },
    {
        "canonical_name": "НОВАТЭК",
        "org_type": "company",
        "aliases": ("новатэк", "пао новатэк", "novatek"),
    },
    {
        "canonical_name": "СИБУР",
        "org_type": "company",
        "aliases": ("сибур", "сибур холдинг", "пао сибур", "sibur"),
    },
    {
        "canonical_name": "Зарубежнефть",
        "org_type": "company",
        "aliases": ("зарубежнефть", "ао зарубежнефть"),
    },
    {
        "canonical_name": "Иркутская нефтяная компания",
        "org_type": "company",
        "aliases": ("иркутская нефтяная компания", "инк", "ооо инк", "irkutsk oil"),
    },
    {
        "canonical_name": "ТАИФ",
        "org_type": "company",
        "aliases": ("таиф", "группа таиф", "ао таиф", "taif"),
    },
    {
        "canonical_name": "ТАНЕКО",
        "org_type": "subsidiary",
        "aliases": ("танеко", "ао танеко", "taneco"),
    },
    {
        "canonical_name": "Славнефть-ЯНОС",
        "org_type": "company",
        "aliases": (
            "славнефть-ярославнефтеоргсинтез",
            "славнефть-янос",
            "янос",
            "slavneft-yanos",
        ),
    },
    # --- дочки Газпрома / Роснефти (отдельные canonical — удобнее фильтровать) ---
    {
        "canonical_name": "Газпром добыча Ямбург",
        "org_type": "subsidiary",
        "aliases": ("газпром добыча ямбург", "ооо газпром добыча ямбург"),
    },
    {
        "canonical_name": "Газпром добыча Уренгой",
        "org_type": "subsidiary",
        "aliases": ("газпром добыча уренгой", "ооо газпром добыча уренгой"),
    },
    {
        "canonical_name": "Газпром добыча Оренбург",
        "org_type": "subsidiary",
        "aliases": ("газпром добыча оренбург",),
    },
    {
        "canonical_name": "Газпром трансгаз Ухта",
        "org_type": "subsidiary",
        "aliases": ("газпром трансгаз ухта", "ооо газпром трансгаз ухта"),
    },
    {
        "canonical_name": "Газпром трансгаз Уфа",
        "org_type": "subsidiary",
        "aliases": ("газпром трансгаз уфа", "газпром трансгаз уфа"),
    },
    {
        "canonical_name": "Газпром трансгаз Нижний Новгород",
        "org_type": "subsidiary",
        "aliases": ("газпром трансгаз нижний новгород",),
    },
    {
        "canonical_name": "Газпром трансгаз Томск",
        "org_type": "subsidiary",
        "aliases": ("газпром трансгаз томск",),
    },
    {
        "canonical_name": "ВНИИГАЗ",
        "org_type": "nii",
        "aliases": (
            "вниигаз",
            "газпром вниигаз",
            "научно-исследовательский институт природных газов и газовых технологий",
            "институт природных газов и газовых технологий",
            "gazprom vniigaz",
            "llc gazprom vniigaz",
        ),
    },
    {
        "canonical_name": "РН-Пурнефтегаз",
        "org_type": "subsidiary",
        "aliases": ("рн-пурнефтегаз", "ооо рн-пурнефтегаз"),
    },
    {
        "canonical_name": "Татнефть-Самара",
        "org_type": "subsidiary",
        "aliases": ("татнефть-самара", "ооо татнефть-самара"),
    },
    # --- сервис / оборудование ---
    {
        "canonical_name": "Шлюмберже",
        "org_type": "foreign",
        "aliases": (
            "шлюмбергер",
            "шлюмберже",
            "schlumberger",
            "шлюмбергер текнолоджи",
            "шлюмбергер текнолоджи б.в",
            "schlumberger technology",
        ),
    },
    {
        "canonical_name": "Halliburton",
        "org_type": "foreign",
        "aliases": ("halliburton", "халлибертон", "халлибуртон"),
    },
    {
        "canonical_name": "Baker Hughes",
        "org_type": "foreign",
        "aliases": ("baker hughes", "бейкер хьюз", "бекер хьюз"),
    },
    {
        "canonical_name": "Weatherford",
        "org_type": "foreign",
        "aliases": ("weatherford", "везерфорд", "уэзерфорд"),
    },
    {
        "canonical_name": "БУРИНТЕХ",
        "org_type": "company",
        "aliases": ("буринтех", "ооо буринтех", "burintekh"),
    },
    {
        "canonical_name": "Пакер",
        "org_type": "company",
        "aliases": ("пакер", "ооо пакер", "нпп пакер"),
    },
    {
        "canonical_name": "ПЕГАЗ",
        "org_type": "nii",
        "aliases": ("пегаз", "нпп пегаз", "ооо пегаз"),
    },
    {
        "canonical_name": "ГТИ",
        "org_type": "company",
        "aliases": ("гти", "геолого-технологические исследования", "ооо гти"),
    },
    {
        "canonical_name": "ТНГ-АлГИС",
        "org_type": "company",
        "aliases": ("тнг-алгис", "тнг алгис", "ооо тнг-алгис"),
    },
    {
        "canonical_name": "КИРИЛЛИЦА",
        "org_type": "company",
        "aliases": ("кириллица", "ооо кириллица"),
    },
    {
        "canonical_name": "Gaztransport & Technigaz",
        "org_type": "foreign",
        "aliases": (
            "газтранспорт эт технигаз",
            "gaztransport",
            "technigaz",
            "gtt",
            "газтранспорт",
        ),
    },
    {
        "canonical_name": "Sinopec",
        "org_type": "foreign",
        "aliases": (
            "чайна петролеум энд кемикал корпорейшн",
            "china petroleum",
            "sinopec",
            "чайна петролеум",
        ),
    },
    {
        "canonical_name": "IFP Energies nouvelles",
        "org_type": "foreign",
        "aliases": (
            "ифп энержи нувелль",
            "ifp energies",
            "ifp energie",
            "ифп",
        ),
    },
    {
        "canonical_name": "Innospec",
        "org_type": "foreign",
        "aliases": ("инноспек", "innospec", "инноспек лимитед"),
    },
    {
        "canonical_name": "Topsoe",
        "org_type": "foreign",
        "aliases": ("топсёэ", "топсе", "topsoe", "haldor topsoe"),
    },
    {
        "canonical_name": "JFE Steel",
        "org_type": "foreign",
        "aliases": ("джфе стил", "jfe steel", "джфе стил корпорейшн"),
    },
    # --- вузы / НИИ (склейка с SCIENCE_CENTERS и частыми написаниями Роспатента) ---
    {
        "canonical_name": "РГУ нефти и газа им. Губкина",
        "org_type": "university",
        "aliases": (
            "губкин",
            "ргу нефти и газа",
            "российский государственный университет нефти и газа",
            "gubkin",
        ),
    },
    {
        "canonical_name": "Санкт-Петербургский горный университет",
        "org_type": "university",
        "aliases": (
            "санкт-петербургский горный университет",
            "горный университет императрицы екатерины",
            "петербургский горный",
            "спггу",
            "spmi",
        ),
    },
    {
        "canonical_name": "Казанский федеральный университет",
        "org_type": "university",
        "aliases": (
            "казанский (приволжский) федеральный университет",
            "казанский федеральный университет",
            "кфу",
            "kfu",
        ),
    },
    {
        "canonical_name": "УГНТУ",
        "org_type": "university",
        "aliases": (
            "уфимский государственный нефтяной технический университет",
            "угнту",
            "уфимский нефтяной",
        ),
    },
    {
        "canonical_name": "Томский политехнический университет",
        "org_type": "university",
        "aliases": (
            "томский политехнический",
            "национальный исследовательский томский политехнический университет",
            "тпу",
            "tpu",
        ),
    },
    {
        "canonical_name": "КубГТУ",
        "org_type": "university",
        "aliases": (
            "кубанский государственный технологический университет",
            "кубгту",
            "kubstu",
        ),
    },
    {
        "canonical_name": "ПНИПУ",
        "org_type": "university",
        "aliases": (
            "пермский национальный исследовательский политехнический университет",
            "пнипу",
            "пермский политех",
        ),
    },
    {
        "canonical_name": "СФУ",
        "org_type": "university",
        "aliases": ("сибирский федеральный университет", "сфу", "sfu"),
    },
    {
        "canonical_name": "СГТУ им. Гагарина",
        "org_type": "university",
        "aliases": (
            "саратовский государственный технический университет",
            "сгту имени гагарина",
            "сгту им. гагарина",
        ),
    },
    {
        "canonical_name": "УУНиТ",
        "org_type": "university",
        "aliases": ("уфимский университет науки и технологий", "уунит"),
    },
    {
        "canonical_name": "РУДН",
        "org_type": "university",
        "aliases": (
            "российский университет дружбы народов",
            "рудн",
            "университет дружбы народов имени патриса лумумбы",
        ),
    },
    {
        "canonical_name": "Институт геофизики УрО РАН",
        "org_type": "nii",
        "aliases": (
            "институт геофизики им. ю.п. булашевича",
            "институт геофизики уральского отделения",
            "булашевича",
        ),
    },
    {
        "canonical_name": "Институт нефтегазовых технологий",
        "org_type": "nii",
        "aliases": ("институт нефтегазовых технологий",),
    },
]

_LEGAL_PREFIXES = (
    r"федеральное\s+государственное\s+бюджетное\s+образовательное\s+учреждение\s+высшего\s+образования",
    r"федеральное\s+государственное\s+автономное\s+образовательное\s+учреждение\s+высшего\s+образования",
    r"государственное\s+бюджетное\s+образовательное\s+учреждение\s+высшего\s+образования",
    r"государственное\s+бюджетное\s+учреждение",
    r"государственное\s+автономное\s+учреждение",
    r"муниципальное\s+бюджетное\s+учреждение",
    r"муниципальное\s+автономное\s+учреждение",
    r"федеральное\s+автономное\s+учреждение",
    r"федеральное\s+государственное\s+бюджетное\s+учреждение\s+науки",
    r"федеральное\s+государственное\s+бюджетное\s+учреждение",
    r"федеральное\s+государственное\s+унитарное\s+предприятие",
    r"публичное\s+акционерное\s+общество",
    r"акционерное\s+общество",
    r"общество\s+с\s+ограниченной\s+ответственностью",
    r"закрытое\s+акционерное\s+общество",
    r"открытое\s+акционерное\s+общество",
    r"индивидуальный\s+предприниматель",
    r"научно-производственное\s+предприятие",
    r"научно-производственное\s+объединение",
    r"научно-исследовательский\s+институт",
    r"фгбоу\s+во",
    r"фгаоу\s+во",
    r"гбоу\s+во",
    r"фгбун",
    r"фгбу",
    r"фгуп",
    r"фгау",
    r"гбу",
    r"гау",
    r"мбу",
    r"мау",
    r"пао",
    r"оао",
    r"зао",
    r"ао",
    r"ооо",
    r"нпо",
    r"нпп",
    r"нии",
    r"нпц",
    r"нтц",
)

# Длинные юрформы → общепринятые сокращения (для отображения; длинные первыми)
_LEGAL_ABBREV_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"федеральн\w*\s+государственн\w*\s+бюджетн\w*\s+образовательн\w*\s+учреждени\w*\s+высшего\s+образовани\w*",
            re.I,
        ),
        "ФГБОУ ВО",
    ),
    (
        re.compile(
            r"федеральн\w*\s+государственн\w*\s+автономн\w*\s+образовательн\w*\s+учреждени\w*\s+высшего\s+образовани\w*",
            re.I,
        ),
        "ФГАОУ ВО",
    ),
    (
        re.compile(
            r"государственн\w*\s+бюджетн\w*\s+образовательн\w*\s+учреждени\w*\s+высшего\s+образовани\w*",
            re.I,
        ),
        "ГБОУ ВО",
    ),
    (re.compile(r"федеральн\w*\s+государственн\w*\s+бюджетн\w*\s+учреждени\w*\s+науки", re.I), "ФГБУН"),
    (re.compile(r"государственн\w*\s+бюджетн\w*\s+учреждени\w*\s+науки", re.I), "ГБУН"),
    (re.compile(r"федеральн\w*\s+государственн\w*\s+бюджетн\w*\s+учреждени\w*", re.I), "ФГБУ"),
    (re.compile(r"федеральн\w*\s+государственн\w*\s+унитарн\w*\s+предприяти\w*", re.I), "ФГУП"),
    (re.compile(r"федеральн\w*\s+автономн\w*\s+учреждени\w*", re.I), "ФГАУ"),
    (re.compile(r"государственн\w*\s+бюджетн\w*\s+учреждени\w*", re.I), "ГБУ"),
    (re.compile(r"государственн\w*\s+автономн\w*\s+учреждени\w*", re.I), "ГАУ"),
    (re.compile(r"муниципальн\w*\s+бюджетн\w*\s+учреждени\w*", re.I), "МБУ"),
    (re.compile(r"муниципальн\w*\s+автономн\w*\s+учреждени\w*", re.I), "МАУ"),
    (re.compile(r"публичн\w*\s+акционерн\w*\s+обществ\w*", re.I), "ПАО"),
    (re.compile(r"открыт\w*\s+акционерн\w*\s+обществ\w*", re.I), "ОАО"),
    (re.compile(r"закрыт\w*\s+акционерн\w*\s+обществ\w*", re.I), "ЗАО"),
    (re.compile(r"акционерн\w*\s+обществ\w*", re.I), "АО"),
    (re.compile(r"обществ\w*\s+с\s+ограниченн\w*\s+ответственност\w*", re.I), "ООО"),
    (re.compile(r"индивидуальн\w*\s+предпринимател\w*", re.I), "ИП"),
    (re.compile(r"научно-?\s*производственн\w*\s+объединени\w*", re.I), "НПО"),
    (re.compile(r"научно-?\s*производственн\w*\s+предприяти\w*", re.I), "НПП"),
    (re.compile(r"научно-?\s*техническ\w*\s+центр\w*", re.I), "НТЦ"),
    (re.compile(r"научно-?\s*исследовательск\w*\s+институт\w*", re.I), "НИИ"),
    (re.compile(r"\bко\.\s*,?\s*лтд\b", re.I), "Co., Ltd"),
    (re.compile(r"\bcompany\s+limited\b", re.I), "Co., Ltd"),
    (re.compile(r"\blimited\b", re.I), "Ltd"),
    (re.compile(r"\bлимитед\b", re.I), "Ltd"),
]

_KEEP_UPPER = {
    "гбу",
    "гау",
    "мбу",
    "мау",
    "фгбу",
    "фгбун",
    "фгуп",
    "фгау",
    "фгбоу",
    "фгаоу",
    "гбоу",
    "гбун",
    "пао",
    "оао",
    "зао",
    "ао",
    "ооо",
    "ип",
    "нпо",
    "нпп",
    "нии",
    "нпц",
    "нтц",
    "ран",
    "со",
    "уро",
    "дво",
    "во",
    "llc",
    "inc",
    "gmbh",
    "sa",
    "bv",
    "as",
    "pjsc",
    "jsc",
}

_SMALL_WORDS = {
    "и",
    "в",
    "во",
    "на",
    "с",
    "со",
    "по",
    "к",
    "о",
    "об",
    "от",
    "для",
    "им",
    "имени",
    "and",
    "of",
    "the",
    "for",
}

_COUNTRY_RE = re.compile(r"\((?:RU|CN|US|DE|FR|JP|KR|GB|EP|WO|UA|BY|KZ|NL|DK|CH|IT|NO|SE|FI|BE|AT|CA|AU|SG|SA|AE|IN)\)\s*$", re.I)
_SPLIT_RE = re.compile(r"\s*;\s*|\s*\|\s*|\n+")
_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[«»\"“”„′'`]")
_NON_ALNUM_RE = re.compile(r"[^a-zа-я0-9]+", re.I)
_PERSON_RE = re.compile(
    r"^[А-ЯЁA-Z][а-яёa-z\-]+(?:\s+[А-ЯЁA-Z][а-яёa-z\-]+){1,3}$"
)
_REDACTED_RE = re.compile(r"не\s+публикуется", re.I)

_ORG_MARKERS = (
    "университет",
    "институт",
    "академи",
    "научн",
    "исследовател",
    "лаборатор",
    "центр",
    "общество",
    "компани",
    "холдинг",
    "завод",
    "фабрик",
    "корпорац",
    "концерн",
    "товариществ",
    "предприяти",
    "limited",
    "ltd",
    "llc",
    "inc",
    "corp",
    "gmbh",
    "s.a",
    "co.",
    "фгбоу",
    "фгаоу",
    "фгуп",
    "пао",
    "ооо",
    "ао ",
    "нии",
    "внии",
    "нпо",
    "нпц",
    "нпп",
)

_UNI_MARKERS = ("университет", "институт.*образован", "высш.*школ", "политех", "фгбоу", "фгаоу", "гбоу")
_FOREIGN_MARKERS = ("ltd", "limited", "llc", "inc", "corp", "gmbh", "s.a", "co.,", "компания", "ко.,", "б.в", "a/s", "а/с")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.lower().replace("ё", "е")
    text = _PUNCT_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def _soft_spell(text: str) -> str:
    """Мягкая унификация транслита/опечаток для склейки дублей."""
    t = _fold(text)
    # иум/еум (петролиум → петролеум), инститьют → институт
    t = re.sub(r"иум\b", "еум", t)
    t = t.replace("инститьют", "институт")
    t = t.replace("технолоджи", "текнолоджи")
    t = t.replace("инжиниринг", "инжиниринг")
    t = re.sub(r"\bко\.\s*,?\s*лтд\b", "колтд", t)
    t = re.sub(r"\bco\.\s*,?\s*ltd\b", "колтд", t)
    return _SPACE_RE.sub(" ", t).strip()


def org_merge_key(name: str) -> str:
    """Ключ склейки: ё=е, мягкий транслит, без пунктуации."""
    return _NON_ALNUM_RE.sub("", _soft_spell(_strip_legal(name)))


def _looks_all_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 4:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) >= 0.85


def _title_token(token: str, *, first: bool) -> str:
    if not token:
        return token
    # инициалы В.Д. / A.B.C.
    if re.fullmatch(r"(?:[A-Za-zА-Яа-яЁё]\.){1,4}", token):
        return token.upper()
    bare = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]", "", token)
    low = bare.lower().replace("ё", "е")
    if low in _KEEP_UPPER:
        return bare.upper()
    if not first and low in _SMALL_WORDS:
        return low
    if "-" in token:
        return "-".join(_title_token(p, first=True) for p in token.split("-"))
    if not bare:
        return token
    # Title Case по буквенному префиксу токена
    m = re.match(r"[0-9A-Za-zА-Яа-яЁё]+", token)
    if not m:
        return token
    word = m.group(0)
    core = word[0].upper() + word[1:].lower()
    return core + token[len(word) :]


def apply_legal_abbreviations(text: str) -> str:
    out = text or ""
    for pattern, repl in _LEGAL_ABBREV_PATTERNS:
        out = pattern.sub(repl, out)
    return _SPACE_RE.sub(" ", out).strip(" ,.-")


def prettify_org_name(name: str) -> str:
    """Сокращения юрформ + без FULL CAPS (Title Case, аббревиатуры UPPER)."""
    raw = (name or "").strip()
    if not raw:
        return ""
    raw = _COUNTRY_RE.sub("", raw).strip()
    was_caps = _looks_all_caps(raw) or raw.isupper()
    raw = raw.replace("Ё", "Е").replace("ё", "е")
    # унификация транслита до смены регистра
    raw = re.sub(r"(?i)инститьют", "ИНСТИТУТ" if was_caps else "Институт", raw)
    raw = re.sub(r"(?i)петролиум", "ПЕТРОЛЕУМ" if was_caps else "Петролеум", raw)
    pretty = apply_legal_abbreviations(raw)
    if was_caps:
        tokens = pretty.split()
        pretty = " ".join(_title_token(tok, first=(i == 0)) for i, tok in enumerate(tokens))
    pretty = _SPACE_RE.sub(" ", pretty).strip(" ,.-")
    pretty = re.sub(r"\bCo\.?\s*,?\s*Ltd\.?\b", "Co., Ltd", pretty, flags=re.I)
    pretty = re.sub(r"\bCO\.?\s*,?\s*LTD\.?\b", "Co., Ltd", pretty)
    pretty = re.sub(r"\bLtd\.?\b", "Ltd", pretty, flags=re.I)
    return pretty


def _strip_legal(text: str) -> str:
    t = _fold(text)
    t = _COUNTRY_RE.sub("", t).strip()
    changed = True
    while changed:
        changed = False
        for prefix in _LEGAL_PREFIXES:
            new = re.sub(rf"^{prefix}\s+", "", t, flags=re.I)
            if new != t:
                t = new.strip(" ,.-")
                changed = True
    t = t.strip(" \"'")
    return _SPACE_RE.sub(" ", t).strip()


def _compact_key(text: str) -> str:
    return _NON_ALNUM_RE.sub("", _fold(text))


def alias_keys(name: str) -> list[str]:
    """Максимально широкий набор ключей для склейки одной организации."""
    base = _strip_legal(name)
    folded = _fold(name)
    keys: set[str] = {base, folded}
    keys.add(re.sub(r"\s+им\.?\s+.+$", "", base).strip())
    keys.add(re.sub(r"\s+имени\s+.+$", "", base).strip())
    # без «энд / and / &»
    keys.add(re.sub(r"\s+(энд|and|&)\s+", " ", base).strip())
    # без слов-шумов
    compact = re.sub(
        r"\b(российск\w*|государственн\w*|федеральн\w*|бюджетн\w*|образовательн\w*|"
        r"высшего|образования|национальн\w*|исследовательск\w*|публичн\w*|"
        r"акционерн\w*|общество|ограниченн\w*|ответственност\w*|приволжск\w*)\b",
        " ",
        base,
    )
    compact = _SPACE_RE.sub(" ", compact).strip()
    if len(compact) >= 4:
        keys.add(compact)
    # ядро в кавычках
    quoted = re.findall(r'[«"]([^»"]+)[»"]', name or "")
    for q in quoted:
        keys.add(_fold(q))
        keys.add(_strip_legal(q))
        keys.add(_compact_key(q))
    # аббревиатуры в скобках: (ГБОУ ВО АГТУ ВШН), (RU) уже срезан
    for paren in re.findall(r"\(([^)]{2,80})\)", name or ""):
        p = _fold(paren)
        if p in {"ru", "cn", "us", "de", "fr", "jp", "nl", "dk", "ep", "wo"}:
            continue
        if len(p) >= 2:
            keys.add(p)
            keys.add(_compact_key(p))
            # последняя аббревиатура из цепочки
            tokens = [t for t in re.split(r"[\s,;/]+", p) if t]
            if tokens and 2 <= len(tokens[-1]) <= 12:
                keys.add(tokens[-1])
    # бренды из вложенных кавычек (Опыт, СибБурМаш, Измерон)
    for chunk in _quoted_chunks(name or ""):
        if chunk and len(chunk) >= 2:
            keys.add(_fold(chunk))
            keys.add(_strip_legal(chunk))
            keys.add(_compact_key(chunk))
    # без пробелов / дефисов
    for k in list(keys):
        if k:
            keys.add(_compact_key(k))
            keys.add(k.replace("-", " ").strip())
            keys.add(k.replace("-", "").strip())
    return sorted({k for k in keys if k and len(k) >= 2})


def classify_org(name: str, folded: str | None = None) -> str:
    """person | university | nii | company | foreign | unknown | redacted"""
    raw = name or ""
    f = folded if folded is not None else _strip_legal(raw)
    if not f:
        return "unknown"
    if _REDACTED_RE.search(raw):
        return "redacted"
    if re.search(r"\((?!RU)[A-Z]{2}\)\s*$", raw.strip(), re.I):
        return "foreign"
    if any(m in f for m in _FOREIGN_MARKERS) and not any(
        x in f for x in ("университет", "институт", "ооо", "пао", "ао ")
    ):
        if re.search(r"[a-z]", f) and not re.search(r"[а-я]", f):
            return "foreign"
        if any(
            m in f
            for m in (
                "лимитед",
                "корпорейшн",
                "текнолоджи",
                "технолоджи",
                "энержи",
                "рисерч",
                "инститьют",
                "петролеум",
                "петролиум",
            )
        ):
            return "foreign"
    if _PERSON_RE.match(raw.split("(")[0].strip()) and not any(m in f for m in _ORG_MARKERS):
        return "person"
    tokens = raw.split("(")[0].strip().split()
    if 2 <= len(tokens) <= 4 and all(re.match(r"^[А-ЯЁA-Z]", t) for t in tokens):
        if not any(m in f for m in _ORG_MARKERS):
            return "person"
    if any(re.search(m, f) for m in _UNI_MARKERS):
        return "university"
    if any(m in f for m in ("внии", "нии ", " нии", "со ран", " ран", "научн", "нпп", "нпо")) or (
        "институт" in f and "университет" not in f
    ):
        return "nii"
    if any(m in f for m in _ORG_MARKERS):
        return "company"
    return "unknown"


def load_alias_dictionary() -> dict[str, dict[str, Any]]:
    """key → {canonical_name, org_type, source}"""
    mapping: dict[str, dict[str, Any]] = {}

    def add(canonical: str, org_type: str, aliases: list[str], source: str) -> None:
        meta = {"canonical_name": canonical, "org_type": org_type, "source": source}
        for alias in [canonical, *aliases]:
            for key in alias_keys(alias):
                # не затираем более «сильные» источники короткими ключами от weaker
                if key in mapping and mapping[key]["source"] in ("seed", "extra") and source == "company_geo":
                    continue
                mapping.setdefault(key, meta)

    for center in SCIENCE_CENTERS:
        name_l = center["name"].lower()
        fold_n = _fold(center["name"])
        is_uni = any(
            x in name_l or x in fold_n
            for x in ("универ", "вшн", "мфти", "полит", "сколтех", "мисис", "фти")
        )
        add(
            center["name"],
            "university" if is_uni else "nii",
            list(center.get("aliases") or []),
            "science_centers",
        )

    for seed in SEED_ORGS:
        add(seed["canonical_name"], seed["org_type"], list(seed["aliases"]), "seed")

    for extra in EXTRA_ORG_ALIASES:
        add(extra["canonical_name"], extra["org_type"], list(extra["aliases"]), "extra")

    geo_path = ROOT / "data" / "company_geo.json"
    if geo_path.exists():
        payload = json.loads(geo_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            for row in payload:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("canonical_name") or "").strip()
                if not name:
                    continue
                aliases = [str(a) for a in (row.get("aliases") or []) if str(a).strip()]
                org_type = str(row.get("org_type") or "company")
                if org_type in ("oilgas_operator", "other", "service"):
                    org_type = "company"
                add(name, org_type, aliases, "company_geo")

    return mapping


def _lookup_dictionary(raw_name: str, dictionary: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    keys = alias_keys(raw_name)
    for key in sorted(keys, key=len, reverse=True):
        hit = dictionary.get(key)
        if hit:
            return hit
    # подстрочное совпадение длинных ключей (≥ 10), самые длинные первыми —
    # не короче 10, чтобы «газпром» (7) не склеивал все дочки
    blob = _strip_legal(raw_name)
    blob_compact = _compact_key(blob)
    candidates = sorted(
        ((k, v) for k, v in dictionary.items() if len(k) >= 10),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )
    for key, meta in candidates:
        key_compact = _compact_key(key)
        # compact только как префикс/равенство — не «ооогазпромнефть» внутри «…востокооо…»
        compact_hit = bool(
            len(key) >= 12
            and key_compact
            and (
                blob_compact == key_compact
                or blob_compact.startswith(key_compact)
                or key_compact.startswith(blob_compact)
            )
        )
        if key == blob or key in blob or compact_hit:
            # не матчить короткое «родительское» имя, если в строке ещё есть хвост
            # (иначе «газпром нефть» внутри «газпром нефть шельф» ок, а голый «газпром» — нет)
            if key in blob and key != blob:
                rest = blob.replace(key, " ", 1)
                rest = _SPACE_RE.sub(" ", rest).strip(" -")
                # если хвост похож на отдельную дочку (добыча/трансгаз/…) — пропуск,
                # пусть сработает более длинный ключ или останется unmatched
                if rest and any(
                    rest.startswith(p)
                    for p in (
                        "добыча",
                        "трансгаз",
                        "межрегион",
                        "нефть",
                        "нефт",
                        "бурение",
                        "переработ",
                        "снабжен",
                        "автоматизац",
                        "информац",
                        "цпс",
                        "восток",
                        "запад",
                        "шельф",
                        "ямал",
                    )
                ):
                    continue
            # compact: «газпромнефть» ⊂ «газпромнефтьвосток» → дочка, не родитель
            if compact_hit and blob_compact != key_compact and blob_compact.startswith(key_compact):
                rest_c = blob_compact[len(key_compact) :]
                if len(rest_c) >= 3:
                    continue
            return meta
    # короткие аббревиатуры только если очищенное имя само короткое (ГТИ, ВШН, ТАИФ)
    if 2 <= len(blob) <= 12 and blob in dictionary:
        return dictionary[blob]
    if 2 <= len(blob_compact) <= 12 and blob_compact in dictionary:
        return dictionary[blob_compact]
    return None


def split_assignees(raw: str | None) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    parts = _SPLIT_RE.split(str(raw).strip())
    return [p.strip() for p in parts if p and p.strip()]


_GENERIC_ORG_LABEL_RE = re.compile(
    r"^(?:"
    r"научно[-\s]?производственн\w*\s+(?:компани\w*|предприяти\w*|фирм\w*|объединени\w*|центр\w*)|"
    r"научно[-\s]?производственн\w*\s+фирм\w*\s+завод\w*|"
    r"научно[-\s]?внедренческ\w*\s+центр\w*|"
    r"научно[-\s]?исследовательск\w*\s+(?:институт\w*|центр\w*|компани\w*)|"
    r"научно[-\s]?технологическ\w*\s+центр\w*|"
    r"инженерн\w*\s+компани\w*|"
    r"институт\w*(?:\s+нефтегазовых\s+технологий)?|"
    r"нпп|нпк|нпф|нпо|нпц|нтц"
    r")$",
    re.I,
)


def _quoted_chunks(text: str) -> list[str]:
    """Куски между кавычками. Учитывает «ломаные» вложенные кавычки Роспатента.

    Пример: …\"Научно-производственная компания \"Опыт\" →
    [\"Научно-производственная компания\", \"Опыт\"].
    """
    t = (text or "").replace("«", '"').replace("»", '"').replace("“", '"').replace("”", '"')
    t = _COUNTRY_RE.sub("", t).strip()
    # хвостовой дубль (ООО "…") / (ООО "ИНТ "ГеоСпектр")
    t = re.sub(r"\s*\((?:ООО|АО|ПАО|ЗАО|ОАО|ТОО)\b[^)]{0,160}\)\s*$", "", t, flags=re.I).strip()

    # Вложенный шаблон Роспатента: "описательная часть "Бренд"
    nested = re.search(r'"([^"]{1,160}?)"\s*([^"]{1,80}?)"\s*$', t)
    if nested:
        head, brand = nested.group(1).strip(" ,.-"), nested.group(2).strip(" ,.-")
        out = [x for x in (head, brand) if x and not re.fullmatch(r"\(?[A-Z]{2}\)?", x)]
        if len(out) >= 2:
            return out

    # Обычные пары кавычек
    simple = [m.strip(" ,.-") for m in re.findall(r'"([^"]+)"', t) if m.strip(" ,.-")]
    simple = [s for s in simple if not re.fullmatch(r"\(?[A-Z]{2}\)?", s)]
    return simple


def _is_generic_org_label(text: str) -> bool:
    f = _fold(text)
    if not f:
        return True
    if _GENERIC_ORG_LABEL_RE.match(f):
        return True
    # слишком общее без собственного имени
    tokens = [t for t in re.split(r"\s+", f) if t]
    if not tokens:
        return True
    generic_tokens = {
        "научно",
        "производственная",
        "производственное",
        "производственный",
        "компания",
        "предприятие",
        "фирма",
        "центр",
        "организация",
        "объединение",
        "институт",
        "завод",
        "инженерная",
        "исследовательский",
        "исследовательская",
        "технологический",
        "технологическая",
        "внедренческий",
        "внедренческая",
    }
    distinctive = [t for t in tokens if t not in generic_tokens and len(t) > 1]
    return len(distinctive) == 0


def _looks_like_brand_token(text: str) -> bool:
    """Короткое собственное имя в кавычках: Опыт, ФЕБА, СибБурМаш, Измерон."""
    t = (text or "").strip(" ,.-«»\"()")
    if not t or _is_generic_org_label(t):
        return False
    if re.fullmatch(r"[A-Z]{2}", t):
        return False
    if t.upper() in {"ООО", "АО", "ПАО", "ЗАО", "ОАО", "ТОО", "НПП", "НПК", "НПФ", "НПО"}:
        return False
    words = t.split()
    if len(words) > 4:
        return False
    # односимвольные отсекаем
    if len(re.sub(r"[^0-9A-Za-zА-Яа-яЁё]", "", t)) < 2:
        return False
    return True


def _canonical_from_raw(raw_name: str) -> str:
    """Канон без словаря: не терять бренд из вложенных кавычек."""
    raw = _COUNTRY_RE.sub("", raw_name or "").strip()
    # хвостовой дубль вида (ООО "…")
    raw = re.sub(r"\s*\((?:ООО|АО|ПАО|ЗАО|ОАО|ТОО)[^)]{0,120}\)\s*$", "", raw, flags=re.I).strip()
    chunks = _quoted_chunks(raw)

    if len(chunks) >= 2:
        brand = chunks[-1]
        head = chunks[-2]
        if _looks_like_brand_token(brand):
            if _is_generic_org_label(head) or (
                _looks_like_brand_token(brand) and len(brand) <= 40
            ):
                # НПП «СибБурМаш», НПК «Опыт», Завод «Измерон»
                combined = f"{head} «{brand}»".strip()
                pretty = prettify_org_name(combined)
                # prettify мог схлопнуть голову в НПП — бренд обязан остаться
                if brand.casefold() not in pretty.casefold() and "«" not in pretty:
                    pretty = f"{pretty} «{prettify_org_name(brand)}»".strip()
                if not _is_generic_org_label(pretty):
                    return pretty
            return prettify_org_name(brand)
        # оба куска содержательные — склеиваем
        return prettify_org_name(f"{head} «{brand}»")

    if len(chunks) == 1:
        only = chunks[0]
        pretty = prettify_org_name(only)
        # не оставлять голое «НПП» / «Научно-производственная компания»
        if _is_generic_org_label(pretty) or _is_generic_org_label(only):
            fallback = _strip_legal(raw)
            fallback = prettify_org_name(fallback) if fallback else pretty
            if len(fallback) > len(pretty):
                return fallback
        return pretty

    # без кавычек
    canonical = re.sub(
        r"^(?:Федеральное|Общество|Публичное|Акционерное|Закрытое|Открытое|"
        r"Государственное|Муниципальное|Товарищество)[^«\"]{0,160}?",
        "",
        raw,
        flags=re.I,
    ).strip(" ,.-«»\"")
    if len(canonical) < 3:
        canonical = _strip_legal(raw)
    pretty = prettify_org_name(canonical)
    if _is_generic_org_label(pretty):
        fuller = prettify_org_name(_strip_legal(raw))
        if len(fuller) >= len(pretty):
            return fuller
    return pretty


def resolve_org(raw_name: str, dictionary: dict[str, dict[str, Any]]) -> dict[str, Any]:
    keys = alias_keys(raw_name)
    hit = _lookup_dictionary(raw_name, dictionary)
    # словарь сматчил «голову», а в сырой строке есть вложенный бренд — не отбрасывать бренд
    nested = _quoted_chunks(raw_name)
    if (
        hit
        and len(nested) >= 2
        and _looks_like_brand_token(nested[-1])
        and nested[-1].casefold().replace("ё", "е")
        not in (hit.get("canonical_name") or "").casefold().replace("ё", "е")
    ):
        hit = None
    org_type = hit["org_type"] if hit else classify_org(raw_name)
    if hit:
        canonical = hit["canonical_name"]
    elif org_type == "person":
        canonical = raw_name.split("(")[0].strip()
    elif org_type == "redacted":
        canonical = "Не публикуется (ППРФ)"
    else:
        canonical = _canonical_from_raw(raw_name)
    # словарь уже с нормальным регистром; unmatched — через prettify
    if hit:
        canonical = prettify_org_name(canonical) if _looks_all_caps(canonical) else canonical
    return {
        "raw": raw_name,
        "canonical_name": canonical,
        "org_type": org_type,
        "keys": keys,
        "merge_key": org_merge_key(canonical) or org_merge_key(raw_name),
        "matched_dictionary": bool(hit),
        "dictionary_source": hit.get("source") if hit else None,
    }


def _patent_clusters(row: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Кластер = coarse, подкластер = fine (направления науки)."""
    raw = row.get("directions_json")
    payload: dict[str, Any] | None = None
    if isinstance(raw, dict):
        payload = raw
    elif raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                payload = loaded
        except json.JSONDecodeError:
            payload = None
    fine: list[str] = []
    coarse: list[str] = []
    if payload:
        fine = normalize_fine(payload.get("fine") if isinstance(payload.get("fine"), list) else [])
        coarse_raw = payload.get("coarse") if isinstance(payload.get("coarse"), list) else []
        coarse = [str(x) for x in coarse_raw if str(x) in COARSE_DIRECTIONS]
        if not coarse and fine:
            coarse = fine_to_coarse(fine)
    return coarse, fine


def extract_from_patent_row(row: dict[str, Any], dictionary: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field in ("patentee", "applicant"):
        for part in split_assignees(row.get(field)):
            resolved = resolve_org(part, dictionary)
            key = resolved.get("merge_key") or org_merge_key(resolved["canonical_name"])
            if not key or key in seen:
                continue
            seen.add(key)
            resolved["role"] = field
            found.append(resolved)
    return found


def build_unique_org_report(patent_rows: list[dict[str, Any]]) -> dict[str, Any]:
    dictionary = load_alias_dictionary()
    by_canonical: dict[str, dict[str, Any]] = {}
    type_counter: dict[str, int] = defaultdict(int)
    patent_links = 0
    cluster_counter: Counter[str] = Counter()
    subcluster_counter: Counter[str] = Counter()

    for row in patent_rows:
        orgs = extract_from_patent_row(row, dictionary)
        clusters, subclusters = _patent_clusters(row)
        for c in clusters:
            cluster_counter[c] += 1
        for s in subclusters:
            subcluster_counter[s] += 1
        if not orgs:
            continue
        patent_links += 1
        for org in orgs:
            cid = org.get("merge_key") or org_merge_key(org["canonical_name"])
            if not cid:
                continue
            bucket = by_canonical.get(cid)
            if not bucket:
                bucket = {
                    "canonical_name": org["canonical_name"],
                    "org_type": org["org_type"],
                    "patent_count": 0,
                    "raw_examples": [],
                    "keys": sorted(set(org["keys"])),
                    "matched_dictionary": org["matched_dictionary"],
                    "dictionary_source": org.get("dictionary_source"),
                    "roles": set(),
                    "cluster_counter": Counter(),
                    "subcluster_counter": Counter(),
                }
                by_canonical[cid] = bucket
            bucket["patent_count"] += 1
            bucket["roles"].add(org["role"])
            bucket["keys"] = sorted(set(bucket["keys"]) | set(org["keys"]))
            # предпочитаем словарь / более «красивое» имя без FULL CAPS
            if org["matched_dictionary"] or (
                _looks_all_caps(bucket["canonical_name"]) and not _looks_all_caps(org["canonical_name"])
            ):
                bucket["canonical_name"] = org["canonical_name"]
            for c in clusters:
                bucket["cluster_counter"][c] += 1
            for s in subclusters:
                bucket["subcluster_counter"][s] += 1
            if len(bucket["raw_examples"]) < 5 and org["raw"] not in bucket["raw_examples"]:
                bucket["raw_examples"].append(org["raw"])
            if org["matched_dictionary"]:
                bucket["org_type"] = org["org_type"]
                bucket["matched_dictionary"] = True
                bucket["dictionary_source"] = org.get("dictionary_source")

    items = []
    for bucket in by_canonical.values():
        type_counter[bucket["org_type"]] += 1
        top_clusters = [
            {"name": name, "count": count}
            for name, count in bucket["cluster_counter"].most_common(5)
            if name in COARSE_DIRECTIONS or True
        ]
        top_subclusters = [
            {"name": name, "count": count}
            for name, count in bucket["subcluster_counter"].most_common(8)
            if name in FINE_DIRECTIONS or True
        ]
        items.append(
            {
                "canonical_name": bucket["canonical_name"],
                "org_type": bucket["org_type"],
                "patent_count": bucket["patent_count"],
                "raw_examples": bucket["raw_examples"],
                "keys": bucket["keys"],
                "matched_dictionary": bucket["matched_dictionary"],
                "dictionary_source": bucket.get("dictionary_source"),
                "roles": sorted(bucket["roles"]),
                "clusters": top_clusters,
                "subclusters": top_subclusters,
            }
        )
    items.sort(key=lambda x: (-x["patent_count"], x["canonical_name"].lower()))

    return {
        "patents_total": len(patent_rows),
        "patents_with_org": patent_links,
        "unique_orgs": len(items),
        "by_type": dict(type_counter),
        "dictionary_keys": len(dictionary),
        "clusters_total": [
            {"name": n, "count": c} for n, c in cluster_counter.most_common()
        ],
        "subclusters_total": [
            {"name": n, "count": c} for n, c in subcluster_counter.most_common()
        ],
        "note": (
            "Без города. Кластер = coarse (8 направлений), подкластер = fine (23+ИТ). "
            "Список организаций для ручного разбора; словарь расширен алиасами."
        ),
        "items": items,
    }
