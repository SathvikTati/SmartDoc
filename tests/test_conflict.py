"""Documents that disagree, and which one the answer should believe."""

from datetime import datetime

from port6.services.rag.base import RetrievedChunk
from port6.services.rag.conflict import (
    KEY_WORDS,
    claims_in,
    context_note,
    find_conflicts,
)


def chunk(number, document_id, filename, content, uploaded=None):
    return RetrievedChunk(
        number=number,
        chunk_id=f"c{number}",
        document_id=document_id,
        filename=filename,
        content=content,
        uploaded_at=uploaded,
    )


OLD = datetime(2026, 1, 10)
NEW = datetime(2026, 8, 18)


# --- reading a figure out of a sentence -------------------------------

class TestClaims:

    def test_a_figure_carries_what_it_measures(self):
        found = claims_in(
            chunk(1, "d", "f", "Employees accrue 22 days of paid annual leave.")
        )

        assert len(found) == 1
        assert found[0].value == "22"
        assert found[0].key == ("day", "paid", "annual", "leave")

    def test_filler_words_do_not_change_the_key(self):
        """"22 days of paid annual leave" and "22 days paid annual leave"
        describe the same thing and must compare equal."""

        with_filler = claims_in(chunk(1, "d", "f", "22 days of paid annual leave"))
        without = claims_in(chunk(2, "d", "f", "22 days paid annual leave"))

        assert with_filler[0].key == without[0].key

    def test_plurals_agree_with_singulars(self):
        plural = claims_in(chunk(1, "d", "f", "26 weeks of maternity leave"))
        single = claims_in(chunk(2, "d", "f", "26 week of maternity leave"))

        assert plural[0].key == single[0].key

    def test_a_bare_number_is_not_a_claim(self):
        assert claims_in(chunk(1, "d", "f", "See 42.")) == []

    def test_the_key_is_bounded(self):
        found = claims_in(
            chunk(1, "d", "f", "22 alpha beta gamma delta epsilon zeta")
        )

        assert len(found[0].key) == KEY_WORDS


# --- deciding what counts as a conflict -------------------------------

class TestFindConflicts:

    def test_two_documents_disagreeing_is_a_conflict(self):
        conflicts = find_conflicts([
            chunk(1, "d1", "hr_policy.md",
                  "Employees accrue 22 days of paid annual leave.", OLD),
            chunk(2, "d2", "hr_policy_2027.md",
                  "Employees accrue 25 days of paid annual leave.", NEW),
        ])

        assert len(conflicts) == 1
        assert conflicts[0].current.value == "25"
        assert conflicts[0].current.filename == "hr_policy_2027.md"
        assert [c.value for c in conflicts[0].superseded] == ["22"]

    def test_different_measurements_are_not_a_conflict(self):
        """Both say "N days ... leave", but of different kinds."""

        conflicts = find_conflicts([
            chunk(1, "d1", "a.md", "Employees accrue 22 days of paid annual leave.", OLD),
            chunk(2, "d2", "b.md", "Employees receive 12 days of paid sick leave.", NEW),
        ])

        assert conflicts == []

    def test_documents_that_agree_are_not_reported(self):
        conflicts = find_conflicts([
            chunk(1, "d1", "a.md", "Employees accrue 22 days of paid annual leave.", OLD),
            chunk(2, "d2", "b.md", "Employees accrue 22 days of paid annual leave.", NEW),
        ])

        assert conflicts == []

    def test_one_document_listing_two_figures_is_a_table_not_a_conflict(self):
        conflicts = find_conflicts([
            chunk(1, "d1", "a.md", "Grade A: 22 days of paid annual leave.", OLD),
            chunk(2, "d1", "a.md", "Grade B: 25 days of paid annual leave.", OLD),
        ])

        assert conflicts == []

    def test_the_newest_upload_wins(self):
        conflicts = find_conflicts([
            chunk(1, "d2", "newer.md", "Employees accrue 25 days of paid annual leave.", NEW),
            chunk(2, "d1", "older.md", "Employees accrue 22 days of paid annual leave.", OLD),
        ])

        assert conflicts[0].current.filename == "newer.md"

    def test_a_document_without_an_upload_time_does_not_win_by_default(self):
        """Ordering must not hand the answer to a document just because
        its timestamp is missing."""

        conflicts = find_conflicts([
            chunk(1, "d1", "undated.md", "Employees accrue 22 days of paid annual leave."),
            chunk(2, "d2", "dated.md", "Employees accrue 25 days of paid annual leave.", OLD),
        ])

        assert conflicts[0].current.filename == "dated.md"

    def test_a_calculation_is_not_a_competing_document(self):
        conflicts = find_conflicts([
            chunk(1, "d1", "a.md", "Employees accrue 22 days of paid annual leave.", OLD),
            chunk(2, "calculation", "calculator", "22 days of paid annual leave = 25", NEW),
        ])

        assert conflicts == []

    def test_a_web_result_is_not_a_competing_document(self):
        web = chunk(2, "web", "gov.uk", "Employees accrue 25 days of paid annual leave.", NEW)
        web.url = "https://gov.uk/leave"

        conflicts = find_conflicts([
            chunk(1, "d1", "a.md", "Employees accrue 22 days of paid annual leave.", OLD),
            web,
        ])

        assert conflicts == []


# --- what the model is told -------------------------------------------

class TestContextNote:

    def test_no_conflicts_means_no_note(self):
        assert context_note([]) == ""

    def test_the_note_names_both_figures_and_the_winner(self):
        conflicts = find_conflicts([
            chunk(1, "d1", "hr_policy.md",
                  "Employees accrue 22 days of paid annual leave.", OLD),
            chunk(2, "d2", "hr_policy_2027.md",
                  "Employees accrue 25 days of paid annual leave.", NEW),
        ])

        note = context_note(conflicts)

        assert "disagree" in note
        assert "hr_policy_2027.md says 25" in note
        assert "hr_policy.md says 22" in note
        assert "most recent" in note
