from web import create_app

from .samples import SAMPLES


def make_client(tmp_path, db_url):
    app = create_app(db_path=db_url, pdf_dir=str(tmp_path / "pdf"))
    return app.test_client()


def test_page_loads(tmp_path, db_url):
    c = make_client(tmp_path, db_url)
    r = c.get("/")
    assert r.status_code == 200 and b"Kwacha Books" in r.data


def test_chat_and_books(tmp_path, db_url):
    c = make_client(tmp_path, db_url)
    assert "Reply *YES*" in c.post("/api/message", json={"text": "hi"}).get_json()["replies"][0]["text"]
    c.post("/api/message", json={"text": "yes"})
    c.post("/api/message", json={"text": "sale 100 bread"})
    books = c.get("/api/books").get_json()
    assert books["consented"] is True
    assert books["totals"]["in"] == 100 and books["totals"]["cash"] == 100
    assert books["entries"][0]["who"] == "bread"


def test_statement_download_and_reset(tmp_path, db_url):
    c = make_client(tmp_path, db_url)
    c.post("/api/message", json={"text": "yes"})
    c.post("/api/message", json={"text": SAMPLES[0][0]})
    reply = c.post("/api/message", json={"text": "statement"}).get_json()["replies"][0]
    pdf = c.get(reply["document"])
    assert pdf.status_code == 200 and pdf.data[:4] == b"%PDF"
    assert c.get("/api/statement/../../etc/passwd").status_code == 404
    c.post("/api/reset", json={})
    assert c.get("/api/books").get_json()["consented"] is False
