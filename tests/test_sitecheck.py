"""Preference-driven website checks: compiler, checker, integrity gate and reference sites (standard library only)."""

from __future__ import annotations

import json

import pytest

from agentescrow import sitecheck as sc

BASE = {
    "business_name": "Lens & Light Studio",
    "purpose": "Portfolio website for a wedding photographer",
    "sections": ["hero", "about", "gallery", "pricing", "contact"],
    "primary_color": "blue",
    "theme": "any",
    "contact_fields": ["name", "email", "message"],
    "include_text": ["Book a free consultation"],
    "tone": "Minimal and professional",
}


def _results(prefs, persona):
    data = sc.normalize_prefs(prefs)
    html = sc.render_site(data, persona)
    return html, {r["id"]: r for r in sc.run_checks(html, sc.compile_checks(data))}


# ----------------------------------------------------------------- preferences --
def test_preferences_are_normalised_and_the_contact_section_is_added():
    data = sc.normalize_prefs({**BASE, "sections": ["gallery"], "business_name": "  Lens   Studio "})
    assert data["business_name"] == "Lens Studio"
    assert data["sections"] == ["gallery", "contact"]  # a contact form needs somewhere to live


@pytest.mark.parametrize(
    "patch",
    [
        {"business_name": ""},
        {"business_name": "<b>Hi</b>"},
        {"sections": []},
        {"sections": ["nonsense"]},
        {"primary_color": "chartreuse"},
        {"theme": "sepia"},
        {"contact_fields": ["fax"]},
        {"include_text": ["x"]},
        {"include_text": ["one", "two", "three", "four", "five", "six"]},
    ],
)
def test_invalid_preferences_are_rejected_with_a_message(patch):
    with pytest.raises(ValueError):
        sc.normalize_prefs({**BASE, **patch})


def test_acceptance_criteria_mention_every_preference():
    text = "\n".join(sc.acceptance_criteria(sc.normalize_prefs({**BASE, "theme": "dark"})))
    for needle in ("Lens & Light Studio", '"Gallery"', "contact form", "blue", "dark page background", "Book a free consultation", "Minimal and professional"):
        assert needle in text


def test_the_compiler_is_deterministic_and_committable():
    data = sc.normalize_prefs(BASE)
    first, second = sc.checks_to_json(sc.compile_checks(data)), sc.checks_to_json(sc.compile_checks(dict(data)))
    assert first == second
    assert json.loads(first)[0]["id"] == "business_name"


# ------------------------------------------------------------- the three workers --
@pytest.mark.parametrize("color", sorted(sc.COLORS))
@pytest.mark.parametrize("theme", ["any", "light", "dark"])
def test_the_honest_site_meets_every_preference(color, theme):
    html, results = _results({**BASE, "primary_color": color, "theme": theme}, "honest")
    failed = [r for r in results.values() if not r["passed"]]
    assert not failed, failed
    assert sc.scan_site_integrity(html) == []


def test_the_sloppy_site_fails_exactly_what_it_neglected():
    _, results = _results(BASE, "sloppy")
    assert {key for key, r in results.items() if not r["passed"]} == {"contact_form", "primary_color", "img_alt"}


def test_the_cheating_site_is_stopped_by_the_integrity_gate_and_fails_the_checks():
    html, results = _results(BASE, "cheater")
    assert any("<script>" in finding for finding in sc.scan_site_integrity(html))
    assert not results["no_external"]["passed"] and not results["business_name"]["passed"]


def test_a_blank_page_is_rejected():
    data = sc.normalize_prefs(BASE)
    passed, total = sc.tally(sc.run_checks(sc.blank_page(), sc.compile_checks(data)))
    assert passed < total / 2


# ------------------------------------------------------------------ single checks --
def _page(extra_css="", body="", head=""):
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        f"<title>Acme</title><style>body{{margin:0}}{extra_css}</style>{head}</head><body><h1>Acme</h1>{body}</body></html>"
    )


def _check(html, kind, **params):
    check = {"id": kind, "kind": kind, "source": "preference", "label": kind, "params": params}
    return sc.run_checks(html, [check])[0]


def test_dominant_colour_decides_the_accent_colour():
    css = "a{color:#2563eb}button{background:rgb(37,99,235)}h2{border-color:hsl(220,80%,50%)}.x{color:#ea580c}"
    assert _check(_page(css), "primary_color", family="blue")["passed"]
    assert not _check(_page(css), "primary_color", family="orange")["passed"]


def test_neutrals_and_pale_tints_do_not_count_as_an_accent():
    result = _check(_page("body{background:#ffffff;color:#1f2937}.card{background:#dbeafe}"), "primary_color", family="blue")
    assert not result["passed"] and "No saturated accent" in result["detail"]


def test_theme_reads_the_background_through_css_variables():
    dark = _page(":root{--bg:#0b1220}body{background:var(--bg)}")
    assert _check(dark, "theme", mode="dark")["passed"] and not _check(dark, "theme", mode="light")["passed"]
    assert _check(_page("body{background:#fff}"), "theme", mode="light")["passed"]
    assert not _check(_page(), "theme", mode="dark")["passed"]


