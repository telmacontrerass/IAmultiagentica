from ci2lab.harness.document_answer import maybe_answer_document_request


def test_maybe_answer_document_request_extracts_main_ideas():
    document = """Documento: prueba.pdf
Tipo: pdf
Paginas/secciones: 3 paginas
Texto extraido:

[PDF page 1/3]
ACADEMIC ENGLISH: FORMAL VS INFORMAL REGISTER
The document explains that informal writing uses colloquial words, phrasal verbs,
contractions and abbreviations.
Formal academic writing uses passive voice, words of Latin origin, relative clauses
and an impersonal tone.
The table compares formal and informal equivalents such as friend and mate.
"""

    answer = maybe_answer_document_request(
        "dime las ideas principales de prueba.pdf",
        [document],
    )

    assert answer is not None
    assert "ideas principales" in answer.lower()
    assert "formal" in answer.lower()
    assert "informal" in answer.lower()


def test_maybe_answer_document_request_detects_english_summary_prompt():
    document = """Documento: derivatives.pdf
Tipo: pdf
Paginas/secciones: 2 paginas
Texto extraido:

Lesson 5. Financial derivatives
A derivative is an instrument whose value depends on the value of another asset.
The four basic derivatives are forwards, futures, swaps and options.
Exchange traded derivatives are standardized and normally go through a clearing house.
"""

    answer = maybe_answer_document_request(
        "Summarise this document for me",
        [document],
    )

    assert answer is not None
    assert "derivative" in answer.lower()
