from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.models import NotebookCreate, NotebookResponse, NotebookUpdate
from open_notebook.domain.notebook import Notebook


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


def test_notebook_domain_model_id():
    nb = Notebook(name="Test Notebook", description="Test", model_id="model:test-llm")
    assert nb.model_id == "model:test-llm"
    assert "model_id" in Notebook.nullable_fields

    data = nb._prepare_save_data()
    assert data["model_id"] == "model:test-llm"


def test_notebook_api_models():
    create = NotebookCreate(name="Test", model_id="model:abc")
    assert create.model_id == "model:abc"

    update = NotebookUpdate(model_id="model:xyz")
    assert update.model_id == "model:xyz"
    assert "model_id" in update.model_fields_set

    resp = NotebookResponse(
        id="notebook:1",
        name="Test",
        description="",
        archived=False,
        created="2026-01-01T00:00:00",
        updated="2026-01-01T00:00:00",
        source_count=0,
        note_count=0,
        model_id="model:xyz",
    )
    assert resp.model_id == "model:xyz"


@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
def test_create_notebook_with_model_id(mock_repo_create, client):
    mock_repo_create.return_value = [
        {
            "id": "notebook:new",
            "name": "New NB",
            "description": "desc",
            "archived": False,
            "created": "2026-01-01 00:00:00",
            "updated": "2026-01-01 00:00:00",
            "model_id": "model:gpt-4",
        }
    ]

    response = client.post(
        "/api/notebooks",
        json={"name": "New NB", "description": "desc", "model_id": "model:gpt-4"},
    )
    assert response.status_code == 200
    assert response.json()["model_id"] == "model:gpt-4"


@patch("api.routers.notebooks.repo_query", new_callable=AsyncMock)
@patch("api.routers.notebooks._stamp_notebook_view", new_callable=AsyncMock)
def test_get_notebook_with_model_id(mock_stamp, mock_repo_query, client):
    mock_repo_query.return_value = [
        {
            "id": "notebook:1",
            "name": "My Notebook",
            "description": "",
            "archived": False,
            "created": "2026-01-01",
            "updated": "2026-01-01",
            "source_count": 2,
            "note_count": 3,
            "model_id": "model:claude-3-5",
        }
    ]

    response = client.get("/api/notebooks/notebook:1")
    assert response.status_code == 200
    assert response.json()["model_id"] == "model:claude-3-5"


@patch("open_notebook.domain.notebook.Notebook.get", new_callable=AsyncMock)
@patch.object(Notebook, "save", new_callable=AsyncMock)
@patch("api.routers.notebooks.repo_query", new_callable=AsyncMock)
def test_update_notebook_with_model_id(mock_repo_query, mock_save, mock_notebook_get, client):
    nb_instance = Notebook(
        id="notebook:1",
        name="Existing NB",
        description="",
        model_id=None,
    )
    mock_notebook_get.return_value = nb_instance

    mock_repo_query.return_value = [
        {
            "id": "notebook:1",
            "name": "Existing NB",
            "description": "",
            "archived": False,
            "created": "2026-01-01",
            "updated": "2026-01-01",
            "source_count": 0,
            "note_count": 0,
            "model_id": "model:updated-llm",
        }
    ]

    response = client.put(
        "/api/notebooks/notebook:1",
        json={"model_id": "model:updated-llm"},
    )
    assert response.status_code == 200
    assert nb_instance.model_id == "model:updated-llm"
    assert response.json()["model_id"] == "model:updated-llm"
