"""Нормализация названий компаний."""

from __future__ import annotations

import re

COMPANY_PREFIX_RE = re.compile(
    r"^(?:АО|ПАО|ОАО|ООО|НК|ПАО НК|ФГУП|ППК|ГК|АНО)\s+",
    re.IGNORECASE,
)

ALIASES = {
    "газпром": "Газпром нефть",
    "газпром нефть": "Газпром нефть",
    "газпромнефть": "Газпром нефть",
    "gazprom neft": "Газпром нефть",
    "татнефть": "Татнефть",
    "tatneft": "Татнефть",
    "роснефть": "Роснефть",
    "лукойл": "Лукойл",
    "сибур": "СИБУР",
    "зарубежнефть": "Зарубежнефть",
    "новатэк": "НОВАТЭК",
    "транснефть": "Транснефть",
}

VENDOR_BLOCKLIST = {
    "сбер",
    "яндекс",
    "yandex",
    "microsoft",
    "ibm",
    "sap",
    "oracle",
    "huawei",
    "ростелеком",
}


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\ufeff", "").replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_company(value: object) -> str:
    company = normalize_text(value)
    if not company:
        return ""
    company = company.replace("«", "").replace("»", "").replace('"', "")
    company = re.sub(r"[()]+", " ", company)
    company = re.sub(r"\s{2,}", " ", company).strip()
    company = COMPANY_PREFIX_RE.sub("", company).strip()
    key = company.lower()
    if any(v in key for v in VENDOR_BLOCKLIST):
        return ""
    return ALIASES.get(key, company)
