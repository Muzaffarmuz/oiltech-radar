"""Регрессии нормализации патентообладателей (вложенные кавычки, дочки)."""

from gartner.patent_orgs import load_alias_dictionary, resolve_org


def test_nested_quotes_keep_brand():
    d = load_alias_dictionary()
    cases = [
        (
            'Общество с ограниченной ответственностью "Научно-производственная компания "Опыт" (RU)',
            "Опыт",
        ),
        (
            'Общество с ограниченной ответственностью "Научно-производственная фирма Завод "Измерон" (RU)',
            "Измерон",
        ),
        (
            'Общество с ограниченной ответственностью "Научно-производственное предприятие "СибБурМаш" (RU)',
            "СибБурМаш",
        ),
        (
            'Общество с ограниченной ответственностью "Институт нефтегазовых технологий "ГеоСпектр" (ООО "ИНТ "ГеоСпектр") (RU)',
            "ГеоСпектр",
        ),
        (
            'Общество с ограниченной ответственностью "Инженерная компания "ФЕБА" (RU)',
            "ФЕБА",
        ),
    ]
    for raw, brand in cases:
        can = resolve_org(raw, d)["canonical_name"]
        assert brand.casefold() in can.casefold(), (raw, can)


def test_subsidiary_not_collapsed_to_parent():
    d = load_alias_dictionary()
    raw = 'Общество с ограниченной ответственностью "Газпромнефть-Восток" (ООО "Газпромнефть-Восток") (RU)'
    can = resolve_org(raw, d)["canonical_name"]
    assert "восток" in can.casefold()
    assert can.casefold() != "газпром нефть"
