import json
import re
from pathlib import Path

import pytest

from bmwow.knowledge.catalog import prepare_catalog
from bmwow.knowledge.local_review import render_local_review
from tests.knowledge.test_catalog import make_manifest, synthetic_pdf


def test_local_source_text_cannot_escape_into_executable_html(tmp_path):
    source = tmp_path / "invented.pdf"
    synthetic_pdf(source)
    manifest = make_manifest()
    attack = '</script><img src="https://invalid.example/" onerror="alert(1)"> & original'
    manifest.context_nodes[-1].label = attack
    catalog = prepare_catalog(source)
    rendered = render_local_review(manifest, catalog)
    payload = re.search(r'<script id="payload" type="application/json">(.*?)</script>', rendered)
    assert payload
    parsed = json.loads(payload[1])
    assert parsed["manifest"]["context_nodes"][-1]["label"] == attack
    assert attack not in rendered
    assert "connect-src 'none'" in rendered
    assert "fetch(" not in rendered and "__BMWOW_REVIEW_PAYLOAD__" not in rendered
    assert parsed["catalog"]["claims"][0]["status"] == "proposed"
    assert manifest.pending_decisions == parsed["manifest"]["pending_decisions"]


def test_changed_original_cannot_be_embedded_under_old_review_hash(tmp_path):
    source = tmp_path / "invented.pdf"
    synthetic_pdf(source)
    catalog = prepare_catalog(source)
    Path(catalog.source_file).write_bytes(source.read_bytes() + b"\n% changed source")
    with pytest.raises(ValueError, match="source changed"):
        render_local_review(make_manifest(), catalog)
