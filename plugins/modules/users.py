from ansible.module_utils.basic import AnsibleModule

from ansible_collections.eraga.matrix.plugins.module_utils.runner import (
    CONNECTION_ARGS, USER_OPTIONS, make_api, run, run_all)
from ansible_collections.eraga.matrix.plugins.module_utils.sync import sync_user

DOCUMENTATION = r'''
module: users
short_description: Sync profiles of many Matrix users in one go
description:
  - Sets display name, avatar and admin flag of every listed user that the
    server has. A user the server does not have is skipped and listed in
    C(missing); it is never created.
  - All users go through one connection, C(concurrency) requests at a time.
  - An avatar is uploaded only when its source picture changed; the upload
    name carries a hash of the source, so where the sync runs does not matter.
options:
  users:
    description: Users to sync, each with C(login) and optional C(displayname), C(avatar) (URL or path), C(admin).
    type: list
    elements: dict
    required: true
  concurrency:
    description: Requests in flight at once.
    type: int
    default: 8
'''

EXAMPLES = r'''
- name: Matrix profiles follow Hub
  eraga.matrix.users:
    matrix_uri: "https://matrix.example.com"
    matrix_token: "{{ token }}"
    matrix_domain: example.com
    users:
      - login: ivan
        displayname: Ivan Kalinin
        avatar: "https://hub.example.com/api/rest/avatar/42"
'''


def main():
    module = AnsibleModule(
        argument_spec=dict(
            **CONNECTION_ARGS,
            users=dict(type="list", elements="dict", required=True, options=USER_OPTIONS),
            concurrency=dict(type="int", default=8),
        ),
        supports_check_mode=True,
    )

    async def go():
        api = make_api(module, module.params["concurrency"])
        try:
            return await run_all(module.params["users"], lambda u: sync_user(api, **u), "login")
        finally:
            await api.close()

    results, failed = run(go())
    changed = [r for r in results if r["changed"]]
    out = dict(
        changed=bool(changed),
        users=results,
        updated=[r["login"] for r in changed],
        missing=sorted(r["login"] for r in results if not r["exists"]),
        errors=failed,
    )
    if failed:
        module.fail_json(msg="{} of {} users failed".format(len(failed), len(module.params["users"])), **out)
    module.exit_json(**out)


if __name__ == "__main__":
    main()
