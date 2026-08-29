"""Operational views for the config project (not tied to any app)."""

from django.http import HttpRequest, JsonResponse


def healthcheck(request: HttpRequest) -> JsonResponse:
    """Report liveness for load balancer / CDN health checks.

    Args:
        request: The incoming request.

    Returns:
        A 200 JSON response with a static status payload.
    """
    return JsonResponse({"status": "ok"})
