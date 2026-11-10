"""Unit tests for the frontend static assets and chat UI serving."""

from starlette.testclient import TestClient


def test_root_serves_chat_ui(client: TestClient) -> None:
    """Test that GET / serves the Phase 6 chat UI HTML."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    html = response.text

    # App title and core UI elements
    assert "Excel AI" in html
    assert 'id="modelStatus"' in html
    assert 'id="excelStatus"' in html
    assert 'id="headerUndoBtn"' in html
    assert 'id="chatLog"' in html
    assert 'id="promptInput"' in html
    assert 'id="sendBtn"' in html

    # Example chips
    assert "Convert headers to camelCase" in html
    assert "Trim spaces in Full Name" in html
    assert "Make Department uppercase" in html
    assert "Keep only digits in Phone" in html


def test_styles_css_served(client: TestClient) -> None:
    """Test that GET /styles.css serves the stylesheet."""
    response = client.get("/styles.css")
    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    assert "text/css" in content_type
    assert "--font-family" in response.text
    assert "--excel-green" in response.text


def test_app_js_served(client: TestClient) -> None:
    """Test that GET /app.js serves the frontend JavaScript."""
    response = client.get("/app.js")
    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    assert "javascript" in content_type
    assert "postSSE" in response.text
    assert "pollHealth" in response.text
    assert "submitInstruction" in response.text
    assert "Office.onReady" in response.text


def test_office_js_served(client: TestClient) -> None:
    """Test that GET /vendor/office/office.js serves local office.js."""
    response = client.get("/vendor/office/office.js")
    assert response.status_code == 200
    assert "javascript" in response.headers.get("content-type", "")
    assert len(response.content) > 1000


def test_icons_served(client: TestClient) -> None:
    """Test that all three icon resolutions are served from /assets/."""
    for size in (16, 32, 80):
        response = client.get(f"/assets/icon-{size}.png")
        assert response.status_code == 200
        assert "image/png" in response.headers.get("content-type", "")
        # Verify valid PNG magic header bytes
        assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_manifest_xml_structure() -> None:
    """Test that addin/manifest.xml is present and correctly structured."""
    import xml.etree.ElementTree as ET
    from pathlib import Path

    manifest_path = Path("addin/manifest.xml")
    assert manifest_path.exists(), "addin/manifest.xml must exist"

    tree = ET.parse(manifest_path)
    root = tree.getroot()

    assert "OfficeApp" in root.tag
    assert root.attrib.get("{http://www.w3.org/2001/XMLSchema-instance}type") == "TaskPaneApp"

    # Verify key metadata
    id_elem = root.find("{http://schemas.microsoft.com/office/appforoffice/1.1}Id")
    assert id_elem is not None and len(id_elem.text or "") == 36

    display_name = root.find("{http://schemas.microsoft.com/office/appforoffice/1.1}DisplayName")
    assert display_name is not None and display_name.attrib.get("DefaultValue") == "Excel AI (Local)"

    source_loc = root.find(
        "{http://schemas.microsoft.com/office/appforoffice/1.1}DefaultSettings"
    ).find("{http://schemas.microsoft.com/office/appforoffice/1.1}SourceLocation")
    assert source_loc is not None
    assert source_loc.attrib.get("DefaultValue") == "https://localhost:8443/index.html"


