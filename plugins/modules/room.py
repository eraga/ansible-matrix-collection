import asyncio
import copy

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.eraga.matrix.plugins.module_utils.room import *

ANSIBLE_METADATA = {
    'metadata_version': '1.0',
    'status': ['preview'],
    'supported_by': 'curated'
}

"""
- name: Room exists in community:
  eraga.matrix.room:
    matrix_uri: "https://matrix.example.com"
    matrix_user:  ansiblebot
    matrix_token: "{{token}}"
    matrix_domain: example.com
    alias: example_room 
    name: Example Room
    topic: This is room managed by ansible 
    preset: trusted_private_chat
    avatar: "http://example.com/path/to/avatar.png"
    
- name: Room exists and is part of 'test' and 'prod' community
  eraga.matrix.room:
    matrix_uri: "https://matrix.example.com"
    matrix_user:  ansiblebot
    matrix_token: "{{token}}"
    matrix_domain: example.com
    alias: example_room 
    name: Example Room
    topic: This is room managed by ansible 
    federate: no
    visibility: private
    preset: trusted_private_chat
    avatar: "/path/to/avatar.png"
    communities:
      - test
      - prod
    room_members:
      owner_login: 100
      admin_login: 90
      moderator_login: 0 
      user_login: 0 
    power_level_override:
      events_default: 0
      state_default: 50
      ban: 50
      kick: 50
      redact: 50
      invite: 50
    community: Example    
"""

async def run_module():
    # define the available arguments/parameters that a user can pass to
    # the module
    module_args = dict(
        matrix_uri=dict(type="str", required=True),
        matrix_user=dict(type="str", required=True),
        matrix_domain=dict(type="str", required=True),
        matrix_token=dict(type="str", required=True, no_log=True),

        alias=dict(type='str', required=True),

        name=dict(type='str', default=None),
        topic=dict(type='str', default=None),
        avatar=dict(type='str', default=None),
        federate=dict(type='bool', default=False),
        visibility=dict(type='str', default="private",
                        choices=["private", "public"]),
        preset=dict(type='str', default=None,
                    choices=["private_chat", "trusted_private_chat", "public_chat"]),
        room_members=dict(type='dict', default=None),
        power_level_override=dict(type='dict', default=None),
        encrypt=dict(type='bool', default=False),

        communities=dict(type='list', default=None),

        state=dict(type="str", default="present",
                   choices=["present", "absent", "archived"])
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

    state = module.params['state']

    matrix_client = AnsibleMatrixClient(
        domain=module.params["matrix_domain"],
        uri=module.params['matrix_uri'],
        token=module.params['matrix_token'],
        user=module.params['matrix_user']
    )

    room = AnsibleMatrixRoom(
        matrix_client=matrix_client,
        matrix_room_alias=module.params['alias'],
        changes=result['changed_fields']
    )

    async with room:
        try:
            room_exists = room.matrix_room_exists()
            if room_exists:
                result['room'] = room.matrix_room_to_dict()
                # del result['room']['power_levels']

            if module.check_mode:
                module.exit_json(**result)
                return result

            room_params = copy.deepcopy(module.params)
            del room_params['matrix_uri']
            del room_params['matrix_user']
            del room_params['matrix_domain']
            del room_params['matrix_token']
            del room_params['alias']
            del room_params['state']

            if state == 'absent':
                if room_exists:
                    await room.delete()
                    result['changed'] = bool(result['changed_fields'])
                    # result['changed'] = api.delete(result['project']['id'])

            elif state == 'present':
                if not room_exists:
                    await room.matrix_room_create(**room_params)
                    result['changed'] = bool(result['changed_fields'])
                else:
                    await room.matrix_room_update(**room_params)
                    result['changed'] = bool(result['changed_fields'])

            # elif state == 'archived':
            #     if not result['project']['archived']:
            #         result['changed_fields'] = api.update(project)
            #         result['changed'] = result['changed_fields'] is not False

            else:
                result['changed'] = bool(result['changed_fields'])
                module.fail_json(msg='Unsupported state={}'.format(state), **result)

            if result['changed']:
                await matrix_client.sync()
                result['room'] = room.matrix_room_to_dict()

        except AnsibleMatrixError as e:
            result['changed'] = bool(result['changed_fields'])
            module.fail_json(msg='MatrixError={}'.format(e), **result)
        finally:
            await room.__aexit__()

    # print(result)
    module.exit_json(**result)


def main():
    asyncio.get_event_loop().run_until_complete(run_module())


if __name__ == '__main__':
    main()
