import asyncio
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.eraga.matrix.plugins.module_utils.room import *

ANSIBLE_METADATA = {
    'metadata_version': '1.0',
    'status': ['preview'],
    'supported_by': 'curated'
}

"""
- name: Send text to room
  eraga.matrix.send:
    matrix_uri: "https://matrix.example.com"
    matrix_user:  ansiblebot
    matrix_token: "{{token}}"
    matrix_domain: example.com
    room: example_room 
    text: Example Room
    notice: yes    
"""


async def run_module():
    # define the available arguments/parameters that a user can pass to
    # the module
    module_args = dict(
        matrix_uri=dict(type="str", required=True),
        matrix_user=dict(type="str", required=True),
        matrix_domain=dict(type="str", required=True),
        matrix_token=dict(type="str", required=True, no_log=True),

        room=dict(type='str', required=True),

        text=dict(type='str', required=True),
        notice=dict(type='bool', default=False),
    )

    # seed the result dict in the object
    # we primarily care about changed and state
    # change is if this module effectively modified the target
    # state will include any data that you want your module to pass back
    # for consumption, for example, in a subsequent task
    result = dict(
        room={},
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

    matrix_client = AnsibleMatrixClient(
        domain=module.params["matrix_domain"],
        uri=module.params['matrix_uri'],
        token=module.params['matrix_token'],
        user=module.params['matrix_user']
    )

    room = AnsibleMatrixRoom(
        matrix_client=matrix_client,
        matrix_room_alias=module.params['room'],
        changes=result['changed_fields']
    )

    async with room:
        try:
            room_exists = room.matrix_room_exists()
            if not room_exists:
                module.fail_json(msg='No room with alias="{}"'.format(module.params['room']), **result)
                return

            result['room'] = room.matrix_room_to_dict()

            if module.check_mode:
                module.exit_json(**result)
                return result

            await room.send_text(
                message=module.params['text'],
                notice=module.params['notice']
            )
            result['changed'] = bool(result['changed_fields'])

        except AnsibleMatrixError as e:
            module.fail_json(msg='MatrixError={}'.format(e), **result)
        finally:
            await room.__aexit__()

    # print(result)
    module.exit_json(**result)


def main():
    asyncio.get_event_loop().run_until_complete(run_module())


if __name__ == '__main__':
    main()
