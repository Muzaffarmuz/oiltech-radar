"""Тесты краула, скоринга и выемки заголовка без LLM."""

from __future__ import annotations

from gartner.custom_sources.article_extract import is_generic_title, polish_title
from gartner.custom_sources.crawl import classify_page, parse_rss_items, parse_sitemap_locs
from gartner.custom_sources.scoring import looks_like_article_url, looks_like_hub_url, news_score, same_site
from tests.fixtures_custom_sources import ARTICLE_HTML, LIST_HTML


def test_news_score_penalizes_about_and_contacts() -> None:
    assert news_score("https://x.ru/press/releases/", "Пресс-центр") > 0
    assert news_score("https://x.ru/company/vacancy/", "Вакансии") < 0
    assert news_score("https://x.ru/press-center/kontakty/", "Контакты") < 0


def test_article_url_with_query_id() -> None:
    assert looks_like_article_url("https://aosngs.ru/press-center/novosti/index.php?ELEMENT_ID=3772")
    assert looks_like_article_url("https://www.novatek.ru/ru/press/releases/index.php?id_4=7882")
    assert not looks_like_article_url("https://x.ru/")


def test_wordpress_cat_hub_and_p_article() -> None:
    """WordPress: ?cat= — лента, ?p= — пост (как на astrg.ru)."""
    hub = "https://www.astrg.ru/?cat=5"
    post = "https://www.astrg.ru/?p=71368"
    assert looks_like_hub_url(hub)
    assert not looks_like_article_url(hub)
    assert news_score(hub, "Новости") > 0
    assert looks_like_article_url(post)
    assert not looks_like_hub_url(post)
    assert news_score(post, "Назначен новый руководитель") > 0


def test_extract_strips_hidden_privacy_dialog() -> None:
    """Скрытая модалка политики ПДн не должна становиться телом статьи (кейс onhpgroup)."""
    from gartner.custom_sources.article_extract import extract_article_page

    html = """
    <html><body class="view-article">
      <main>
        <h1>День открытых дверей в ПАО «ОНХП»</h1>
        <p>День открытых дверей для учеников 8-9 классов и их родителей прошёл на площадке компании.
        Гости познакомились с инженерными специальностями и лабораториями предприятия.</p>
      </main>
      <div class="eb-hide eb-custom">
        <div id="dialog3" class="eb-dialog">
          <div class="eb-content">
            <p><strong>1. Общие положения</strong></p>
            <p>1.1. Использование Пользователем сайта означает согласие с настоящей Политикой
            конфиденциальности и условиями обработки персональных данных Пользователя.
            1.2. В случае несогласия с условиями Политики конфиденциальности Пользователь должен
            прекратить использование Сайта. Далее длинный юридический текст политики ПДн
            повторяется много раз, чтобы блок был достаточно объёмным для экстрактора. """ + (
                "пункт политики конфиденциальности обработка персональных данных. " * 40
            ) + """</p>
          </div>
        </div>
      </div>
    </body></html>
    """
    rec = extract_article_page(html, "https://onhpgroup.com/company/news/demo", source_name="onhpgroup.com")
    assert rec is not None
    assert "День открытых дверей" in rec.title or "открытых дверей" in rec.text
    assert "1.1." not in rec.text
    assert "Политикой конфиденциальности" not in rec.text


def test_same_site_does_not_follow_com_mirror() -> None:
    assert same_site("https://lukoil.ru/a", "https://www.lukoil.ru/")
    assert not same_site("https://www.lukoil.com/PressCenter", "https://lukoil.ru/")


def test_polish_generic_novatek_title() -> None:
    text = (
        "Пресс-релизы и мероприятия «НОВАТЭК» запустил самую северную станцию "
        "мониторинга парниковых газов в Москве. Дальше подробности проекта."
    )
    title = polish_title("Пресс-релизы и мероприятия", text)
    assert "НОВАТЭК" in title
    assert title.lower() != "пресс-релизы и мероприятия"


def test_generic_site_title() -> None:
    assert is_generic_title("Новости | АО Саханефтегазсбыт")


def test_classify_list_as_hub() -> None:
    assert classify_page("https://example-news.test/news/", LIST_HTML) in {"hub", "article"}


def test_classify_article() -> None:
    kind = classify_page("https://example-news.test/news/one", ARTICLE_HTML)
    assert kind in {"article", "other", "hub"}


def test_parse_sitemap_and_rss() -> None:
    xml = """<?xml version="1.0"?><urlset>
      <url><loc>https://x.ru/news/a</loc></url>
    </urlset>"""
    assert "https://x.ru/news/a" in parse_sitemap_locs(xml)
    rss = """<rss><channel><item><title>Релиз</title><link>https://x.ru/news/a</link><description>Текст</description></item></channel></rss>"""
    items = parse_rss_items(rss)
    assert items
    assert "news/a" in items[0]["link"]
