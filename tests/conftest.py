import os
import re
import tempfile

import pytest

_DB = os.path.join(tempfile.mkdtemp(prefix="mrigel-test-"), "test.db")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_DB}",
    "SECRET_KEY": "test-secret",
    "RUN_JOBS": "0",
    "DEMO_MODE": "0",
    "GEMINI_API_KEY": "",
    "CRON_TOKEN": "cron-test",
})

from fastapi.testclient import TestClient  # noqa: E402

from app import ratelimit  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

CSRF = re.compile(r'name="csrf" value="([^"]+)"')


@pytest.fixture(autouse=True)
def fresh_db():
    from app import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    ratelimit.reset()
    yield


class Client(TestClient):
    def csrf(self, path: str = "/signup") -> str:
        page = self.get(path)
        match = CSRF.search(page.text)
        assert match, f"no csrf on {path}"
        return match.group(1)

    def post_form(self, path: str, data: dict, from_page: str = "/dashboard", **kwargs):
        data = dict(data)
        data.setdefault("csrf", self.csrf(from_page))
        return self.post(path, data=data, **kwargs)


def make_client() -> Client:
    return Client(app, base_url="http://testserver")


def signup(client: Client, store="Boutique Test", email="owner@test.dz", password="password123", name="Owner"):
    response = client.post("/signup", data={"csrf": client.csrf("/signup"), "store_name": store, "name": name,
                                            "email": email, "password": password}, follow_redirects=False)
    assert response.status_code == 303, response.text[:500]
    return response


@pytest.fixture
def client():
    with make_client() as c:
        yield c


@pytest.fixture
def owner(client):
    signup(client)
    return client


def new_order(client: Client, **overrides) -> str:
    data = {"customer_name": "Amina Benali", "phone": "0555 12 34 56", "wilaya": "16", "commune": "Bab Ezzouar",
            "address": "Cité 5 Juillet", "delivery_type": "home", "product": "Crème", "qty": "1", "total": "2500",
            "delivery_fee": "400"}
    data.update(overrides)
    response = client.post_form("/orders/new", data, follow_redirects=False)
    assert response.status_code == 303, response.text[:500]
    return response.headers["location"].rsplit("/", 1)[-1]
