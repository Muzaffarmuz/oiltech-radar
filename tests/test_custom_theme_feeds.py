"""Тесты тематики и поиска лент."""

from __future__ import annotations

from gartner.custom_sources.feeds import extract_feed_candidates, looks_like_rss
from gartner.custom_sources.theme import classify_theme


def test_oilgas_theme_on_operator_html() -> None:
    html = """
    <html><head><title>ПАО Татнефть</title></head>
    <body>Новости компании: добыча нефти, бурение скважин, месторождение Ромашкинское.</body></html>
    """
    res = classify_theme(html, url="https://www.tatneft.ru/")
    assert res["accepted"]
    assert res["theme"] in {"oilgas", "mixed"}


def test_reject_shop_without_oilgas() -> None:
    html = "<html><body>Интернет-магазин, каталог товаров, корзина, доставка по России</body></html>"
    res = classify_theme(html, url="https://shop.example.ru/")
    assert not res["accepted"]
    assert res["theme"] == "other"


def test_extract_news_and_rss_links() -> None:
    html = """
    <html><head><link rel="alternate" type="application/rss+xml" href="/rss.xml"></head>
    <body><a href="/press-center/news/">Пресс-центр</a><a href="/about">О компании</a></body></html>
    """
    cands = extract_feed_candidates(html, "https://www.tatneft.ru/")
    joined = " ".join(cands)
    assert "/press-center/news/" in joined
    assert any(x.endswith("/rss.xml") or "/rss" in x for x in cands)


def test_rss_detection() -> None:
    assert looks_like_rss('<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>')
    assert not looks_like_rss("<html><body>news</body></html>")
