"""OpenAPI schema regression tests for Website Builder endpoints."""
import subprocess

import yaml
from django.test import TestCase


class WebsiteBuilderOpenAPISchemaTests(TestCase):
    SCHEMA_PATH = "/tmp/website_builder_schema.yml"

    def _generate_schema(self) -> dict:
        result = subprocess.run(
            ["python", "manage.py", "spectacular", "--file", self.SCHEMA_PATH],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        with open(self.SCHEMA_PATH, encoding="utf-8") as schema_file:
            return yaml.safe_load(schema_file)

    def test_generated_schema_contains_website_builder_components(self):
        schema = self._generate_schema()
        components = schema["components"]["schemas"]

        self.assertIn("HomepageLayout", components)
        self.assertIn("BranchContentOverrides", components)
        self.assertIn("WebsiteMediaUploadRequest", components)
        self.assertIn("WebsiteMediaUploadResponse", components)

    def test_generated_schema_contains_endpoint_response_bodies(self):
        schema = self._generate_schema()
        paths = schema["paths"]

        layout_get = paths["/api/tenants/{tenant_id}/website/layout/"]["get"]["responses"]["200"]
        layout_put = paths["/api/tenants/{tenant_id}/website/layout/"]["put"]["responses"]["200"]
        overrides_get = paths[
            "/api/tenants/{tenant_id}/branches/{branch_id}/website/overrides/"
        ]["get"]["responses"]["200"]
        overrides_put = paths[
            "/api/tenants/{tenant_id}/branches/{branch_id}/website/overrides/"
        ]["put"]["responses"]["200"]
        media_post = paths["/api/tenants/{tenant_id}/website/media/"]["post"]["responses"]["201"]

        self.assertIn("$ref", layout_get["content"]["application/json"]["schema"])
        self.assertIn("HomepageLayout", layout_get["content"]["application/json"]["schema"]["$ref"])

        self.assertIn("$ref", layout_put["content"]["application/json"]["schema"])
        self.assertIn("HomepageLayout", layout_put["content"]["application/json"]["schema"]["$ref"])

        self.assertIn("$ref", overrides_get["content"]["application/json"]["schema"])
        self.assertIn(
            "BranchContentOverrides",
            overrides_get["content"]["application/json"]["schema"]["$ref"],
        )

        self.assertIn("$ref", overrides_put["content"]["application/json"]["schema"])
        self.assertIn(
            "BranchContentOverrides",
            overrides_put["content"]["application/json"]["schema"]["$ref"],
        )

        self.assertIn("$ref", media_post["content"]["application/json"]["schema"])
        self.assertIn(
            "WebsiteMediaUploadResponse",
            media_post["content"]["application/json"]["schema"]["$ref"],
        )
