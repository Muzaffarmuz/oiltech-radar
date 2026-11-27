import json

from gartner.pipeline.flow_enrich import (
    canonical_company,
    is_digest,
    load_enrich,
    load_enrich_raw,
    postprocess,
)


def test_canonical_company_merges_synonyms():
    assert canonical_company("ПАО «Газпром»") == "Газпром"
    assert canonical_company("ПАО «Газпром нефть»") == "Газпром нефть"
    assert canonical_company("ПАО «ЛУКОЙЛ»") == "ЛУКОЙЛ"
    assert canonical_company("Лукойл") == "ЛУКОЙЛ"
    assert canonical_company("ФГБУ «РЭА» Минэнерго России") == "РЭА Минэнерго"
    assert canonical_company("ЦБ РФ") == "Банк России"
    assert canonical_company("АО «Неизвестная компания»") == "Неизвестная компания"


def test_digest_detection():
    assert is_digest("Что произошло за день: воскресенье, 5 октября")
    assert not is_digest("Минэнерго обсудит экспорт бензина")


def test_postprocess_policy_macro_and_dedupe():
    out = postprocess(
        "policy",
        {
            "event_type": "macro",
            "severity": 5,
            "directions": ["Переработка и нефтехимия"],
            "impact": "ставка",
            "companies": ["Банк России", "ЦБ", "ПАО «Газпром»", "Газпром"],
        },
        title="Что произошло за день: суббота",
    )
    assert out["directions"] == []
    assert out["severity"] == 3
    assert out["companies"] == ["Банк России", "Газпром"]
    assert out["is_digest"] is True


def test_postprocess_invest_participants_and_amount():
    out = postprocess(
        "investments",
        {
            "deal_type": "ma",
            "participants": [
                {"name": "ПАО «ЛУКОЙЛ»", "role": "target"},
                {"name": "Лукойл", "role": "investor"},
                {"name": "Carlyle", "role": "investor"},
            ],
            "amount": {"value": 2.5, "scale": "млрд", "currency": "USD", "text": "$2,5 млрд", "amount_mln": 2500},
            "directions": ["Добыча и нефтесервис"],
        },
    )
    assert [p["name"] for p in out["participants"]] == ["ЛУКОЙЛ", "Carlyle"]
    assert out["amount"] == {"amount_mln": 2500, "currency": "USD", "text": "$2,5 млрд"}
    assert out["directions"] == ["Добыча и нефтесервис"]


def test_load_enrich_prefers_log_over_json(tmp_path):
    (tmp_path / "policy_enrich_lab.json").write_text(
        json.dumps({"items": {"a1": {"event_type": "market"}, "a2": {"event_type": "other"}}}),
        encoding="utf-8",
    )
    rows = [
        {"article_id": "a2", "method": "llm", "enrich": {"event_type": "sanctions", "severity": 2}},
        {"article_id": "a3", "method": "llm_error", "enrich": None},
    ]
    (tmp_path / "policy_enrich_lab_decisions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    raw = load_enrich_raw("policy", base=tmp_path)
    assert set(raw) == {"a1", "a2"}
    assert raw["a2"]["event_type"] == "sanctions"
    done = load_enrich("policy", {"a1": "Что произошло за день"}, base=tmp_path)
    assert done["a1"]["is_digest"] is True
    assert done["a2"]["severity"] == 2
