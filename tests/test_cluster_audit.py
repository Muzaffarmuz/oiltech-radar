from gartner.pipeline.cluster_audit import apply_audit, kept_theme_ids, needs_reassign, taxonomy_jobs


def test_taxonomy_jobs_and_kept_ids():
    rows = [
        {
            "article_id": "a1",
            "title": "Бурение скважины",
            "cluster_id": "c1",
            "cluster_title": "Бурение",
            "sub_cluster_id": "c1_s0",
            "sub_cluster_title": "Наклонное бурение",
            "is_noise": 0,
        },
        {
            "article_id": "a2",
            "title": "Уран",
            "cluster_id": "c2",
            "cluster_title": "Выщелачивание",
            "is_noise": 0,
        },
    ]
    jobs = taxonomy_jobs(rows)
    assert {j["id"] for j in jobs} == {"c1", "c1_s0", "c2"}
    taxonomy = {
        "c1": {"kind": "cluster", "keep": True},
        "c1_s0": {"kind": "subcluster", "parent_id": "c1", "keep": True},
        "c2": {"kind": "cluster", "keep": False},
        "c2_s0": {"kind": "subcluster", "parent_id": "c2", "keep": True},
    }
    kept_c, kept_s = kept_theme_ids(taxonomy)
    assert kept_c == {"c1"}
    assert kept_s == {"c1_s0"}


def test_apply_audit_drop_keep_reassign_unassigned():
    rows = [
        {"article_id": "d1", "title": "Уран", "cluster_id": "c2", "cluster_title": "Выщелачивание"},
        {
            "article_id": "k1",
            "title": "Бурение",
            "cluster_id": "c1",
            "cluster_title": "Бурение",
            "sub_cluster_id": "c1_s0",
            "sub_cluster_title": "Наклонное",
        },
        {
            "article_id": "m1",
            "title": "Наладка оборудования",
            "cluster_id": "c3",
            "cluster_title": "Образование",
        },
        {
            "article_id": "u1",
            "title": "Странный кейс",
            "cluster_id": "c3",
            "cluster_title": "Образование",
        },
    ]
    fits = {
        "d1": {"oilgas": False, "fits": False, "reason": "уран"},
        "k1": {"oilgas": True, "fits": True, "score": 0.9},
        "m1": {"oilgas": True, "fits": False, "score": 0.1},
        "u1": {"oilgas": True, "fits": False, "score": 0.1},
    }
    moves = {
        "m1": {"cluster_id": "c1", "sub_cluster_id": "c1_s0", "reason": "добыча"},
        "u1": {"cluster_id": "", "sub_cluster_id": "", "reason": "нет темы"},
    }
    audited = apply_audit(
        rows,
        fits,
        moves,
        kept_clusters={"c1"},
        kept_subs={"c1_s0"},
        titles={"c1": "Бурение", "c1_s0": "Наклонное"},
    )
    by_id = {r["article_id"]: r for r in audited}
    assert by_id["d1"]["audit_status"] == "dropped"
    assert by_id["k1"]["audit_status"] == "kept"
    assert by_id["m1"]["audit_status"] == "reassigned"
    assert by_id["m1"]["cluster_id"] == "c1"
    assert by_id["u1"]["audit_status"] == "unassigned"
    assert needs_reassign(rows[2], fits["m1"], kept_clusters={"c1"}, kept_subs={"c1_s0"})
