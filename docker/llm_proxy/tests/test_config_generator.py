import json
import os
import stat
import tempfile

import pytest

from llm_proxy.config_generator import generate_opencode_configs
from llm_proxy.models import ModelObject
from llm_proxy.provider_base import ProviderAdapter
from llm_proxy.provider_registry import ProviderRegistry


class FakeAdapter(ProviderAdapter):
    @property
    def provider_id(self) -> str:
        return "fake"

    @property
    def display_name(self) -> str:
        return "Fake Provider"

    async def initialize(self) -> None:
        pass

    def get_models(self) -> list[ModelObject]:
        return [
            ModelObject(id="model-a", created=0, owned_by="fake"),
            ModelObject(id="model-b", created=0, owned_by="fake"),
        ]

    def get_opencode_model_config(self) -> list[dict]:
        return [
            {
                "id": "model-a",
                "name": "Model A",
                "can_reason": False,
                "supports_attachments": False,
                "context_window": 200000,
                "default_max_tokens": 16000,
                "cost_per_1m_in": 0,
                "cost_per_1m_out": 0,
                "cost_per_1m_in_cached": 0,
                "cost_per_1m_out_cached": 0,
            },
            {
                "id": "model-b",
                "name": "Model B",
                "can_reason": True,
                "supports_attachments": False,
                "context_window": 200000,
                "default_max_tokens": 16000,
                "cost_per_1m_in": 0,
                "cost_per_1m_out": 0,
                "cost_per_1m_in_cached": 0,
                "cost_per_1m_out_cached": 0,
            },
        ]

    async def chat_completion(self, request, credentials):
        pass

    async def chat_completion_stream(self, request, credentials):
        pass


class TestConfigGenerator:
    def test_creates_json_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ProviderRegistry()
            registry.register(FakeAdapter())
            generate_opencode_configs(registry, tmpdir)

            json_path = os.path.join(tmpdir, "opencode_provider_fake.json")
            assert os.path.exists(json_path)

            with open(json_path) as f:
                data = json.load(f)
            assert "fake" in data
            assert data["fake"]["name"] == "Fake Provider"

    def test_creates_executable_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ProviderRegistry()
            registry.register(FakeAdapter())
            generate_opencode_configs(registry, tmpdir)

            script_path = os.path.join(tmpdir, "update_opencode_config.sh")
            assert os.path.exists(script_path)
            assert os.stat(script_path).st_mode & stat.S_IEXEC

    def test_json_contains_all_models(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ProviderRegistry()
            registry.register(FakeAdapter())
            generate_opencode_configs(registry, tmpdir)

            json_path = os.path.join(tmpdir, "opencode_provider_fake.json")
            with open(json_path) as f:
                data = json.load(f)
            assert len(data["fake"]["models"]) == 2

    def test_json_has_correct_base_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ProviderRegistry()
            registry.register(FakeAdapter())
            generate_opencode_configs(registry, tmpdir)

            json_path = os.path.join(tmpdir, "opencode_provider_fake.json")
            with open(json_path) as f:
                data = json.load(f)
            assert data["fake"]["base_url"] == "http://localhost:4141/fake/v1"

    def test_creates_output_dir_if_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "nested", "output")
            registry = ProviderRegistry()
            registry.register(FakeAdapter())
            generate_opencode_configs(registry, nested)
            assert os.path.isdir(nested)
