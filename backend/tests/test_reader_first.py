"""The client library and the Reader-First presets."""

import asyncio

import pytest
from sqlmodel import select

from app.presets import READER_FIRST


def test_client_docs_are_saved_found_and_replaced_by_title(db):
    from app import client_library as lib
    from app.db import AuditEntry, KnowledgeDoc, session

    first = asyncio.run(lib.save("VAIO", "reader profile", "IT Director",
                                 "# Profile\nBanned: seamless, next-gen."))
    assert first["saved"] == "VAIO · Reader Profile · IT Director"
    assert first["replaced_existing"] is False
    again = asyncio.run(lib.save("vaio", "Reader Profile", "it director", "v2"))
    assert again == {**again, "saved": "VAIO · Reader Profile · IT Director",
                     "replaced_existing": True}
    asyncio.run(lib.save("VAIO", "Proof Bank", "", "P01: 1.4 kg"))
    asyncio.run(lib.save("Acme", "Proof Bank", "", "secret acme stat"))

    found = asyncio.run(lib.find("VAIO"))
    titles = [d["title"] for d in found["documents"]]
    assert "VAIO · Proof Bank" in titles and not any("Acme" in t for t in titles)
    hits = asyncio.run(lib.find("VAIO", "P01 kg"))
    assert [m["title"] for m in hits["matches"]] == ["VAIO · Proof Bank"]
    assert asyncio.run(lib.find("VAIO", "secret acme stat"))["matches"] == []
    assert asyncio.run(lib.find("Nobody"))["documents"] == []

    with session() as s:
        profiles = [d for d in s.exec(select(KnowledgeDoc)).all()
                    if d.title.lower() == "vaio · reader profile · it director"]
        assert len(profiles) == 1 and profiles[0].content == "v2"
        assert any(e.kind == "knowledge_saved" for e in s.exec(select(AuditEntry)).all())


def test_client_docs_need_a_client_a_known_kind_and_content(db):
    from app import client_library as lib

    for args in [("", "Proof Bank", "", "x"), ("VAIO", "Wishlist", "", "x"),
                 ("VAIO", "Proof Bank", "", "  ")]:
        with pytest.raises(lib.LibraryError):
            asyncio.run(lib.save(*args))
    # the separator can't be smuggled in to impersonate another client's doc
    assert lib.title_for("Acme · Proof Bank", "Proof Bank") == "Acme - Proof Bank · Proof Bank"


def test_saving_needs_approval_and_reading_does_not():
    from app.agents.tools import HUB_TOOLS, needs_approval, risk_of

    risk = {t.name: risk_of(t) for t in HUB_TOOLS}
    assert risk["save_client_doc"] == "write"
    assert needs_approval(risk["save_client_doc"], "approve_writes")
    assert risk["find_client_docs"] == risk["fetch_page"] == "read"


@pytest.mark.parametrize("preset", READER_FIRST)
def test_the_reader_first_presets_install_with_the_framework(client, preset):
    from app import presets
    from app.agents import registry
    from app.agents.tools import HUB_TOOLS
    from app.db import KnowledgeDoc, Skill, session

    assert asyncio.run(presets.install(preset)) == (preset, "created")
    agent = registry.get(preset)
    assert set(agent.tools) <= {t.name for t in HUB_TOOLS}
    assert "find_client_docs" in agent.tools
    with session() as s:
        titles = {d.title for d in s.exec(select(KnowledgeDoc)).all()
                  if d.id in agent.knowledge_ids}
        skills = {k.name for k in s.exec(select(Skill)).all() if k.id in agent.skill_ids}
    assert titles == {"Reader-First Framework", "B2B Moments Library"}
    if preset == "reader_researcher":
        assert skills == {"lens_horizon", "lens_moment", "lens_tribe", "lens_gap"}
    if preset == "moment_writer":
        assert skills == {"format_linkedin", "format_email_3", "format_exec_brief",
                          "format_video_script"}
    for name in skills:  # every skill an agent is told to load exists
        assert name in agent.instructions
    assert agent.templates and "Client:" in agent.templates[0]["description"]
    assert asyncio.run(presets.install(preset))[1] == "unchanged"


def test_the_team_shares_one_copy_of_the_framework(client):
    from app import presets
    from app.db import KnowledgeDoc, session

    for p in READER_FIRST:
        asyncio.run(presets.install(p))
    with session() as s:
        titles = [d.title for d in s.exec(select(KnowledgeDoc)).all()]
    assert titles.count("Reader-First Framework") == 1
