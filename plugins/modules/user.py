import asyncio
import copy

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.eraga.matrix.plugins.module_utils.room_model import *
from ansible_collections.eraga.matrix.plugins.module_utils.user import AnsibleMatrixUser

ANSIBLE_METADATA = {
    'metadata_version': '1.0',
    'status': ['preview'],
    'supported_by': 'curated'
}

"""
- name: User exists
  eraga.matrix.user:
    matrix_uri: "https://matrix.example.com"
    matrix_user:  ansiblebot
    matrix_token: "{{token}}"
    matrix_domain: example.com
    login: someone     
"""


async def run_module():
    # define the available arguments/parameters that a user can pass to
    # the module
    module_args = dict(
        matrix_uri=dict(type="str", required=True),
        matrix_user=dict(type="str", required=True),
        matrix_domain=dict(type="str", required=True),
        matrix_token=dict(type="str", required=True, no_log=True),

        login=dict(type='str', required=True),
        displayname=dict(type='str', default=None),
        avatar=dict(type='str', default=None),

        # name=dict(type='str', default=None),
        # topic=dict(type='str', default=None),
        # federate=dict(type='bool', default=False),
        # visibility=dict(type='str', default="private",
        #                 choices=["private", "public"]),
        # preset=dict(type='str', default=None,
        #             choices=["private_chat", "trusted_private_chat", "public_chat"]),
        # room_members=dict(type='dict', default=None),
        # power_level_override=dict(type='dict', default=None),
        # encrypt=dict(type='bool', default=False),
        #
        # community=dict(type='str', default=None),

        state=dict(type="str", default="present",
                   choices=["present", "absent", "archived"])
    )

    # seed the result dict in the object
    # we primarily care about changed and state
    # change is if this module effectively modified the target
    # state will include any data that you want your module to pass back
    # for consumption, for example, in a subsequent task
    result = dict(
        user={},
        changed=False,
        changed_fields={}
    )

    # the AnsibleModule object will be our abstraction working with Ansible
    # this includes instantiation, a couple of common attr would be the
    # args/params passed to the execution, as well as if the module
    # supports check mode
    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True
    )

    state = module.params['state']

    matrix_client = AnsibleMatrixClient(
        domain=module.params["matrix_domain"],
        uri=module.params['matrix_uri'],
        token=module.params['matrix_token'],
        user=module.params['matrix_user']
    )

    user = AnsibleMatrixUser(
        matrix_client=matrix_client,
        login=module.params['login'],
        changes=result['changed_fields']
    )

    async with user:
        try:
            exists = user.account is not None
            if exists:
                result['user'] = user.account.dict()
                # del result['room']['power_levels']

            if module.check_mode:
                module.exit_json(**result)
                return result

            params = copy.deepcopy(module.params)
            del params['matrix_uri']
            del params['matrix_user']
            del params['matrix_domain']
            del params['matrix_token']
            del params['login']
            del params['state']

            if state == 'absent':
                pass
                # if room_exists:
                # await room.delete()
                # result['changed'] = bool(result['changed_fields'])
                # result['changed'] = api.delete(result['project']['id'])

            elif state == 'present':
                await user.update(**params)
                result['changed'] = bool(result['changed_fields'])
            #     else:
            #         await room.matrix_room_update(**room_params)
            #         result['changed'] = bool(result['changed_fields'])
            #
            # # elif state == 'archived':
            # #     if not result['project']['archived']:
            # #         result['changed_fields'] = api.update(project)
            # #         result['changed'] = result['changed_fields'] is not False
            #
            else:
                result['changed'] = bool(result['changed_fields'])
                module.fail_json(msg='Unsupported state={}'.format(state), **result)

            if result['changed']:
                result['user'] = user.account.dict()

        except MatrixError as e:
            result['changed'] = bool(result['changed_fields'])
            module.fail_json(msg='MatrixError={}'.format(e), **result)
        finally:
            await user.__aexit__()

    # print(result)
    module.exit_json(**result)


def main():
    asyncio.get_event_loop().run_until_complete(run_module())


if __name__ == '__main__':
    main()
