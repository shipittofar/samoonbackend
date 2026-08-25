"""Shared tenant summary attachment for public menu endpoints."""
from __future__ import annotations

from menu.services.menu_bll import MenuBusinessLogicLayer

menu_bll = MenuBusinessLogicLayer()


class MenuPublicTenantSummaryMixin:
    """Attach branch tenant visibility/usability summary to paginated list responses."""

    def _resolve_branch_id_for_summary(self):
        branch_id = self.kwargs.get("branch_id")
        if branch_id is None:
            branch_id = self.request.query_params.get("branch_id")
        return branch_id

    def _attach_tenant_summary(self, response):
        if isinstance(response.data, dict):
            branch_id = self._resolve_branch_id_for_summary()
            if branch_id:
                response.data.update(menu_bll.get_branch_tenant_summary(branch_id))
        return response

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return self._attach_tenant_summary(response)


def tenant_summary_for_branch(branch_id) -> dict:
    """Return ``{"tenant": ...}`` for the given branch (one query)."""
    return menu_bll.get_branch_tenant_summary(branch_id)


def wrap_public_menu_results(branch_id, results: list) -> dict:
    """Envelope list payloads with a top-level tenant summary."""
    return {
        **tenant_summary_for_branch(branch_id),
        "results": results,
    }
