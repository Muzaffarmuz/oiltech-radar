"""Сброс разметки событий перед повторным LLM-extract."""

from gartner.config import get_settings
from gartner.db import connect, init_db, set_state

get_settings.cache_clear()
s = get_settings()
print("llm_enabled", s.llm_enabled)
print("base_url", s.base_url)
print("model", s.llm_model)
print("key_set", bool(s.api_key))

init_db()
with connect() as c:
    c.execute("DELETE FROM cluster_members")
    c.execute("DELETE FROM cluster_forecasts")
    c.execute("DELETE FROM clusters")
    c.execute("DELETE FROM events")
    c.execute("DELETE FROM llm_cache")
    c.execute("UPDATE articles SET processed=0")
    n = c.execute("SELECT COUNT(*) AS n FROM articles").fetchone()["n"]
set_state("has_clusters", "0")
print("articles_ready", n)
