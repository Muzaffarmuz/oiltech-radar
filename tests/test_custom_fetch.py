"""Тесты обхода JS-cookie challenge в fetch."""

from __future__ import annotations

from gartner.custom_sources.fetch import (
    _compute_jhash,
    _is_js_cookie_challenge,
    _solve_from_js_p,
    reset_fetch_sessions,
)


def test_jhash_stable() -> None:
    assert _compute_jhash(102) == _compute_jhash(102)
    assert 0 <= _compute_jhash(102) < 1111


def test_solve_from_js_p() -> None:
    tokens = _solve_from_js_p("136,86400,0,0,0")
    assert tokens is not None
    assert tokens["__js_p_"] == "136,86400,0,0,0"
    assert tokens["__jhash_"] == str(_compute_jhash(136))
    assert "Mozilla" in tokens["__jua_"]


def test_challenge_detection() -> None:
    assert _is_js_cookie_challenge(
        '<html><script>function get_jhash(b){} var x="__js_p_";</script></html>'
    )
    assert not _is_js_cookie_challenge("<html><body><a href='/news/1'>x</a></body></html>")


def test_reset_sessions() -> None:
    reset_fetch_sessions()
