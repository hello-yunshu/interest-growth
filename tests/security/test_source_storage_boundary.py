from __future__ import annotations


def test_manual_source_cannot_smuggle_server_local_file_path(client):
    created = client.post(
        "/api/sources",
        json={
            "title": "malicious path attempt",
            "source_type": "document",
            "local_file": "/etc/passwd",
            "full_text_available": True,
        },
    )
    assert created.status_code == 200
    source = created.json()
    assert source["local_file"] == ""
    assert source["full_text_available"] is False
    assert client.get(f"/api/knowledge/sources/{source['id']}/file").status_code == 404
