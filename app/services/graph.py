"""Microsoft Graph integration for reading/writing the GAPNINJA control-list
workbook stored on SharePoint.

Uses the MSAL client-credentials (app-only) flow, the same Azure app
registration already used by the TBTS web app. All credentials come from
environment variables — nothing sensitive is stored in this repository.
"""
from __future__ import annotations

import os
import threading
import time as _time

import httpx
import msal

GRAPH_CLIENT_ID = os.environ.get("GRAPH_CLIENT_ID", "")
GRAPH_TENANT_ID = os.environ.get("GRAPH_TENANT_ID", "")
GRAPH_CLIENT_SECRET = os.environ.get("GRAPH_CLIENT_SECRET", "")

SHAREPOINT_HOSTNAME = os.environ.get("SHAREPOINT_HOSTNAME", "")


def _normalise_site_path(raw: str) -> str:
    """Accept 'sites/Foo', '/sites/Foo', or a full URL and return '/sites/Foo'.

    Also tolerates a leading Windows path fragment, which some shells prepend
    when a value starts with '/'.
    """
    value = (raw or "").strip().replace("\\", "/")
    if "://" in value:  # full URL -> keep only the path
        value = "/" + value.split("://", 1)[1].split("/", 1)[-1]
    marker = "/sites/"
    if marker in value:
        value = marker + value.split(marker, 1)[1]
    return "/" + value.strip("/") if value else ""


SHAREPOINT_SITE_PATH = _normalise_site_path(os.environ.get("SHAREPOINT_SITE_PATH", ""))
EXCEL_ITEM_ID = os.environ.get("EXCEL_ITEM_ID", "")
EXCEL_FILE_PREFIX = os.environ.get("EXCEL_FILE_PREFIX", "Gap Ninja Machie Info List")
EXCEL_SHEET_NAME = os.environ.get("EXCEL_SHEET_NAME", "Gap Ninja Controll list")

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"

_token_cache: dict = {"token": None, "exp": 0.0}
_ids_cache: dict = {"site_id": None, "item_id": None}
_lock = threading.Lock()


class GraphError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(
        GRAPH_CLIENT_ID
        and GRAPH_TENANT_ID
        and GRAPH_CLIENT_SECRET
        and SHAREPOINT_HOSTNAME
        and SHAREPOINT_SITE_PATH
    )


def get_token() -> str:
    if not is_configured():
        raise GraphError(
            "Microsoft Graph is not configured. Set GRAPH_CLIENT_ID, GRAPH_TENANT_ID, "
            "GRAPH_CLIENT_SECRET, SHAREPOINT_HOSTNAME and SHAREPOINT_SITE_PATH."
        )
    with _lock:
        now = _time.time()
        if _token_cache["token"] and _token_cache["exp"] > now + 60:
            return _token_cache["token"]
        app = msal.ConfidentialClientApplication(
            GRAPH_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}",
            client_credential=GRAPH_CLIENT_SECRET,
        )
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        token = result.get("access_token")
        if not token:
            raise GraphError(
                f"Graph token error: {result.get('error_description', result.get('error'))}"
            )
        _token_cache["token"] = token
        _token_cache["exp"] = now + int(result.get("expires_in", 3600))
        return token


def _headers() -> dict:
    return {"Authorization": f"Bearer {get_token()}"}


def _request(method: str, url: str, **kwargs) -> httpx.Response:
    try:
        resp = httpx.request(method, url, headers=_headers(), timeout=60.0, **kwargs)
    except httpx.HTTPError as e:
        raise GraphError(f"Could not reach Microsoft Graph: {e}")
    if resp.status_code >= 400:
        raise GraphError(f"Graph API {resp.status_code}: {resp.text[:300]}")
    return resp


def resolve_ids() -> tuple[str, str]:
    """Return (site_id, item_id) for the workbook, caching the lookup."""
    with _lock:
        if _ids_cache["site_id"] and _ids_cache["item_id"]:
            return _ids_cache["site_id"], _ids_cache["item_id"]

    site = _request(
        "GET", f"{GRAPH_ROOT}/sites/{SHAREPOINT_HOSTNAME}:{SHAREPOINT_SITE_PATH}"
    ).json()
    site_id = site["id"]

    if EXCEL_ITEM_ID:
        item_id = EXCEL_ITEM_ID
    else:
        found = _request(
            "GET", f"{GRAPH_ROOT}/sites/{site_id}/drive/root/search(q='Gap Ninja')"
        ).json()
        match = next(
            (i for i in found.get("value", []) if i["name"].startswith(EXCEL_FILE_PREFIX)),
            None,
        )
        if not match:
            raise GraphError(f"Workbook starting with '{EXCEL_FILE_PREFIX}' not found.")
        item_id = match["id"]

    with _lock:
        _ids_cache["site_id"] = site_id
        _ids_cache["item_id"] = item_id
    return site_id, item_id


def _workbook_base() -> str:
    site_id, item_id = resolve_ids()
    return f"{GRAPH_ROOT}/sites/{site_id}/drive/items/{item_id}"


def file_info() -> dict:
    data = _request("GET", _workbook_base()).json()
    return {
        "name": data.get("name"),
        "lastModifiedDateTime": data.get("lastModifiedDateTime"),
        "webUrl": data.get("webUrl"),
        "size": data.get("size"),
    }


def read_used_range(sheet: str | None = None) -> dict:
    """Return the sheet's used range: {address, rowCount, columnCount, values}."""
    sheet = sheet or EXCEL_SHEET_NAME
    url = f"{_workbook_base()}/workbook/worksheets/{sheet}/usedRange(valuesOnly=true)"
    return _request("GET", url).json()


def write_cell(address: str, value, sheet: str | None = None) -> None:
    """Write a single cell, e.g. address='B6'. Only the named cell is touched."""
    sheet = sheet or EXCEL_SHEET_NAME
    url = f"{_workbook_base()}/workbook/worksheets/{sheet}/range(address='{address}')"
    _request("PATCH", url, json={"values": [[value]]})


def download_bytes() -> bytes:
    url = f"{_workbook_base()}/content"
    try:
        resp = httpx.get(url, headers=_headers(), timeout=120.0, follow_redirects=True)
    except httpx.HTTPError as e:
        raise GraphError(f"Could not download workbook: {e}")
    if resp.status_code >= 400:
        raise GraphError(f"Download failed {resp.status_code}: {resp.text[:200]}")
    return resp.content


def upload_backup(content: bytes, filename: str) -> dict:
    """Upload a backup copy next to the original workbook."""
    site_id, item_id = resolve_ids()
    parent = _request("GET", f"{GRAPH_ROOT}/sites/{site_id}/drive/items/{item_id}").json()
    parent_id = parent.get("parentReference", {}).get("id")
    if not parent_id:
        raise GraphError("Could not determine the workbook's parent folder for backup.")
    url = f"{GRAPH_ROOT}/sites/{site_id}/drive/items/{parent_id}:/{filename}:/content"
    try:
        resp = httpx.put(
            url,
            headers={
                **_headers(),
                "Content-Type": "application/vnd.ms-excel.sheet.macroEnabled.12",
            },
            content=content,
            timeout=180.0,
        )
    except httpx.HTTPError as e:
        raise GraphError(f"Backup upload failed: {e}")
    if resp.status_code >= 400:
        raise GraphError(f"Backup upload failed {resp.status_code}: {resp.text[:200]}")
    return resp.json()
