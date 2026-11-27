"""Фикстуры HTML для тестов custom sources."""

LIST_HTML = """
<html><body>
  <h1>Новости</h1>
  <div class="news-list">
    <a class="news-item" href="/news/one">Первая статья</a>
    <a class="news-item" href="/news/two">Вторая статья</a>
  </div>
  <a class="next-page" href="/news?page=2">Далее</a>
</body></html>
"""

LIST_HTML_PAGE2 = """
<html><body>
  <div class="news-list">
    <a class="news-item" href="/news/three">Третья статья</a>
  </div>
</body></html>
"""

ARTICLE_HTML = """
<html><body>
  <article>
    <h1 class="title">Цифровой двойник месторождения</h1>
    <time datetime="2026-03-15">15 марта 2026</time>
    <div class="content">
      <p>Компания внедрила цифровой двойник для оптимизации добычи и снижения простоев оборудования на промысле.</p>
      <p>Решение включает моделирование скважин и интеграцию с АСУ ТП.</p>
    </div>
    <script>evil()</script>
  </article>
</body></html>
"""

ARTICLE_HTML_THIN = """
<html><body>
  <h1>Коротко</h1>
  <div class="content">мало</div>
</body></html>
"""

HOME_HTML = """
<html><body>
  <a href="/about">О компании</a>
  <a href="/news/">Новости</a>
  <a href="/analytics">Аналитика</a>
</body></html>
"""

VALID_RULES = {
    "list_url": "https://example-news.test/news/",
    "list": {
        "article_link_selector": "a.news-item",
        "link_attr": "href",
    "pagination": {"next_selector": "a.next-page", "max_pages": 2, "strategy": "next_link"},
    },
    "article": {
        "title_selector": "h1.title",
        "date_selector": "time",
        "date_attr": "datetime",
        "text_selector": "div.content",
        "remove_selectors": ["script", "style"],
    },
    "source_name": "example-news.test",
    "version": 1,
}
