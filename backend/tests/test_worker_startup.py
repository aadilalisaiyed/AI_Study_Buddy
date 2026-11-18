from subprocess import run
from sys import executable


def test_standalone_worker_registers_document_foreign_keys():
    result = run([executable, "-c", """
from app.document_worker import Document
assert {key.column.table.name for key in Document.__table__.foreign_keys} == {"users", "subjects"}
"""], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
