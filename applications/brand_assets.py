"""Two immutable public artwork URLs retained by the replacement service (bgl.2).

Owner-supplied official artwork is reproduced unchanged. These fixed routes do not
expose a directory or accept a caller-provided filesystem path.
"""

from pathlib import Path

from django.http import FileResponse, Http404
from django.views.decorators.http import require_safe

DIRECTORY = Path(__file__).resolve().parent / "assets"
ASSETS = {
    "select-services-partner-e4897387bbdb.svg": (
        "image/svg+xml",
        "e4897387bbdb066939e3d128db75ac881dffdc7152917896354725be593e59ed",
    ),
    "select-services-partner-c96bbd4b0d98.png": (
        "image/png",
        "c96bbd4b0d988367418d2b026e1f2021a56e43b27810c568bcff5536608b7cba",
    ),
}


@require_safe
def partner_asset(request, name):
    if name not in ASSETS:
        raise Http404
    content_type, digest = ASSETS[name]
    response = FileResponse((DIRECTORY / name).open("rb"), content_type=content_type)
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["ETag"] = f'"{digest}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response