def test_theme_ignores_rules_inside_media_queries():
    css = "body{background:#ffffff}@media (max-width:600px){body{background:#000000}}"
    assert _check(_page(css), "theme", mode="light")["passed"]


def test_a_contact_form_needs_labels_every_field_and_a_submit_button():
    good = '<form><label for="a">Name</label><input id="a" name="name"><label for="b">Email</label><input id="b" type="email" name="e"><button>Send</button></form>'
    assert _check(_page(body=good), "contact_form", fields=["name", "email"])["passed"]
    unlabeled = '<form><input name="name"><input type="email" name="e"><button>Send</button></form>'
    assert "no label" in _check(_page(body=unlabeled), "contact_form", fields=["name", "email"])["detail"]
    missing = '<form><label for="a">Name</label><input id="a" name="name"><button>Send</button></form>'
    assert "missing field(s): email" in _check(_page(body=missing), "contact_form", fields=["name", "email"])["detail"]
    assert "no submit button" in _check(_page(body='<form><label>Name <input name="name"></label></form>'), "contact_form", fields=["name"])["detail"]
    assert not _check(_page(), "contact_form", fields=["name"])["passed"]


def test_a_section_is_found_by_id_class_or_heading():
    assert _check(_page(body='<section id="gallery"></section>'), "section", key="gallery")["passed"]
    assert _check(_page(body='<div class="card pricing"></div>'), "section", key="pricing")["passed"]
    assert _check(_page(body="<h2>Our Portfolio</h2>"), "section", key="gallery")["passed"]
    assert not _check(_page(body="<h2>Hello</h2>"), "section", key="gallery")["passed"]


def test_baseline_checks():
    assert not _check(_page(body="<h1>Two</h1>"), "single_h1")["passed"]
    assert not _check(_page(body='<img src="data:image/png;base64,AAAA">'), "img_alt")["passed"]
    assert _check(_page(body='<img src="data:image/png;base64,AAAA" alt="A cat">'), "img_alt")["passed"]
    assert not _check("<html><body><h1>x</h1></body></html>", "structure")["passed"]
    assert not _check("<!doctype html><html lang=en><head><title>x</title></head></html>", "responsive")["passed"]


@pytest.mark.parametrize(
    "html",
    [
        _page(head='<link rel="stylesheet" href="https://cdn.example/x.css">'),
        _page(body='<img src="//cdn.example/a.png" alt="x">'),
        _page("body{background:url(https://evil.example/a.png)}"),
        _page("@import url('https://evil.example/a.css');"),
    ],
)
def test_loading_from_other_sites_is_caught(html):
    assert not _check(html, "no_external")["passed"]


def test_links_to_other_sites_are_fine_but_resources_are_not():
    assert _check(_page(body='<a href="https://example.org">Partner</a><img src="data:image/gif;base64,R0lG" alt="x">'), "no_external")["passed"]


# --------------------------------------------------------------------- integrity --
@pytest.mark.parametrize(
    "snippet",
    [
        "<script>alert(1)</script>",
        '<img src="data:image/gif;base64,R0lG" alt="x" onerror="x()">',
        '<a href="javascript:alert(1)">x</a>',
        '<iframe src="about:blank"></iframe>',
        '<meta http-equiv="refresh" content="0;url=https://evil.example">',
        '<object data="x"></object>',
    ],
)
def test_scripts_and_embeds_are_findings(snippet):
    assert sc.scan_site_integrity(_page(body=snippet) if not snippet.startswith("<meta") else _page(head=snippet))


def test_a_clean_page_has_no_integrity_findings():
    assert sc.scan_site_integrity(_page(body="<p>Hello</p>")) == []


def test_oversized_pages_are_flagged():
    assert any("larger than" in f for f in sc.scan_site_integrity("<p>" + "x" * (sc.MAX_HTML_CHARS + 1)))


# ------------------------------------------------------------------------ preview --
def test_the_preview_document_puts_the_policy_first_and_keeps_standards_mode():
    doc = sc.preview_document("<!DOCTYPE html><html><body>x</body></html>")
    assert doc.startswith('<!doctype html><meta http-equiv="Content-Security-Policy"')
    assert doc.lower().count("<!doctype") == 1
    assert "default-src 'none'" in doc


def test_an_unparseable_page_fails_instead_of_crashing():
    results = sc.run_checks("<<<>>>&&&", sc.compile_checks(sc.normalize_prefs(BASE)))
    assert len(results) > 0 and not all(r["passed"] for r in results)


def test_scripted_workers():
    data = sc.normalize_prefs(BASE)
    assert set(sc.scripted_site_deliverable(data, "honest")) == {"index_html", "explanation"}
    with pytest.raises(ValueError):
        sc.scripted_site_deliverable(data, "nobody")
