"""Shared plumbing of the user(s) and room(s) modules."""
import asyncio
import traceback
from typing import Any, Awaitable, Callable, Dict, List

from ansible_collections.eraga.matrix.plugins.module_utils.admin import MatrixApi
from ansible_collections.eraga.matrix.plugins.module_utils.client_model import AnsibleMatrixClient

CONNECTION_ARGS = dict(
    matrix_uri=dict(type="str", required=True),
    matrix_user=dict(type="str", default=None),
    matrix_domain=dict(type="str", required=True),
    matrix_token=dict(type="str", required=True, no_log=True),
)

USER_OPTIONS = dict(
    login=dict(type="str", required=True),
    displayname=dict(type="str", default=None),
    avatar=dict(type="str", default=None),
    admin=dict(type="bool", default=None),
)

ROOM_OPTIONS = dict(
    alias=dict(type="str", required=True),
    name=dict(type="str", default=None),
    topic=dict(type="str", default=None),
    avatar=dict(type="str", default=None),
    federate=dict(type="bool", default=False),
    visibility=dict(type="str", default="private", choices=["private", "public"]),
    preset=dict(type="str", default=None, choices=["private_chat", "trusted_private_chat", "public_chat"]),
    room_members=dict(type="dict", default=None),
    power_level_override=dict(type="dict", default=None),
    encrypt=dict(type="bool", default=False),
    # Matrix communities are gone from Synapse; accepted and ignored so old plays still parse.
    communities=dict(type="list", elements="str", default=None),
)


def make_api(module, concurrency: int = 8) -> MatrixApi:
    client = AnsibleMatrixClient(
        domain=module.params["matrix_domain"],
        uri=module.params["matrix_uri"],
        token=module.params["matrix_token"],
        user=module.params["matrix_user"],
    )
    return MatrixApi(client, check_mode=module.check_mode, concurrency=concurrency)


async def run_all(items: List[Dict[str, Any]], one: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]],
                  key: str) -> (List[Dict[str, Any]], List[Dict[str, Any]]):
    """Run every item; one failure does not stop the others."""
    async def guarded(item):
        try:
            return await one(item), None
        except Exception as e:  # reported per item, the module fails at the end
            return None, {key: item.get(key), "error": "{}: {}".format(type(e).__name__, e),
                          "trace": traceback.format_exc(limit=5)}

    done = await asyncio.gather(*(guarded(i) for i in items))
    return [r for r, _ in done if r is not None], [e for _, e in done if e is not None]


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
