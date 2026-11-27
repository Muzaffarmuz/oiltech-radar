"""Экспериментальные домены нового парсера (прогон 3.2)."""

from __future__ import annotations

SAMPLE_SITE_URLS = [
    "https://lukoil.ru/",
    "https://www.novatek.ru/",
    "https://surgutneftegas.ru/",
    "https://www.ipng.ru/",
    "https://www.vniineft.ru/",
    "https://www.npnh.ru/",
    "https://bznga.ru/",
    "https://npp-unm.ru/",
    "https://aosngs.ru/",
    "https://www.penzaregiongaz.ru/",
    "https://nefthimmash.ru/",
    "https://www.jereh-rus.com/",
    "https://npoineko.ru/",
    "https://oilandgasgeology.ru/",
    "https://petroleum.ru/",
    "https://www.kingpetro.ru/",
]

SAMPLE_DOMAINS = (
    "lukoil.ru",
    "novatek.ru",
    "surgutneftegas.ru",
    "ipng.ru",
    "vniineft.ru",
    "npnh.ru",
    "bznga.ru",
    "npp-unm.ru",
    "aosngs.ru",
    "penzaregiongaz.ru",
    "nefthimmash.ru",
    "jereh-rus.com",
    "npoineko.ru",
    "oilandgasgeology.ru",
    "petroleum.ru",
    "kingpetro.ru",
)


def norm_host(value: str) -> str:
    text = (value or "").strip().lower()
    text = text.replace("https://", "").replace("http://", "")
    text = text.split("/")[0].split("?")[0]
    if text.startswith("www."):
        text = text[4:]
    return text
