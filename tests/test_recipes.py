import re

import pytest

from aitk.connect import recipes
from aitk.connect.recipes import LISTED, READY, RO_KIT, RO_NONE, RecipeError, find, load_all, parse

SECRET_LOOKING = re.compile(r"(sk|pk|ak)-[A-Za-z0-9]{16,}|[A-Za-z0-9]{32,}")


def test_every_recipe_loads_and_is_consistent():
    all_recipes = load_all()
    assert len(all_recipes) >= 10
    for r in all_recipes.values():
        assert r.summary and r.checked and r.docs_url or r.status == LISTED
        assert r.confidence in ("checked", "partly", "unchecked")
        if r.status == READY:
            assert r.access_steps, r.id
            if r.transport in ("stdio", "http"):
                assert r.read_only == RO_KIT, f"{r.id}: a connector the kit starts must be guarded"
            if r.transport == "oauth":
                assert not r.fields and r.url.startswith("https://")
        for f in r.fields:
            assert f.key.isupper() or f.key.isidentifier()


def test_recipes_contain_no_secret_values():
    from importlib import resources
    folder = resources.files("aitk.connect") / "recipes"
    for entry in folder.iterdir():
        text = entry.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "=" in line and "url" not in line and "docs_url" not in line:
                assert not SECRET_LOOKING.search(line.split("=", 1)[1]), f"{entry.name}: {line}"


def test_server_name_marks_read_only():
    r = load_all()
    assert r["alpaca"].server_name == "alpaca-readonly"
    assert r["robinhood"].server_name == "robinhood"


def test_find_matches_covered_brokers_and_prefers_ready():
    hits = find("fidelity")
    assert hits and hits[0].id == "snaptrade" and any(h.id == "no-connector" for h in hits)
    assert find("Alpaca")[0].id == "alpaca"
    assert find("") == []
    assert find("zzz-not-a-broker") == []


def test_parse_rejects_bad_recipes():
    base = {"id": "x", "name": "X", "summary": "s", "checked": "2026-01-01", "docs_url": "https://x",
            "access_steps": ["a"]}
    with pytest.raises(RecipeError):
        parse({**base, "read_only": "magic", "connector": {"transport": "stdio", "command": ["a"]}})
    with pytest.raises(RecipeError):
        parse({**base, "read_only": "kit", "connector": {"transport": "stdio"}})            # no command
    with pytest.raises(RecipeError):
        parse({**base, "read_only": "kit", "connector": {"transport": "oauth", "url": "https://x"}})
    with pytest.raises(RecipeError):
        parse({**base, "read_only": "sign-in", "connector": {"transport": "http", "url": "http://x"}})
    with pytest.raises(RecipeError):
        parse({**base, "read_only": "kit", "fields": [{"key": "A", "label": "a"}],
               "connector": {"transport": "http", "url": "https://x", "header_fields": ["B"]}})
    ok = parse({**base, "read_only": "kit", "connector": {"transport": "stdio", "command": ["uvx", "x"]}})
    assert ok.guarded and ok.read_only == RO_KIT


def test_get_unknown_recipe_names_the_known_ones():
    with pytest.raises(RecipeError) as exc:
        recipes.get("nope")
    assert "alpaca" in str(exc.value)


def test_not_read_only_recipes_carry_a_warning():
    for r in load_all().values():
        if r.status == READY and r.read_only == RO_NONE:
            assert r.warning, r.id
